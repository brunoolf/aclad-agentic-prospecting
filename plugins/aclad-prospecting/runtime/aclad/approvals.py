"""Persist reviewed proposals before emitting any native-tool intent.

This bridge guards its own intents. It does not claim to intercept arbitrary
native calls made by an assistant outside the bridge.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4

from .models import (Approval, Capability, Event, GateError, Payload, Proposal,
                     Record, ToolIntent, ToolResult, canonical, now_utc, payload as validate_payload, utc)
from .policy import operation_policy, validate_capability, validate_cost, validate_preflight
from .store import Store


def proposal_digest(operation: str, connection_id: str, item_ids: list[str],
                    content: Payload) -> str:
    return sha256(canonical({'operation': operation, 'connection_id': connection_id,
                             'item_ids': item_ids, 'payload': content}).encode()).hexdigest()


def _proposal(record: Record | None) -> Proposal:
    if record is None:
        raise GateError('proposal_not_found')
    try:
        data = record.data
        proposal = Proposal(record.id, data['revision'], data['operation'],
                            data['connection_id'], data['item_ids'], data['payload'],
                            data['digest'], data['status'])
        actual = proposal_digest(proposal.operation, proposal.connection_id,
                                 proposal.item_ids, proposal.payload)
    except (KeyError, TypeError):
        raise GateError('invalid_proposal') from None
    if actual != proposal.digest:
        raise GateError('proposal_changed')
    return proposal


def _event(store: Store, record_id: str, kind: str, data: Payload, at: str | None = None) -> None:
    store.record_event(Event(uuid4().hex, record_id, kind, at or now_utc(), data))


def _validate_operation_scope(operation: str, content: Payload) -> None:
    if operation != 'calendar.read':
        return
    ids = content.get('account_ids', [])
    if (not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids)
            or len(set(ids)) != len(ids) or 'campaign_id' in content and (
                not isinstance(content['campaign_id'], str) or not content['campaign_id'])):
        raise GateError('invalid_calendar_scope')


def create_proposal(store: Store, operation: str, connection_id: str,
                    item_ids: list[str], payload: Payload) -> Proposal:
    operation_policy(operation)
    content = validate_payload(payload)
    _validate_operation_scope(operation, content)
    if (not isinstance(connection_id, str) or not connection_id.strip()
            or not isinstance(item_ids, list) or not item_ids
            or any(not isinstance(item, str) or not item for item in item_ids)
            or len(set(item_ids)) != len(item_ids)):
        raise GateError('invalid_proposal')
    if 'item_ids' in content and content['item_ids'] != item_ids:
        raise GateError('scope_mismatch')
    proposal = Proposal(uuid4().hex, 1, operation, connection_id, list(item_ids), content,
                        proposal_digest(operation, connection_id, item_ids, content), 'proposed')
    with store.transaction():
        bindings = [row for row in store.list('connection')
                    if row.data.get('capability', {}).get('connection_id') == connection_id
                    and row.data.get('capability', {}).get('operation') == operation]
        identity = bindings[0].data.get('account_identity') if len(bindings) == 1 else None
        store.put('proposal', proposal.id, dict(asdict(proposal), connection_identity=identity), None)
        _event(store, proposal.id, 'proposal_created', {'digest': proposal.digest,
                                                       'revision': proposal.revision})
    return proposal


def approve(store: Store, proposal_id: str, revision: int, digest: str,
            approved_by: str, approved_at: str) -> Approval:
    utc(approved_at)
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise GateError('approver_required')
    with store.transaction():
        record = store.get('proposal', proposal_id)
        proposal = _proposal(record)
        if proposal.revision != revision or proposal.digest != digest:
            raise GateError('approval_mismatch')
        if proposal.status not in {'proposed', 'approved'}:
            raise GateError('proposal_not_approvable')
        approval = Approval(proposal_id, revision, digest, approved_by, approved_at)
        if record.data.get('approval') == asdict(approval):
            return approval
        store.put('proposal', proposal_id,
                  dict(record.data, approval=asdict(approval), status='approved'), record.revision)
        _event(store, proposal_id, 'proposal_approved', asdict(approval), approved_at)
    return approval


def _validate_selection(store: Store, proposal: Proposal) -> Record | None:
    from .followup import reviewed_response
    ticket = reviewed_response(store, proposal.payload.get('message', {}),
        proposal.payload.get('message_id', proposal.id)) if proposal.operation in {'email.create_draft', 'email.send'} else None
    selection = operation_policy(proposal.operation)['selection']
    if selection is None:
        return
    kinds = ['account', 'contact'] if selection == 'either' else [selection]
    campaign = proposal.payload.get('campaign_id')
    for item_id in proposal.item_ids:
        selected = False
        for kind in kinds:
            record = store.get(kind, item_id)
            if record is None or record.data.get('selected') is not True:
                continue
            if campaign is not None and campaign != record.data.get('campaign_id') and campaign not in record.data.get('campaign_ids', []):
                continue
            if record.data.get('do_not_contact') is True or record.data.get('address_suspended') is True or (record.data.get('contact_blocked') is True and not ticket):
                raise GateError('contact_blocked')
            if kind == 'contact':
                parent = store.get('account', record.data.get('account_id', ''))
                if not parent or parent.data.get('selected') is not True:
                    raise GateError('selection_required')
                if campaign is not None and campaign != parent.data.get('campaign_id') and campaign not in parent.data.get('campaign_ids', []):
                    raise GateError('selection_required')
                if parent.data.get('do_not_contact') or (parent.data.get('contact_blocked') and not ticket):
                    raise GateError('contact_blocked')
            if kind == 'contact' and proposal.operation == 'email.send':
                if not ticket and any(parent.data.get(key) is True or record.data.get(key) is True
                       for key in ('contact_blocked', 'do_not_contact', 'sequence_paused', 'address_suspended')):
                    raise GateError('contact_blocked')
            selected = True
        if not selected:
            raise GateError('selection_required')
    return ticket


def prepare_action(store: Store, proposal_id: str, capability: Capability,
                   preflight: Payload, now: str) -> ToolIntent:
    from .results import ensure_results_current
    ensure_results_current(store)
    utc(now)
    checked = validate_payload(preflight)
    # BEGIN IMMEDIATE serializes the check/create pair across manual/scheduled
    # callers. No intent escapes unless the outer transaction commits.
    with store.transaction():
        record = store.get('proposal', proposal_id)
        proposal = _proposal(record)
        policy = operation_policy(proposal.operation)
        _validate_operation_scope(proposal.operation, proposal.payload)
        if proposal.status not in {'proposed', 'approved'}:
            raise GateError('proposal_not_executable')
        action_id = 'action-' + sha256(proposal_id.encode()).hexdigest()
        previous = store.get('action', action_id)
        if previous:
            code = 'reconciliation_required' if previous.data['status'] == 'unknown' else 'action_already_started'
            raise GateError(code)
        validate_capability(proposal.operation, proposal.connection_id, capability)
        bindings = [row for row in store.list('connection')
                    if row.data.get('capability', {}).get('connection_id') == proposal.connection_id
                    and row.data.get('capability', {}).get('operation') == proposal.operation]
        if len(bindings) != 1 or bindings[0].data.get('capability') != asdict(capability):
            raise GateError('capability_unverified')
        identity = bindings[0].data.get('account_identity')
        if not isinstance(identity, str) or not identity:
            raise GateError('capability_unverified')
        if record.data.get('connection_identity') not in (None, identity):
            raise GateError('connection_mismatch')
        needs_approval = policy['approval'] or capability.cost != 'free'
        environment = store.get('profile', 'environment')
        if environment and (environment.data.get('can_external_actions') is not True
                or capability.cost != 'free' and environment.data.get('can_paid_actions') is not True):
            raise GateError('environment_unavailable')
        if needs_approval:
            approval = record.data.get('approval')
            if (proposal.status != 'approved' or not isinstance(approval, dict)
                    or approval.get('proposal_id') != proposal.id
                    or approval.get('revision') != proposal.revision
                    or approval.get('digest') != proposal.digest):
                raise GateError('approval_required')
        if proposal.operation in {'email.create_draft', 'email.send'} and proposal.payload.get('campaign_id'):
            from .portfolio import validate_message_portfolio
            portfolio = validate_message_portfolio(store, proposal.payload['campaign_id'],
                                                    proposal.payload.get('message', {}))
            if proposal.payload.get('portfolio') is not None and proposal.payload['portfolio'] != portfolio:
                raise GateError('portfolio_context_changed')
        ticket = _validate_selection(store, proposal)
        validate_cost(capability, proposal.payload, len(proposal.item_ids))
        validate_preflight(proposal.operation, proposal.connection_id, proposal.payload, checked, now,
                           ticket.data['event_id'] if ticket else None)
        if proposal.operation == 'crm.write' and any(
                existing.data.get('operation') == 'crm.write'
                and existing.data.get('connection_id') == proposal.connection_id
                and existing.data.get('status') in {'in_flight', 'unknown'}
                and set(proposal.item_ids).intersection(existing.data.get('payload', {}).get('item_ids', []))
                for existing in store.list('action')):
            raise GateError('reconciliation_required')
        if proposal.operation == 'email.send':
            target = proposal.payload.get('draft_ref')
            if not isinstance(target, dict):
                raise GateError('draft_reference_required')
            if any(existing.data.get('operation') == 'email.send'
                   and existing.data.get('connection_id') == proposal.connection_id
                   and existing.data.get('payload', {}).get('draft_ref') == target
                   and existing.data.get('status') in {'in_flight', 'unknown', 'succeeded'}
                   for existing in store.list('action')):
                raise GateError('reconciliation_required')
        intent_payload = dict(proposal.payload, item_ids=list(proposal.item_ids))
        intent = ToolIntent(action_id, proposal.operation, capability.tool_name,
                            proposal.connection_id, intent_payload, proposal.digest)
        lease_owner = uuid4().hex
        if not store.acquire_lease('action:' + action_id, lease_owner, now, 300):
            raise GateError('action_already_started')
        store.put('action', action_id, {
            'lease_owner': lease_owner,
            **asdict(intent), 'proposal_id': proposal.id, 'proposal_revision': proposal.revision,
            'status': 'in_flight', 'prepared_at': now, 'preflight': checked,
            'approval': record.data.get('approval'), 'external_refs': [],
        }, None)
        if ticket and proposal.operation == 'email.send':
            store.put('decision', ticket.id, dict(ticket.data, status='used', send_action_id=action_id), ticket.revision)
        _event(store, action_id, 'action_in_flight', {'proposal_id': proposal.id,
                                                    'digest': proposal.digest}, now)
    return intent


def _validate_style_receipt(store: Store, action: Record, data: Payload, status: str) -> None:
    """A marked style read may persist only a receipt of its canonical summary."""
    content = action.data.get('payload', {})
    if action.data.get('operation') != 'email.read' or 'style_request_id' not in content:
        return
    allowed = {'complete', 'sample_count', 'excluded_count', 'reconciled', 'definitive_no_effect'}
    if set(data) - allowed or any(type(data[key]) is not bool
            for key in ('complete', 'reconciled', 'definitive_no_effect') if key in data):
        raise GateError('style_result_privacy_required', 'Record the style summary first; persist only its numeric receipt, never raw mail.')
    for key in ('sample_count', 'excluded_count'):
        if key in data and (type(data[key]) is not int or not 0 <= data[key] <= 10):
            raise GateError('style_result_privacy_required')
    if status == 'succeeded' and ('complete' not in data or 'sample_count' not in data):
        raise GateError('style_result_privacy_required')
    if not {'sample_count', 'excluded_count'}.intersection(data):
        return  # A failed/uncertain read can have no sample to summarize.
    request_id = content.get('style_request_id')
    request = store.get('analysis', request_id) if isinstance(request_id, str) else None
    sample = store.get('analysis', request.data.get('sample_id', '')) if request else None
    if (not request or request.data.get('type') != 'style_sample_request'
            or request.data.get('status') != 'consumed'
            or request.data.get('connection_id') != action.data.get('connection_id')
            or not sample or sample.data.get('type') != 'style_sample'
            or sample.data.get('request_id') != request_id
            or any(data[key] != sample.data.get(key) for key in ('sample_count', 'excluded_count') if key in data)):
        raise GateError('style_sample_receipt_required', 'Use the counts returned by style-sample-record for this request.')


def record_result(store: Store, result: ToolResult) -> Record:
    result_data = validate_payload(result.data)
    if result.status not in {'succeeded', 'failed', 'unknown'}:
        raise GateError('invalid_result_status')
    with store.transaction():
        action = store.get('action', result.action_id)
        if action is None:
            raise GateError('action_not_found')
        _validate_style_receipt(store, action, result_data, result.status)
        connection = action.data['connection_id']
        refs = [asdict(ref) for ref in result.external_refs]
        for ref in refs:
            if ref['connection_id'] != connection:
                raise GateError('connection_mismatch')
            if any(not isinstance(value, str) or not value for value in ref.values()):
                raise GateError('invalid_external_ref')
        if 'connection_id' in result_data and result_data['connection_id'] != connection:
            raise GateError('connection_mismatch')
        status = result.status
        external_effect = operation_policy(action.data['operation'])['approval']
        if external_effect and status == 'succeeded' and not refs:
            status = 'unknown'
        if external_effect and status == 'failed' and result_data.get('definitive_no_effect') is not True:
            status = 'unknown'
        stored = {'status': status, 'external_refs': refs, 'result': result_data}
        if all(action.data.get(k) == v for k, v in stored.items()):
            return action
        if action.data['status'] in {'succeeded', 'failed', 'cancelled'}:
            raise GateError('result_conflict')
        if action.data['status'] == 'unknown' and status != 'unknown' and result_data.get('reconciled') is not True:
            raise GateError('reconciliation_required')
        updated = store.put('action', action.id, dict(action.data, **stored), action.revision)
        _event(store, action.id, 'action_result', stored)
        if action.data.get('lease_owner'):
            store.release_lease('action:' + action.id, action.data['lease_owner'])
    return updated
