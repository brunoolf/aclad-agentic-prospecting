"""Record provider outcomes; reconciliation never repeats the external effect."""
from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

from .approvals import record_result
from .learning import capture_correction
from .models import Event, ExternalRef, GateError, Payload, Record, ToolResult, now_utc, payload, utc
from .store import Store


def _next_action(store: Store, message: Record, sent_at: str) -> Payload | None:
    current = message.data.get('current_message', message.data['message'])
    if current.get('reviewed_response_id'):
        return None  # A reviewed answer does not resume the cold sequence.
    for plan in store.list('outreach_plan'):
        if plan.data.get('campaign_id') != message.data['campaign_id']:
            continue
        contact_steps = [step for step in plan.data.get('steps', [])
                         if step.get('contact_id') == current['contact_id']]
        for index, step in enumerate(contact_steps):
            if step.get('id') == current['plan_step_id'] and index + 1 < len(contact_steps):
                following = contact_steps[index + 1]
                due = utc(sent_at) + timedelta(days=following['delay_days'])
                return {'plan_step_id': following['id'], 'contact_id': current['contact_id'],
                        'due_at': due.isoformat().replace('+00:00', 'Z'),
                        'status': 'needs_review', 'operation': 'prepare_followup'}
    return None


def record_delivery(store: Store, result: ToolResult, message_id: str) -> Record:
    with store.transaction():
        message = store.get('message', message_id)
        action = store.get('action', result.action_id)
        if not message or not action or action.data.get('operation') not in {'email.send', 'email.create_draft'}:
            raise GateError('message_action_mismatch')
        expected_id = action.data.get('payload', {}).get('message_id', action.data.get('proposal_id'))
        if expected_id != message_id:
            raise GateError('message_action_mismatch')
        # Idempotency covers message, learning and proposed CRM activity, not just
        # the lower-level action result.
        confirmed = record_result(store, result)
        operation, status = action.data['operation'], confirmed.data['status']
        states = dict(message.data.get('recorded_action_states', {}))
        previous_status = states.get(result.action_id)
        if previous_status is None and result.action_id in message.data.get('recorded_action_ids', []):
            previous_status = {'unknown': 'unknown', 'failed': 'failed',
                               'drafted': 'succeeded', 'sent': 'succeeded'}.get(message.data.get('status'))
        if previous_status == status:
            return message
        data = dict(message.data)
        if status == 'succeeded':
            refs = confirmed.data['external_refs']
            data['reconciliation_required'] = False
            if operation == 'email.create_draft':
                data.update(status='drafted', draft_ref=refs[0], draft_action_id=action.id)
                data.pop('delivery_status', None)
            else:
                supplied_at = result.data.get('sent_at')
                sent_at = supplied_at if isinstance(supplied_at, str) else now_utc()
                try:
                    utc(sent_at)
                except GateError:
                    sent_at = now_utc()
                    supplied_at = None
                data.update(status='sent', delivery_status='sent', sent_ref=refs[0],
                            external_refs=refs, sent_at=sent_at,
                            sent_at_source='provider' if supplied_at else 'confirmation_received',
                            send_action_id=action.id)
                data['next_action'] = _next_action(store, message, sent_at)
                conversation = result.data.get('conversation_ref')
                if isinstance(conversation, dict):
                    try:
                        conversation_ref = ExternalRef(**conversation)
                    except TypeError:
                        raise GateError('invalid_external_ref') from None
                    if any(getattr(conversation_ref, field) != refs[0][field]
                           for field in ('provider', 'tenant_id', 'connection_id')) or not conversation_ref.object_id:
                        raise GateError('connection_mismatch')
                    data['conversation_ref'] = asdict(conversation_ref)
                    data['tracking_status'] = 'tracked'
                else:
                    data['tracking_status'] = 'conversation_ref_missing'
                current = action.data['payload']['message']
                data['current_message'] = current
                for field in ('subject', 'body'):
                    before, after = message.data['message'][field], current[field]
                    if before != after and before[:1900] != after[:1900]:
                        capture_correction(store, before[:1900], after[:1900],
                                           'personal:email', False, action.id + ':' + field)
                # Preparing this activity never writes to the CRM by itself.
                account = store.get('account', current['account_id'])
                if account and data['next_action']:
                    due = data['next_action']['due_at']
                    previous = account.data.get('next_action_at')
                    if not previous or utc(due) < utc(previous):
                        account = store.put('account', account.id,
                                  dict(account.data, next_action_at=due), account.revision)
                activity = {'local_id': current['account_id'], 'entity': 'activity',
                    'external_ref': None, 'before': {},
                    'after': {'id': 'activity-' + action.id, 'type': 'email_sent',
                              'message_ref': refs[0], 'subject': current['subject'], 'sent_at': sent_at},
                    'links': {'account_id': current['account_id'], 'contact_id': current['contact_id']},
                    'provenance': [action.id]}
                data['crm_activity_pending'] = activity
                if account and isinstance(account.data.get('owner_ref'), dict):
                    from .crm import propose_crm
                    try:
                        proposal = propose_crm(store, message.data['campaign_id'], [activity],
                                               ExternalRef(**account.data['owner_ref']))
                        data['crm_activity_proposal_id'] = proposal.id
                    except GateError as error:
                        data['crm_activity_reason'] = error.code
        elif status == 'unknown':
            data.update(status='unknown', delivery_status='unknown', reconciliation_required=True)
        else:
            data.update(status='failed', delivery_status='failed')
        recorded = list(data.get('recorded_action_ids', []))
        if result.action_id not in recorded:
            recorded.append(result.action_id)
        data['recorded_action_ids'] = recorded
        states[result.action_id] = status
        data['recorded_action_states'] = states
        updated = store.put('message', message.id, data, message.revision)
        store.record_event(Event(uuid4().hex, message.id, 'message_result_recorded', now_utc(),
                                 {'action_id': action.id, 'operation': operation, 'status': status}))
    return updated


def reconcile_delivery(store: Store, action_id: str, observations: list[Payload]) -> Record:
    checked = [payload(observation) for observation in observations]
    with store.transaction():
        action = store.get('action', action_id)
        if not action or action.data.get('operation') not in {'email.send', 'email.create_draft'}:
            raise GateError('action_not_found')
        message_id = action.data.get('payload', {}).get('message_id', action.data.get('proposal_id'))
        message = store.get('message', message_id) if isinstance(message_id, str) else None
        if message is None:
            raise GateError('message_action_mismatch')
        if action.data.get('status') == 'succeeded':
            record_delivery(store, ToolResult(action_id, 'succeeded',
                [ExternalRef(**ref) for ref in action.data['external_refs']], action.data['result']), message.id)
            return action
        observed_status = 'drafted' if action.data['operation'] == 'email.create_draft' else 'sent'
        found = [item for item in checked if item.get('action_id') == action_id
                 and item.get('status') == observed_status and item.get('external_refs')]
        if len(found) != 1:
            # Neither absence nor partial lookup proves the provider never sent.
            return action
        item = found[0]
        try:
            refs = [ExternalRef(**ref) for ref in item['external_refs']]
        except (TypeError, KeyError):
            raise GateError('invalid_external_ref') from None
        result_data = {'reconciled': True, 'connection_id': action.data['connection_id']}
        if 'sent_at' in item:
            result_data['sent_at'] = item['sent_at']
        if 'conversation_ref' in item:
            result_data['conversation_ref'] = item['conversation_ref']
        result = ToolResult(action_id, 'succeeded', refs, result_data)
        record_delivery(store, result, message.id)
        return store.get('action', action_id)
