"""Offline saved connector results; no host or network calls."""
from dataclasses import asdict

from aclad.accounts import select_accounts
from aclad.delivery import record_delivery
from aclad.followup import apply_review, finish_review, start_review
from aclad.meetings import record_meetings
from aclad.models import Capability, ExternalRef, ToolResult
from aclad.prospecting import open_campaign, record_candidates
from tests.support import NOW


def result_ref(identifier, provider='mail', connection='mail'):
    return dict(provider=provider, tenant_id='tenant', connection_id=connection, object_id=identifier)


def seed_results(store):
    open_campaign(store, 'campaign', 'Private objective')
    candidates = [{'id': f'a{i}', 'name': f'Company {i}', 'source_at': NOW,
                   'external_ref': result_ref(f'a{i}', 'apollo', 'prospect')} for i in range(100)]
    store.put('action', 'search', {'operation': 'accounts.search', 'connection_id': 'prospect',
        'status': 'succeeded', 'result': {'candidates': candidates, 'complete': True}}, None)
    record_candidates(store, 'campaign', 'account', candidates, 'search')
    for i in range(30):
        account = store.get('account', f'a{i}')
        store.put('account', account.id, dict(account.data, eligibility='eligible'), account.revision)
    select_accounts(store, 'campaign', [f'a{i}' for i in range(30)])
    for i in range(10):
        store.put('contact', f'c{i}', {'account_id': f'a{i}', 'campaign_id': 'campaign',
            'selected': True, 'external_ref': result_ref(f'c{i}', 'apollo', 'prospect')}, None)
        for touch in range(2):
            identifier = f'sent-{i}-{touch}'
            content = {'account_id': f'a{i}', 'contact_id': f'c{i}', 'subject': 'Private subject',
                       'body': 'Private body', 'plan_step_id': f'step{touch}'}
            store.put('message', identifier, {'campaign_id': 'campaign', 'status': 'drafted', 'message': content}, None)
            store.put('action', identifier, {'status': 'in_flight', 'operation': 'email.send',
                'connection_id': 'mail', 'payload': {'message_id': identifier, 'message': content}}, None)
            record_delivery(store, ToolResult(identifier, 'succeeded', [ExternalRef(**result_ref(identifier))],
                {'sent_at': NOW, 'conversation_ref': result_ref(f'thread-{i}')}), identifier)
    events = []
    for index, account in enumerate([0, 0, 1, 2]):
        events.append({'external_ref': result_ref(f'reply{index}'),
            'conversation_ref': result_ref(f'thread-{account}'), 'account_id': f'a{account}',
            'contact_id': f'c{account}', 'kind': 'email', 'occurred_at': NOW,
            'source_revision': '1', 'classification': 'question', 'evidence': 'Saved reply'})
    run = start_review(store, 'manual', NOW)
    apply_review(store, run.id, events, [{'connection_id': 'mail', 'source': 'email',
        'next_cursor': 'complete', 'complete': True}], [], NOW)
    finish_review(store, run.id, NOW)
    cap = Capability('calendar.read', 'calendar.find', 'calendar', 'visible', 'authenticated', 'allowed', 'verified', 'free')
    store.put('connection', 'calendar', {'provider': 'calendar', 'account_identity': 'seller', 'capability': asdict(cap)}, None)
    items = [{'ref': result_ref(f'meeting{i}', 'calendar', 'calendar'), 'source_revision': '1',
        'status': 'confirmed', 'starts_at': '2026-11-01T12:00:00Z', 'ends_at': '2026-11-01T13:00:00Z',
        'participant_refs': [result_ref(f'c{i}', 'apollo', 'prospect')]} for i in range(2)]
    store.put('action', 'calendar-read', {'status': 'succeeded', 'operation': 'calendar.read', 'prepared_at': NOW,
        'connection_id': 'calendar', 'external_refs': [result_ref('page', 'calendar', 'calendar')],
        'payload': {'campaign_id': 'campaign', 'account_ids': [f'a{i}' for i in range(10)]},
        'result': {'items': items, 'complete': True}}, None)
    record_meetings(store, 'campaign', 'calendar-read', [{**{k:v for k,v in item.items() if k != 'participant_refs'},
        'account_id': f'a{i}', 'contact_ids': [f'c{i}']} for i,item in enumerate(items)])
