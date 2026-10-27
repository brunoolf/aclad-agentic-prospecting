from copy import deepcopy
from dataclasses import asdict

from aclad.models import Capability, Event, GateError
from aclad.prospecting import open_campaign, record_candidates
from tests.support import StateTest, NOW


def ref(identifier, provider='calendar', connection='calendar'):
    return dict(provider=provider, tenant_id='tenant', connection_id=connection, object_id=identifier)


def seed_meeting(store, status='confirmed', revision='1', meeting_id='meeting'):
    if not store.get('campaign', 'campaign'):
        open_campaign(store, 'campaign', 'Objective')
        store.put('account', 'account', {'campaign_id': 'campaign', 'selected': True}, None)
        store.put('contact', 'contact', {'account_id': 'account', 'campaign_id': 'campaign',
            'external_ref': ref('contact', 'apollo', 'prospect')}, None)
        store.put('message', 'sent', {'campaign_id': 'campaign', 'status': 'sent',
            'delivery_status': 'sent', 'sent_ref': ref('sent', 'mail', 'mail'),
            'conversation_ref': ref('thread', 'mail', 'mail'),
            'send_action_id': 'sent-action',
            'message': {'account_id': 'account', 'contact_id': 'contact'}}, None)
        store.put('action', 'sent-action', {'operation': 'email.send', 'status': 'succeeded',
            'connection_id': 'mail', 'external_refs': [ref('sent', 'mail', 'mail')],
            'payload': {'message_id': 'sent', 'message': {'account_id': 'account', 'contact_id': 'contact'}}}, None)
        cap = Capability('calendar.read', 'calendar.find', 'calendar', 'visible', 'authenticated', 'allowed', 'verified', 'free')
        store.put('connection', 'calendar', {'provider': 'calendar', 'account_identity': 'seller',
            'capability': asdict(cap)}, None)
    item = dict(ref=ref(meeting_id), source_revision=revision, status=status,
        starts_at='2026-11-01T12:00:00Z', ends_at='2026-11-01T13:00:00Z',
        participant_refs=[ref('contact', 'apollo', 'prospect')])
    evidence = 'calendar-result-' + meeting_id + '-' + revision
    store.put('action', evidence, {'status': 'succeeded', 'operation': 'calendar.read',
        'connection_id': 'calendar', 'external_refs': [ref('calendar-page')],
        'result': {'complete': True, 'items': [item]}}, None)
    observation = {key: value for key, value in item.items() if key != 'participant_refs'}
    observation.update(account_id='account', contact_ids=['contact'])
    return evidence, observation


class MeetingTests(StateTest):
    def test_requires_matching_saved_calendar_result(self):
        from aclad.meetings import record_meetings
        with self.assertRaises(GateError):
            record_meetings(self.store, 'unproven', 'email-unproven', [])
        evidence, observation = seed_meeting(self.store)
        action = self.store.get('action', evidence)
        cases = [dict(action.data, operation='email.read'),
                 dict(action.data, result={'complete': False, 'items': action.data['result']['items']}),
                 dict(action.data, result={'complete': True, 'items': []}),
                 dict(action.data, external_refs=[{**ref('page'), 'tenant_id': 'other'}])]
        for index, data in enumerate(cases):
            key = 'bad-' + str(index)
            self.store.put('action', key, data, None)
            with self.subTest(index=index), self.assertRaises(GateError):
                record_meetings(self.store, 'campaign', key, [observation])
        for changes in ({'account_id': 'other'}, {'contact_ids': []},
                        {'ref': {**observation['ref'], 'connection_id': 'other'}},
                        {'source_revision': 'not-returned'}, {'status': 'draft'}):
            with self.subTest(changes=changes), self.assertRaises(GateError):
                record_meetings(self.store, 'campaign', evidence, [{**observation, **changes}])
        self.assertEqual(self.store.list('meeting'), [])

    def test_repeat_reschedule_cancel_preserve_booking(self):
        from aclad.meetings import record_meetings
        evidence, observation = seed_meeting(self.store)
        first = record_meetings(self.store, 'campaign', evidence, [observation])[0]
        self.assertEqual(record_meetings(self.store, 'campaign', evidence, [observation])[0], first)
        for revision, status in [('2', 'confirmed'), ('3', 'cancelled')]:
            evidence, observation = seed_meeting(self.store, status, revision)
            item = self.store.get('action', evidence)
            if revision == '2':
                observation['starts_at'] = '2026-11-02T12:00:00Z'
                observation['ends_at'] = '2026-11-02T13:00:00Z'
                changed = deepcopy(item.data)
                changed['result']['items'][0]['starts_at'] = observation['starts_at']
                changed['result']['items'][0]['ends_at'] = observation['ends_at']
                self.store.put('action', evidence, changed, item.revision)
            record_meetings(self.store, 'campaign', evidence, [observation])
        meetings = self.store.list('meeting')
        self.assertEqual(len(meetings), 1)
        self.assertTrue(meetings[0].data['ever_confirmed'])
        self.assertEqual(meetings[0].data['status'], 'cancelled')
        evidence, observation = seed_meeting(self.store, 'cancelled', '1', 'cancelled-only')
        cancelled = record_meetings(self.store, 'campaign', evidence, [observation])[0]
        self.assertFalse(cancelled.data['ever_confirmed'])

    def test_old_or_conflicting_revision_cannot_regress_meeting(self):
        from aclad.meetings import record_meetings
        for revision, status in [('2', 'confirmed'), ('3', 'cancelled')]:
            evidence, observation = seed_meeting(self.store, status, revision)
            record_meetings(self.store, 'campaign', evidence, [observation])
        evidence, observation = seed_meeting(self.store, 'confirmed', '1')
        with self.assertRaises(GateError):
            record_meetings(self.store, 'campaign', evidence, [observation])
        self.assertEqual(self.store.list('meeting')[0].data['status'], 'cancelled')

    def test_event_history_and_candidate_ids(self):
        open_campaign(self.store, 'campaign', 'Objective')
        candidate = {'id': 'account', 'external_ref': ref('account', 'apollo', 'prospect'), 'source_at': NOW}
        self.store.put('action', 'search', {'status': 'succeeded', 'operation': 'accounts.search',
            'connection_id': 'prospect', 'result': {'candidates': [candidate]}}, None)
        record_candidates(self.store, 'campaign', 'account', [candidate], 'search')
        events = self.store.events_since()
        self.assertEqual([e['sequence'] for e in events], sorted(e['sequence'] for e in events))
        self.assertEqual(events[-1]['data']['item_ids'], ['account'])
        self.assertEqual(self.store.events_since(events[-1]['sequence']), [])

    def test_forged_sent_flag_is_not_tracked_delivery(self):
        from aclad.meetings import record_meetings
        evidence, observation = seed_meeting(self.store)
        message = self.store.get('message', 'sent')
        self.store.put('message', message.id, dict(message.data, send_action_id='unproven'), message.revision)
        with self.assertRaises(GateError):
            record_meetings(self.store, 'campaign', evidence, [observation])

    def test_same_booking_can_link_two_campaigns_without_duplicate_record(self):
        from aclad.meetings import record_meetings
        evidence, observation = seed_meeting(self.store)
        record_meetings(self.store, 'campaign', evidence, [observation])
        open_campaign(self.store, 'other', 'Other')
        account = self.store.get('account', 'account')
        self.store.put('account', account.id, dict(account.data, campaign_ids=['campaign', 'other']), account.revision)
        message = self.store.get('message', 'sent')
        self.store.put('message', 'sent-other', dict(message.data, campaign_id='other', send_action_id='send-other'), None)
        action = self.store.get('action', 'sent-action')
        self.store.put('action', 'send-other', dict(action.data, payload={
            'message_id': 'sent-other', 'message': message.data['message']}), None)
        meeting = record_meetings(self.store, 'other', evidence, [observation])[0]
        self.assertEqual(meeting.data['campaign_ids'], ['campaign', 'other'])
        self.assertEqual(len(self.store.list('meeting')), 1)
