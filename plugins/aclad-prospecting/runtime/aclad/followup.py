"""Incremental, coordinated review. This module never invokes commercial tools."""
from __future__ import annotations
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4
from .models import Event, GateError, Payload, Record, canonical, payload, utc
from .recovery import bootstrap, checkpoint
from .store import Store

LEASE_KEY = 'review-instance'
LEASE_SECONDS = 300
CLASSIFICATIONS = {'interested', 'question', 'not_now', 'no', 'do_not_contact',
                   'auto', 'bounce', 'meeting', 'crm_change', 'needs_review'}


def _hash(data: object) -> str:
    return sha256(canonical(data).encode()).hexdigest()


def _until(now: str) -> str:
    return (utc(now) + timedelta(seconds=LEASE_SECONDS)).isoformat()


def start_review(store: Store, origin: str, now: str, scope_ids: list[str] | None = None) -> Record:
    utc(now)
    if origin not in {'manual', 'scheduled'}:
        raise GateError('invalid_review_origin')
    run_id = 'review-' + uuid4().hex
    with store.transaction():
        # Acquire first: a concurrent entry must never recover this run's work.
        if not store.acquire_lease(LEASE_KEY, run_id, now, LEASE_SECONDS):
            raise GateError('review_in_progress', 'Another review is already processing this instance.')
        if scope_ids is not None and (not isinstance(scope_ids, list) or not scope_ids
                or any(not isinstance(identifier, str) or not identifier for identifier in scope_ids)
                or len(set(scope_ids)) != len(scope_ids)):
            raise GateError('invalid_review_scope')
        if origin == 'scheduled':
            schedule = store.get('schedule', 'review-schedule')
            if schedule:
                if schedule.data.get('status') != 'active' or schedule.data.get('schedule', {}).get('active') is not True:
                    raise GateError('schedule_not_active')
                from .scheduling import _target, _mapping_matches
                target = _target(store, schedule.data.get('target'))
                if (target is None or schedule.data.get('reconciliation_required')
                        or not _mapping_matches(schedule.data.get('native_configuration'),
                                                schedule.data['schedule'], target)
                        or not schedule.data.get('confirmed_at')):
                    raise GateError('schedule_target_reconciliation_required')
                scheduled_scope = schedule.data.get('schedule', {}).get('scope_ids')
                if not isinstance(scheduled_scope, list) or not scheduled_scope:
                    raise GateError('invalid_review_scope')
                if scope_ids is not None and not set(scope_ids).issubset(set(scheduled_scope)):
                    raise GateError('review_scope_exceeds_schedule')
                scope_ids = scope_ids if scope_ids is not None else list(scheduled_scope)
        if scope_ids is not None:
            if any(not store.get('campaign', identifier) for identifier in scope_ids):
                raise GateError('campaign_required')
            scope_ids = sorted(scope_ids)
        bootstrap(store, now)
        return store.put('run', run_id, {'origin': origin, 'status': 'running', 'scope_ids': scope_ids,
            'started_at': now, 'lease_until': _until(now), 'last_report': None}, None)


def _renew(store: Store, run_id: str, now: str) -> Record:
    run = store.get('run', run_id)
    if not run or run.data.get('status') != 'running':
        raise GateError('review_not_running')
    if utc(now) >= utc(run.data['lease_until']):
        raise GateError('review_lease_expired', 'Restart review before processing another page.')
    if not store.acquire_lease(LEASE_KEY, run_id, now, LEASE_SECONDS):
        raise GateError('review_in_progress')
    return run


def _ref(value: object) -> Payload:
    if not isinstance(value, dict) or set(value) != {'provider', 'tenant_id', 'connection_id', 'object_id'}:
        raise GateError('invalid_event_reference')
    if any(not isinstance(v, str) or not v for v in value.values()):
        raise GateError('invalid_event_reference')
    return value


def _in_scope(account: Record | None, scope_ids: list[str] | None) -> bool:
    if scope_ids is None:
        return True
    if account is None:
        return False
    campaigns = set(account.data.get('campaign_ids', []))
    if account.data.get('campaign_id'):
        campaigns.add(account.data['campaign_id'])
    return bool(campaigns.intersection(scope_ids))


def _crm_reference_matches(store: Store, account: Record, conversation: Payload) -> bool:
    synced = account.data.get('crm_external_ref')
    if synced is not None:
        return synced == conversation
    original = account.data.get('external_ref')
    if original != conversation:
        return False
    # Legacy references are accepted only when they are identifiable as CRM data,
    # never because a prospecting reference happens to share an object ID.
    known_crm = original.get('provider') in {'netsuite', 'hubspot', 'pipedrive', 'salesforce', 'close'}
    crm_binding = any(row.data.get('provider') == original.get('provider')
        and row.data.get('capability', {}).get('operation') in {'crm.read', 'crm.write'}
        and row.data.get('capability', {}).get('connection_id') == original.get('connection_id')
        and row.data.get('tenant_id', original.get('tenant_id')) == original.get('tenant_id')
        for row in store.list('connection'))
    return known_crm or crm_binding


def _event(store: Store, raw: Payload, now: str, scope_ids: list[str] | None = None) -> Payload:
    event = payload(raw)
    for key in ('external_ref', 'conversation_ref'):
        _ref(event.get(key))
    external, conversation = event['external_ref'], event['conversation_ref']
    if any(external[k] != conversation[k] for k in ('provider', 'tenant_id', 'connection_id')):
        raise GateError('event_identity_mismatch')
    if utc(event.get('occurred_at')) > utc(now):
        raise GateError('future_event')
    if not isinstance(event.get('source_revision'), (str, int)) or isinstance(event.get('source_revision'), bool):
        raise GateError('event_revision_required')
    if not isinstance(event.get('evidence'), str) or not event['evidence']:
        raise GateError('event_evidence_required')
    classification = event.get('classification')
    if classification not in CLASSIFICATIONS:
        event['classification'] = 'needs_review'
    account = store.get('account', event.get('account_id', ''))
    contact = store.get('contact', event.get('contact_id') or '')
    account_event = event.get('kind') == 'crm' and event['classification'] == 'crm_change'
    if not account or (not account_event and (not contact or contact.data.get('account_id') != account.id)):
        raise GateError('untracked_event')
    if not _in_scope(account, scope_ids):
        raise GateError('event_outside_review_scope')
    # A stored conversation reference is needed, never a name/domain guessed by the model.
    tracked = any(message.data.get('conversation_ref') == conversation
        and message.data.get('message', {}).get('account_id', message.data.get('account_id')) == account.id
        and contact is not None
        and message.data.get('message', {}).get('contact_id', message.data.get('contact_id')) == contact.id
        for message in store.list('message'))
    if event.get('kind') == 'crm' and event['classification'] == 'crm_change':
        tracked = _crm_reference_matches(store, account, conversation)
    if not tracked:
        raise GateError('untracked_conversation')
    if 'resume_at' in event:
        utc(event['resume_at'])
    return event


def _pending(store: Store, key: str, data: Payload) -> Record:
    identifier = 'review-action-' + _hash(key)[:32]
    prior = store.get('action', identifier)
    if prior:
        return prior
    return store.put('action', identifier, {**data, 'status': 'pending',
        'external_execution': False, 'approval_required': True}, None)


def _apply_event(store: Store, event: Payload, identifier: str) -> Payload | None:
    contact = store.get('contact', event.get('contact_id') or '')
    account = store.get('account', event['account_id'])
    classification = event['classification']
    if classification == 'crm_change' and event.get('kind') == 'crm':
        store.put('account', account.id, {**account.data, 'contact_blocked': True,
            'sequence_paused': True, 'pause_reason': 'crm_change'}, account.revision)
        affected = {row.id for row in store.list('contact') if row.data.get('account_id') == account.id}
        for proposal in store.list('proposal'):
            if (proposal.data.get('operation') == 'email.send'
                    and proposal.data.get('status') in {'proposed', 'approved'}
                    and affected.intersection(proposal.data.get('item_ids', []))):
                store.put('proposal', proposal.id, dict(proposal.data, status='invalidated'), proposal.revision)
        action = _pending(store, identifier, {'type': 'review_crm_change',
            'account_id': account.id, 'classification': classification, 'event_id': identifier})
        return {'event_id': identifier, 'account_id': account.id,
                'classification': classification, 'pending_action_id': action.id}
    data = deepcopy(contact.data)
    previous_at = data.get('last_reply_at')
    if classification != 'do_not_contact' and data.get('last_reply_external_ref') == event['external_ref']:
        old_revision, new_revision = str(data.get('last_reply_revision', '')), str(event['source_revision'])
        if old_revision.isdecimal() and new_revision.isdecimal() and int(new_revision) < int(old_revision):
            return None
        if old_revision != new_revision and not (old_revision.isdecimal() and new_revision.isdecimal()):
            # Opaque revisions cannot establish order; preserve prior decision and ask for review.
            _pending(store, identifier + ':revision', {'type': 'review_revision_order',
                'account_id': account.id, 'contact_id': contact.id})
            return {'event_id': identifier, 'account_id': account.id,
                    'contact_id': contact.id, 'classification': 'needs_review'}
    if classification != 'do_not_contact' and (data.get('do_not_contact') or
            previous_at and utc(event['occurred_at']) < utc(previous_at)):
        return None
    if classification == 'not_now' and not event.get('resume_at'):
        classification = 'needs_review'
    data['reply_prior_blocked'] = data.get('reply_prior_blocked', False) or bool(data.get('contact_blocked') and not data.get('reply_pause'))
    data.update({'contact_blocked': True, 'sequence_paused': True, 'reply_pause': True,
                 'reply_classification': classification, 'last_reply_at': event['occurred_at'],
                 'last_reply_event': identifier, 'last_reply_revision': event['source_revision'],
                 'last_reply_external_ref': event['external_ref']})
    if classification == 'do_not_contact':
        data['do_not_contact'] = True
    elif classification == 'bounce':
        data['address_suspended'] = True
    elif classification == 'not_now':
        data['resume_at'] = event['resume_at']
    elif classification == 'no':
        data['outreach_status'] = 'closed'
    store.put('contact', contact.id, data, contact.revision)
    account_data = deepcopy(account.data)
    if classification in {'interested', 'meeting', 'crm_change'}:
        account_data['reply_prior_blocked'] = account_data.get('reply_prior_blocked', False) or bool(account_data.get('contact_blocked') and not account_data.get('reply_pause'))
        account_data.update(contact_blocked=True, sequence_paused=True, reply_pause=True, pause_reason=classification)
    if classification == 'do_not_contact' and event.get('block_scope') == 'account':
        account_data.update(contact_blocked=True, do_not_contact=True, pause_reason='do_not_contact')
    if account_data != account.data:
        store.put('account', account.id, account_data, account.revision)
    # Existing unexecuted send proposals must be reviewed again after any reply.
    for proposal in store.list('proposal'):
        if proposal.data.get('operation') != 'email.send' or proposal.data.get('status') not in {'proposed', 'approved'}:
            continue
        affected = {contact.id}
        if classification in {'interested', 'meeting', 'crm_change'} or account_data.get('do_not_contact'):
            affected.update(row.id for row in store.list('contact') if row.data.get('account_id') == account.id)
        if affected.intersection(proposal.data.get('item_ids', [])):
            store.put('proposal', proposal.id, dict(proposal.data, status='invalidated'), proposal.revision)
    action = _pending(store, identifier, {'type': 'review_reply', 'account_id': account.id,
        'contact_id': contact.id, 'classification': classification, 'event_id': identifier,
        'resume_at': event.get('resume_at')})
    return {'event_id': identifier, 'account_id': account.id, 'contact_id': contact.id,
            'classification': classification, 'pending_action_id': action.id}


def apply_review(store: Store, run_id: str, events: list[Payload], source_pages: list[Payload],
                 source_errors: list[Payload], now: str) -> Payload:
    utc(now)
    if not all(isinstance(items, list) for items in (events, source_pages, source_errors)):
        raise GateError('invalid_review_batch')
    with store.transaction():
        run = _renew(store, run_id, now)
        scope_ids = run.data.get('scope_ids')
        clean = [_event(store, event, now, scope_ids) for event in events]
        pages, errors = [payload(page) for page in source_pages], [payload(error) for error in source_errors]
        for item in pages + errors:
            if any(not isinstance(item.get(key), str) or not item[key] for key in ('connection_id', 'source')):
                raise GateError('invalid_source_page')
        failed = {(item['connection_id'], item['source']) for item in errors}
        findings = []
        for event in sorted(clean, key=lambda item: utc(item['occurred_at'])):
            identifier = 'reply-' + _hash([event['external_ref'], event['source_revision']])
            previous = store.get('decision', identifier)
            if previous:
                if previous.data['event'] != event:
                    raise GateError('event_conflict')
                continue
            store.put('decision', identifier, {'event': event}, None)
            store.record_event(Event(identifier, event.get('contact_id') or event['account_id'], 'reply.observed', event['occurred_at'], event))
            finding = _apply_event(store, event, identifier)
            if finding:
                findings.append(finding)
        for page in pages:
            if type(page.get('complete')) is not bool:
                raise GateError('invalid_source_page')
            if not page['complete'] or (page['connection_id'], page['source']) in failed:
                continue
            # Cursor and all normalized events in this batch commit together.
            key = 'source-' + _hash([page['connection_id'], page['source'], scope_ids])[:32]
            old = store.get('cursor', key)
            store.put('cursor', key, {'connection_id': page['connection_id'], 'source': page['source'],
                'value': page.get('next_cursor'), 'last_success': now, 'scope_ids': scope_ids}, old.revision if old else None)
        for account in store.list('account'):
            if not _in_scope(account, scope_ids):
                continue
            due = account.data.get('next_action_at')
            contacts = [row for row in store.list('contact') if row.data.get('account_id') == account.id and row.data.get('selected')]
            if contacts and not any(not any(row.data.get(key) for key in
                    ('contact_blocked', 'sequence_paused', 'do_not_contact', 'address_suspended')) for row in contacts):
                continue
            if due and utc(due) <= utc(now) and not (account.data.get('contact_blocked') or account.data.get('do_not_contact')):
                action = _pending(store, 'due:' + account.id + ':' + due,
                    {'type': 'prepare_followup', 'account_id': account.id, 'due_at': due})
                findings.append({'account_id': account.id, 'classification': 'followup_due',
                                 'pending_action_id': action.id})
        for contact in store.list('contact'):
            account = store.get('account', contact.data.get('account_id', ''))
            due = contact.data.get('resume_at')
            if (not _in_scope(account, scope_ids) or not contact.data.get('selected')
                    or not due or utc(due) > utc(now) or contact.data.get('do_not_contact')
                    or contact.data.get('address_suspended')):
                continue
            action = _pending(store, 'resume:' + contact.id + ':' + due, {
                'type': 'review_resume', 'account_id': account.id, 'contact_id': contact.id,
                'event_id': contact.data.get('last_reply_event'), 'due_at': due})
            if action.data.get('status') == 'pending':
                findings.append({'account_id': account.id, 'contact_id': contact.id,
                    'classification': 'resume_due', 'pending_action_id': action.id})
        notify = False
        for material in findings + [{'source_error': error} for error in errors]:
            fingerprint = _hash(material)
            if not store.get('notification', fingerprint):
                store.put('notification', fingerprint, {'material': material, 'first_seen': now,
                    'status': 'reported', 'run_id': run_id}, None)
                notify = True
        last_success = {f"{r.data['connection_id']}:{r.data['source']}": r.data['last_success']
                        for r in store.list('cursor') if 'last_success' in r.data
                        and r.data.get('scope_ids') == scope_ids}
        pending = [{'id': action.id, **action.data} for action in store.list('action')
                   if action.data.get('status') == 'pending'
                   and _in_scope(store.get('account', action.data.get('account_id', '')), scope_ids)]
        report = {'origin': run.data['origin'], 'scope_ids': scope_ids, 'checked_at': now,
            'coverage': {'status': 'partial' if errors or any(not p['complete'] for p in pages) else 'complete' if pages else 'not_checked',
                         'pages': pages, 'errors': errors},
            'findings': findings, 'pending_actions': pending, 'notify': notify,
            'last_success_by_source': last_success}
        store.put('run', run.id, {**run.data, 'lease_until': _until(now), 'last_report': report}, run.revision)
        checkpoint(store)
        return report


def finish_review(store: Store, run_id: str, now: str) -> Record:
    with store.transaction():
        run = _renew(store, run_id, now)
        result = store.put('run', run.id, {**run.data, 'status': 'completed', 'finished_at': now}, run.revision)
        store.record_event(Event('finished-' + run.id, run.id, 'review.completed', now,
                                 {'origin': run.data['origin']}))
        store.release_lease(LEASE_KEY, run_id)
        checkpoint(store)
        return result


def _reply_restrictions(contact: Record, account: Record) -> None:
    for row in (contact, account):
        if any(row.data.get(key) for key in ('do_not_contact', 'address_suspended', 'reply_prior_blocked')):
            raise GateError('contact_blocked')
        if row.data.get('contact_blocked') and not row.data.get('reply_pause'):
            raise GateError('contact_blocked')
    if account.data.get('pause_reason') == 'crm_change':
        raise GateError('account_review_required')
    eligibility = account.data.get('eligibility')
    if isinstance(eligibility, dict):
        eligibility = eligibility.get('status')
    if eligibility is not None and eligibility != 'eligible':
        raise GateError('account_review_required')


def resolve_review(store: Store, action_id: str, expected_revision: int,
                   contact_revision: int, account_revision: int, decision: str,
                   evidence_id: str, now: str, resume_account: bool = False) -> Record:
    """Explicit seller decision; never sends or automatically resumes on a date."""
    utc(now)
    if (decision not in {'respond', 'keep_paused', 'resume_sequence', 'close'}
            or not isinstance(evidence_id, str) or not evidence_id or type(resume_account) is not bool):
        raise GateError('invalid_review_resolution')
    with store.transaction():
        action = store.get('action', action_id)
        if not action or action.data.get('type') not in {'review_reply', 'review_resume'}:
            raise GateError('reply_review_required')
        identifier = 'resolution-' + action.id
        prior = store.get('decision', identifier)
        if prior:
            if prior.data.get('decision') == decision and prior.data.get('evidence_id') == evidence_id:
                return prior
            raise GateError('resolution_conflict')
        if action.revision != expected_revision or action.data.get('status') != 'pending':
            raise GateError('revision_conflict')
        contact = store.get('contact', action.data.get('contact_id', ''))
        account = store.get('account', action.data['account_id'])
        if not contact or not account or contact.revision != contact_revision or account.revision != account_revision:
            raise GateError('revision_conflict')
        if contact.data.get('last_reply_event') != action.data.get('event_id'):
            raise GateError('reply_review_stale')
        if decision in {'respond', 'resume_sequence'}:
            _reply_restrictions(contact, account)
            if not contact.data.get('selected') or not account.data.get('selected'):
                raise GateError('selection_required')
        if decision == 'resume_sequence':
            if account.data.get('contact_blocked') and not resume_account:
                raise GateError('account_review_required')
            data = dict(contact.data, contact_blocked=False, sequence_paused=False,
                        reply_pause=False, resume_at=None, resume_reviewed_at=now)
            store.put('contact', contact.id, data, contact.revision)
            if resume_account:
                store.put('account', account.id, dict(account.data, contact_blocked=False,
                    sequence_paused=False, reply_pause=False, pause_reason=None), account.revision)
        elif decision == 'close':
            store.put('contact', contact.id, dict(contact.data, outreach_status='closed',
                sequence_paused=True, contact_blocked=True, resume_at=None), contact.revision)
        resolution = store.put('decision', identifier, {'decision': decision,
            'evidence_id': evidence_id, 'event_id': action.data['event_id'], 'action_id': action.id,
            'account_id': account.id, 'contact_id': contact.id, 'contact_revision': contact_revision,
            'account_revision': account_revision, 'status': 'active' if decision == 'respond' else 'recorded',
            'resume_account': resume_account, 'resolved_at': now}, None)
        for pending in store.list('action'):
            if pending.id == action.id or (decision in {'resume_sequence', 'close'}
                    and pending.data.get('status') == 'pending'
                    and pending.data.get('type') in {'review_reply', 'review_resume'}
                    and pending.data.get('contact_id') == contact.id
                    and pending.data.get('event_id') == action.data['event_id']):
                store.put('action', pending.id, dict(pending.data, status='resolved',
                    resolution_id=resolution.id), pending.revision)
        store.record_event(Event(identifier, contact.id, 'reply.review_resolved', now, resolution.data))
        checkpoint(store)
        return resolution


def reviewed_response(store: Store, message: Payload, message_id: str | None = None) -> Record | None:
    """Validate a one-reply permission against the exact current paused state."""
    identifier = message.get('reviewed_response_id')
    if not identifier:
        return None
    ticket = store.get('decision', identifier)
    if (not ticket or ticket.data.get('decision') != 'respond' or ticket.data.get('status') != 'active'
            or ticket.data.get('account_id') != message.get('account_id')
            or ticket.data.get('contact_id') != message.get('contact_id')):
        raise GateError('reply_review_required')
    contact = store.get('contact', ticket.data['contact_id'])
    account = store.get('account', ticket.data['account_id'])
    if (not contact or not account or contact.revision != ticket.data['contact_revision']
            or account.revision != ticket.data['account_revision']
            or contact.data.get('last_reply_event') != ticket.data['event_id']):
        raise GateError('reply_review_stale')
    _reply_restrictions(contact, account)
    bound = ticket.data.get('bound_message_id')
    if bound and bound != message_id:
        raise GateError('response_already_started')
    return ticket
