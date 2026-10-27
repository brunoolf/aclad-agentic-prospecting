"""Full-message previews bind draft and send to distinct approvals."""
from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from .approvals import create_proposal
from .followup import reviewed_response
from .models import Event, ExternalRef, GateError, Payload, Proposal, now_utc, payload
from .outreach import _campaign, _selected
from .policy import validate_preflight
from .store import Store
from .portfolio import validate_message_portfolio

MESSAGE_FIELDS = {'account_id', 'contact_id', 'sender_ref', 'to', 'cc', 'bcc',
                  'subject', 'body', 'attachments', 'source_ids', 'plan_step_id'}


def _message(message: Payload) -> Payload:
    clean = payload(message)
    if not MESSAGE_FIELDS.issubset(clean) or set(clean) - MESSAGE_FIELDS - {'external_revision', 'reviewed_response_id', 'learning_context', 'offering_ids', 'portfolio_digest'}:
        raise GateError('invalid_message')
    if any(not isinstance(clean[key], str) or not clean[key].strip()
           for key in ('account_id', 'contact_id', 'subject', 'body', 'plan_step_id')):
        raise GateError('invalid_message')
    for key in ('to', 'cc', 'bcc'):
        if not isinstance(clean[key], list) or any(not isinstance(v, str) or not v.strip() for v in clean[key]):
            raise GateError('invalid_recipients')
    if not clean['to']:
        raise GateError('invalid_recipients')
    if clean['attachments'] != []:
        raise GateError('attachments_unverified')
    if not isinstance(clean['source_ids'], list) or any(not isinstance(x, str) for x in clean['source_ids']):
        raise GateError('invalid_message')
    ref = clean['sender_ref']
    if not isinstance(ref, dict) or set(ref) != {'provider', 'tenant_id', 'connection_id', 'object_id'} or any(not isinstance(v, str) or not v for v in ref.values()):
        raise GateError('sender_mismatch')
    return clean


def _check_context(store: Store, campaign_id: str, message: Payload, operation: str, message_id: str | None = None) -> None:
    _campaign(store, campaign_id)
    validate_message_portfolio(store, campaign_id, message)
    ticket = reviewed_response(store, message, message_id)
    account = _selected(store, 'account', message['account_id'], campaign_id, ticket is not None)
    contact = _selected(store, 'contact', message['contact_id'], campaign_id, ticket is not None)
    if contact.data.get('account_id') != account.id:
        raise GateError('contact_account_mismatch')
    if account.data.get('crm_status') != 'confirmed' or contact.data.get('crm_status') != 'confirmed':
        raise GateError('crm_unconfirmed')
    sender = message['sender_ref']
    bindings = [row for row in store.list('connection')
                if row.data.get('capability', {}).get('connection_id') == sender['connection_id']
                and row.data.get('capability', {}).get('operation') == operation]
    if len(bindings) != 1:
        raise GateError('channel_unavailable')
    binding = bindings[0]
    capability = binding.data['capability']
    if (capability.get('visibility') != 'visible' or capability.get('auth') != 'authenticated'
            or capability.get('permission') != 'allowed' or capability.get('verification') != 'verified'):
        raise GateError('channel_unavailable')
    if binding.data.get('account_identity') != sender['object_id']:
        raise GateError('sender_mismatch')
    if not any(plan.data.get('campaign_id') == campaign_id
               and any(step.get('id') == message['plan_step_id']
                       and step.get('contact_id') == contact.id and step.get('channel') == 'email'
                       for step in plan.data.get('steps', []))
               for plan in store.list('outreach_plan')):
        raise GateError('plan_step_required')
    if 'learning_context' in message:
        from .outcome_learning import validate_learning_context
        matching = [step for plan in store.list('outreach_plan')
                    if plan.data.get('campaign_id') == campaign_id
                    for step in plan.data.get('steps', []) if step.get('id') == message['plan_step_id']
                    and step.get('contact_id') == contact.id]
        if len(matching) != 1 or message['learning_context'] != matching[0].get('learning_context'):
            raise GateError('learning_context_mismatch')
        validate_learning_context(store, message['learning_context'], account_id=account.id,
                                  contact_id=contact.id, plan_step=matching[0])


def _reply_reference(store: Store, message: Payload) -> Payload:
    ticket = reviewed_response(store, message)
    if not ticket:
        return {}
    observed = store.get('decision', ticket.data['event_id'])
    conversation = observed.data.get('event', {}).get('conversation_ref') if observed else None
    if not isinstance(conversation, dict):
        raise GateError('untracked_conversation')
    return {'reply_to_conversation_ref': conversation, 'reviewed_reply_event_id': ticket.data['event_id']}


def propose_draft(store: Store, campaign_id: str, message: Payload) -> Proposal:
    clean = _message(message)
    with store.transaction():
        _check_context(store, campaign_id, clean, 'email.create_draft')
        from .outcome_learning import freeze_learning_basis
        proposal = create_proposal(store, 'email.create_draft', clean['sender_ref']['connection_id'],
            [clean['contact_id']], {'campaign_id': campaign_id, 'message': clean,
                                    'external_revision': 'new',
                                    'portfolio': validate_message_portfolio(store, campaign_id, clean),
                                    'learning_basis': freeze_learning_basis(store, campaign_id, clean),
                                    **_reply_reference(store, clean)})
        store.put('message', proposal.id, {'campaign_id': campaign_id, 'message': clean,
                  'draft_proposal_id': proposal.id, 'status': 'proposed'}, None)
        ticket = reviewed_response(store, clean)
        if ticket:
            store.put('decision', ticket.id, dict(ticket.data, bound_message_id=proposal.id), ticket.revision)
        store.record_event(Event(uuid4().hex, proposal.id, 'draft_proposed', now_utc(),
                                 {'campaign_id': campaign_id, 'contact_id': clean['contact_id']}))
    return proposal


def propose_send(store: Store, draft_ref: ExternalRef, current_draft: Payload,
                 preflight: Payload) -> Proposal:
    clean = _message(current_draft)
    checked = payload(preflight)
    with store.transaction():
        records = [row for row in store.list('message') if row.data.get('draft_ref') == asdict(draft_ref)]
        if len(records) != 1:
            raise GateError('draft_not_found')
        record = records[0]
        if record.data.get('status') in {'sent', 'unknown'}:
            raise GateError('reconciliation_required')
        if any(action.data.get('operation') == 'email.send'
               and action.data.get('payload', {}).get('message_id') == record.id
               and action.data.get('status') in {'in_flight', 'unknown', 'succeeded'}
               for action in store.list('action')):
            raise GateError('reconciliation_required')
        campaign_id = record.data['campaign_id']
        if (clean['account_id'] != record.data['message']['account_id']
                or clean['contact_id'] != record.data['message']['contact_id']
                or draft_ref.connection_id != clean['sender_ref']['connection_id']):
            raise GateError('scope_mismatch')
        _check_context(store, campaign_id, clean, 'email.send', record.id)
        ticket = reviewed_response(store, clean, record.id)
        if (checked.get('sender_connection_id') != clean['sender_ref']['connection_id']
                or checked.get('sender_object_id') != clean['sender_ref']['object_id']):
            raise GateError('sender_mismatch')
        if checked.get('crm_confirmed') is not True:
            raise GateError('crm_unconfirmed')
        if (not ticket and checked.get('recent_replies') is not False) or checked.get('contact_allowed') is not True:
            raise GateError('contact_blocked')
        revision = clean.get('external_revision')
        if not isinstance(revision, str) or not revision:
            raise GateError('external_revision_required')
        from .outcome_learning import freeze_learning_basis
        content = {'campaign_id': campaign_id, 'message_id': record.id,
                   'message': clean, 'draft_ref': asdict(draft_ref), 'external_revision': revision,
                   'portfolio': validate_message_portfolio(store, campaign_id, clean),
                   'learning_basis': freeze_learning_basis(store, campaign_id, clean)}
        # Validate the same fresh state that prepare_action will validate again.
        validate_preflight('email.send', draft_ref.connection_id, content, checked,
                           checked.get('checked_at', ''), ticket.data['event_id'] if ticket else None)
        for previous in store.list('proposal'):
            if (previous.data.get('operation') == 'email.send'
                    and previous.data.get('payload', {}).get('message_id') == record.id
                    and previous.data.get('status') in {'proposed', 'approved'}):
                store.put('proposal', previous.id, dict(previous.data, status='invalidated'), previous.revision)
        proposal = create_proposal(store, 'email.send', draft_ref.connection_id,
                                   [clean['contact_id']], content)
        store.put('message', record.id, dict(record.data, current_message=clean,
                  send_proposal_id=proposal.id), record.revision)
        store.record_event(Event(uuid4().hex, record.id, 'send_proposed', now_utc(),
                                 {'proposal_id': proposal.id, 'external_revision': revision}))
    return proposal
