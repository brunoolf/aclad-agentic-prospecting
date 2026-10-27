import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from aclad.approvals import approve, prepare_action
from aclad.delivery import record_delivery, reconcile_delivery
from aclad.messages import propose_draft, propose_send
from aclad.models import Capability, ExternalRef, GateError, Scope, ToolResult
from aclad.store import Store

NOW = '2026-10-22T12:00:00Z'


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name), Scope('p', 's', 'i'))
        self.store.put('campaign', 'c1', {}, None)
        self.store.put('account', 'a1', {'selected': True, 'campaign_id': 'c1', 'crm_status': 'confirmed'}, None)
        self.store.put('contact', 'x1', {'selected': True, 'campaign_id': 'c1', 'account_id': 'a1', 'crm_status': 'confirmed'}, None)
        self.sender = ExternalRef('mail', 'tenant', 'mail1', 'seller@example.com')
        self.cap = Capability('email.send', 'email.send', 'mail1', 'visible', 'authenticated', 'allowed', 'verified', 'free')
        for operation in ('email.send', 'email.create_draft'):
            self.store.put('connection', operation, {'account_identity': self.sender.object_id,
                'capability': asdict(Capability(operation, operation, 'mail1', 'visible', 'authenticated', 'allowed', 'verified', 'free'))}, None)
        self.store.put('outreach_plan', 'plan1', {'campaign_id': 'c1', 'steps': [
            {'id': 'step1', 'contact_id': 'x1', 'channel': 'email', 'delay_days': 0},
            {'id': 'step2', 'contact_id': 'x1', 'channel': 'email', 'delay_days': 3}]}, None)
        self.message = {'account_id': 'a1', 'contact_id': 'x1', 'sender_ref': asdict(self.sender),
            'to': ['buyer@example.com'], 'cc': [], 'bcc': [], 'subject': 'Inventory',
            'body': 'Initial body', 'attachments': [], 'source_ids': [], 'plan_step_id': 'step1'}
        draft = propose_draft(self.store, 'c1', self.message)
        self.message_id = draft.id
        record = self.store.get('message', draft.id)
        self.draft_ref = ExternalRef('mail', 'tenant', 'mail1', 'draft1')
        self.store.put('message', draft.id, dict(record.data, draft_ref=asdict(self.draft_ref), status='drafted'), record.revision)
        preflight = {'connection_id': 'mail1', 'checked_at': NOW, 'ownership_allowed': True,
            'contact_allowed': True, 'opportunity_allowed': True, 'external_revision': 'r1',
            'sender_connection_id': 'mail1', 'sender_object_id': self.sender.object_id,
            'crm_confirmed': True, 'recent_replies': False}
        proposal = propose_send(self.store, self.draft_ref, dict(self.message, body='Edited body', external_revision='r1'), preflight)
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        self.intent = prepare_action(self.store, proposal.id, self.cap, preflight, NOW)
        self.sent_ref = ExternalRef('mail', 'tenant', 'mail1', 'sent1')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_confirmed_send_saves_ids_next_action_and_candidate_edit(self):
        result = ToolResult(self.intent.action_id, 'succeeded', [self.sent_ref], {'sent_at': NOW})
        message = record_delivery(self.store, result, self.message_id)
        self.assertEqual(message.data['delivery_status'], 'sent')
        self.assertEqual(message.data['sent_ref']['object_id'], 'sent1')
        self.assertEqual(message.data['next_action']['due_at'], '2026-10-25T12:00:00Z')
        self.assertEqual(message.data['next_action']['plan_step_id'], 'step2')
        self.assertTrue(message.data['crm_activity_pending'])
        self.assertEqual([r.data['status'] for r in self.store.list('rule')], ['candidate'])
        self.assertEqual(record_delivery(self.store, result, self.message_id), message)
        self.assertEqual(len(self.store.list('action')), 1)

    def test_send_exposes_conversation_and_due_date_to_followup(self):
        conversation = asdict(ExternalRef('mail', 'tenant', 'mail1', 'thread1'))
        record = record_delivery(self.store, ToolResult(self.intent.action_id, 'succeeded',
                    [self.sent_ref], {'sent_at': NOW, 'conversation_ref': conversation}), self.message_id)
        self.assertEqual(record.data['conversation_ref'], conversation)
        self.assertEqual(self.store.get('account', 'a1').data['next_action_at'], '2026-10-25T12:00:00Z')

    def test_repeated_delivery_still_rejects_wrong_connection_result(self):
        result = ToolResult(self.intent.action_id, 'succeeded', [self.sent_ref], {'sent_at': NOW})
        record_delivery(self.store, result, self.message_id)
        with self.assertRaises(GateError) as caught:
            record_delivery(self.store, ToolResult(self.intent.action_id, 'succeeded',
                [ExternalRef('mail', 'tenant', 'other', 'bad')], {'sent_at': NOW}), self.message_id)
        self.assertEqual(caught.exception.code, 'connection_mismatch')

    def test_partial_sent_search_does_not_authorize_retry(self):
        record_delivery(self.store, ToolResult(self.intent.action_id, 'unknown', [], {}), self.message_id)
        action = reconcile_delivery(self.store, self.intent.action_id, [{'complete': False, 'messages': []}])
        self.assertEqual(action.data['status'], 'unknown')
        self.assertEqual(len(self.store.list('action')), 1)
        with self.assertRaises(GateError):
            propose_send(self.store, self.draft_ref, dict(self.message, external_revision='r1'), {})

    def test_reconciliation_finds_sent_message_without_new_send(self):
        record_delivery(self.store, ToolResult(self.intent.action_id, 'unknown', [], {}), self.message_id)
        action = reconcile_delivery(self.store, self.intent.action_id, [{
            'complete': True, 'action_id': self.intent.action_id,
            'external_refs': [asdict(self.sent_ref)], 'sent_at': NOW, 'status': 'sent'}])
        self.assertEqual(action.data['status'], 'succeeded')
        self.assertEqual(self.store.get('message', self.message_id).data['delivery_status'], 'sent')
        self.assertEqual(len(self.store.list('action')), 1)

    def test_sent_reconciliation_preserves_thread_for_reply_tracking(self):
        record_delivery(self.store, ToolResult(self.intent.action_id, 'unknown', [], {}), self.message_id)
        conversation = asdict(ExternalRef('mail', 'tenant', 'mail1', 'thread-found'))
        observation = {'complete': True, 'action_id': self.intent.action_id,
            'external_refs': [asdict(self.sent_ref)], 'sent_at': NOW, 'status': 'sent',
            'conversation_ref': conversation}
        reconcile_delivery(self.store, self.intent.action_id, [observation])
        message = self.store.get('message', self.message_id)
        self.assertEqual(message.data['conversation_ref'], conversation)
        self.assertEqual(message.data['tracking_status'], 'tracked')
        self.assertFalse(message.data['reconciliation_required'])
        before = len(self.store.list('proposal'))
        reconcile_delivery(self.store, self.intent.action_id, [observation])
        self.assertEqual(len(self.store.list('proposal')), before)

    def test_reconciliation_rejects_thread_from_other_identity(self):
        record_delivery(self.store, ToolResult(self.intent.action_id, 'unknown', [], {}), self.message_id)
        with self.assertRaises(GateError) as caught:
            reconcile_delivery(self.store, self.intent.action_id, [{
                'complete': True, 'action_id': self.intent.action_id, 'status': 'sent',
                'external_refs': [asdict(self.sent_ref)], 'sent_at': NOW,
                'conversation_ref': asdict(ExternalRef('mail', 'other-tenant', 'mail1', 'thread'))}])
        self.assertEqual(caught.exception.code, 'connection_mismatch')
        self.assertEqual(self.store.get('action', self.intent.action_id).data['status'], 'unknown')

    def test_unknown_draft_reconciles_then_can_be_proposed_for_send(self):
        proposal = propose_draft(self.store, 'c1', self.message)
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        cap = Capability('email.create_draft', 'email.create_draft', 'mail1',
                         'visible', 'authenticated', 'allowed', 'verified', 'free')
        intent = prepare_action(self.store, proposal.id, cap, {}, NOW)
        record_delivery(self.store, ToolResult(intent.action_id, 'unknown', [], {}), proposal.id)
        found_ref = ExternalRef('mail', 'tenant', 'mail1', 'recovered-draft')
        observation = {'complete': True, 'action_id': intent.action_id, 'status': 'drafted',
                       'external_refs': [asdict(found_ref)]}
        action = reconcile_delivery(self.store, intent.action_id, [observation])
        self.assertEqual(action.data['status'], 'succeeded')
        record = self.store.get('message', proposal.id)
        self.assertEqual(record.data['status'], 'drafted')
        self.assertEqual(record.data['draft_ref'], asdict(found_ref))
        self.assertFalse(record.data['reconciliation_required'])
        sequence = self.store.snapshot().event_sequence
        reconcile_delivery(self.store, intent.action_id, [observation])
        self.assertEqual(self.store.snapshot().event_sequence, sequence)
        preflight = {'connection_id': 'mail1', 'checked_at': NOW, 'ownership_allowed': True,
            'contact_allowed': True, 'opportunity_allowed': True, 'external_revision': 'r1',
            'sender_connection_id': 'mail1', 'sender_object_id': self.sender.object_id,
            'crm_confirmed': True, 'recent_replies': False}
        send = propose_send(self.store, found_ref, dict(self.message, external_revision='r1'), preflight)
        self.assertEqual(send.payload['message_id'], proposal.id)

    def test_record_delivery_processes_unknown_to_confirmed_once(self):
        owner = asdict(ExternalRef('crm', 'tenant', 'crm1', 'seller1'))
        account = self.store.get('account', 'a1')
        self.store.put('account', account.id, dict(account.data, owner_ref=owner), account.revision)
        record_delivery(self.store, ToolResult(self.intent.action_id, 'unknown', [], {}), self.message_id)
        result = ToolResult(self.intent.action_id, 'succeeded', [self.sent_ref],
                            {'reconciled': True, 'sent_at': NOW})
        message = record_delivery(self.store, result, self.message_id)
        self.assertEqual(message.data['status'], 'sent')
        proposals = [r for r in self.store.list('proposal') if r.data.get('operation') == 'crm.write']
        self.assertEqual(len(proposals), 1)
        record_delivery(self.store, result, self.message_id)
        self.assertEqual(len([r for r in self.store.list('proposal') if r.data.get('operation') == 'crm.write']), 1)
        self.assertEqual(message.data['recorded_action_ids'].count(self.intent.action_id), 1)

    def test_unrelated_observation_cannot_confirm_delivery(self):
        record_delivery(self.store, ToolResult(self.intent.action_id, 'unknown', [], {}), self.message_id)
        action = reconcile_delivery(self.store, self.intent.action_id, [{
            'complete': True, 'action_id': 'other', 'external_refs': [asdict(self.sent_ref)],
            'sent_at': NOW, 'status': 'sent'}])
        self.assertEqual(action.data['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
