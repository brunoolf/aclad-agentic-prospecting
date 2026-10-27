import copy
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from aclad.approvals import approve, create_proposal, prepare_action
from aclad.messages import propose_draft, propose_send
from aclad.models import Capability, ExternalRef, GateError, Scope, ToolResult
from aclad.delivery import record_delivery
from aclad.store import Store

NOW = '2026-10-22T12:00:00Z'


class MessagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name), Scope('p', 's', 'i'))
        self.store.put('campaign', 'c1', {}, None)
        self.store.put('account', 'a1', {'selected': True, 'campaign_id': 'c1', 'crm_status': 'confirmed'}, None)
        self.store.put('contact', 'x1', {'selected': True, 'campaign_id': 'c1',
            'account_id': 'a1', 'crm_status': 'confirmed'}, None)
        self.sender = ExternalRef('mail', 'tenant', 'mail1', 'seller@example.com')
        self.cap = Capability('email.send', 'email.send', 'mail1', 'visible', 'authenticated', 'allowed', 'verified', 'free')
        for operation in ('email.create_draft', 'email.send'):
            self.store.put('connection', operation, {'account_identity': self.sender.object_id,
                'capability': asdict(Capability(operation, operation, 'mail1', 'visible',
                    'authenticated', 'allowed', 'verified', 'free'))}, None)
        self.store.put('outreach_plan', 'plan1', {'campaign_id': 'c1', 'steps': [
            {'id': 'step1', 'contact_id': 'x1', 'channel': 'email', 'delay_days': 3}]}, None)
        self.message = {'account_id': 'a1', 'contact_id': 'x1', 'sender_ref': asdict(self.sender),
            'to': ['buyer@example.com'], 'cc': [], 'bcc': [], 'subject': 'Inventory',
            'body': 'How are you managing inventory?', 'attachments': [],
            'source_ids': ['company-site'], 'plan_step_id': 'step1'}
        self.draft_ref = ExternalRef('mail', 'tenant', 'mail1', 'draft1')
        self.preflight = {'connection_id': 'mail1', 'checked_at': NOW, 'ownership_allowed': True,
            'contact_allowed': True, 'opportunity_allowed': True, 'external_revision': 'rev1',
            'sender_connection_id': 'mail1', 'sender_object_id': 'seller@example.com',
            'crm_confirmed': True, 'recent_replies': False}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def stored_draft(self):
        proposal = propose_draft(self.store, 'c1', self.message)
        message = self.store.get('message', proposal.id)
        self.store.put('message', proposal.id, dict(message.data, draft_ref=asdict(self.draft_ref), status='drafted'), message.revision)
        return proposal

    def test_native_draft_result_becomes_durable_send_input(self):
        proposal = propose_draft(self.store, 'c1', self.message)
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        capability = Capability('email.create_draft', 'email.create_draft', 'mail1',
            'visible', 'authenticated', 'allowed', 'verified', 'free')
        intent = prepare_action(self.store, proposal.id, capability, {}, NOW)
        message = record_delivery(self.store, ToolResult(intent.action_id, 'succeeded',
                                  [self.draft_ref], {}), proposal.id)
        self.assertEqual(message.data['status'], 'drafted')
        send = propose_send(self.store, self.draft_ref, dict(self.message, external_revision='rev1'), self.preflight)
        self.assertEqual(send.payload['message_id'], message.id)

    def test_request_to_draft_never_authorizes_send(self):
        self.stored_draft()
        proposal = propose_send(self.store, self.draft_ref, dict(self.message, external_revision='rev1'), self.preflight)
        with self.assertRaises(GateError) as caught:
            prepare_action(self.store, proposal.id, self.cap, self.preflight, NOW)
        self.assertEqual(caught.exception.code, 'approval_required')
        self.assertEqual(self.store.list('action'), [])

    def test_provider_edits_get_new_digest_and_full_current_preview(self):
        self.stored_draft()
        first = propose_send(self.store, self.draft_ref, dict(self.message, external_revision='rev1'), self.preflight)
        for key, value in [('body', 'Changed body'), ('to', ['other@example.com']),
                           ('cc', ['cc@example.com']), ('bcc', ['bcc@example.com'])]:
            updated = dict(self.message, external_revision='rev1', **{key: value})
            second = propose_send(self.store, self.draft_ref, updated, self.preflight)
            self.assertNotEqual(second.digest, first.digest)
            self.assertEqual(second.payload['message'][key], value)

    def test_reply_and_block_before_send_prevent_any_intent(self):
        self.stored_draft()
        for changes in ({'recent_replies': True}, {'contact_allowed': False}):
            with self.subTest(changes=changes), self.assertRaises(GateError) as caught:
                propose_send(self.store, self.draft_ref, dict(self.message, external_revision='rev1'),
                             dict(self.preflight, **changes))
            self.assertEqual(caught.exception.code, 'contact_blocked')
        self.assertEqual(self.store.list('action'), [])

    def test_other_mailbox_uncertain_crm_and_unverified_attachments_are_blocked(self):
        self.stored_draft()
        cases = [(dict(self.preflight, sender_object_id='other@example.com'), self.message, 'sender_mismatch'),
                 (dict(self.preflight, crm_confirmed=False), self.message, 'crm_unconfirmed'),
                 (self.preflight, dict(self.message, attachments=['report.pdf']), 'attachments_unverified')]
        for preflight, message, code in cases:
            with self.subTest(code=code), self.assertRaises(GateError) as caught:
                propose_send(self.store, self.draft_ref, dict(message, external_revision='rev1'), preflight)
            self.assertEqual(caught.exception.code, code)

    def test_provider_edit_invalidates_previously_approved_send(self):
        self.stored_draft()
        first = propose_send(self.store, self.draft_ref, dict(self.message, external_revision='rev1'), self.preflight)
        approve(self.store, first.id, first.revision, first.digest, 'seller', NOW)
        propose_send(self.store, self.draft_ref, dict(self.message, body='Changed', external_revision='rev1'), self.preflight)
        with self.assertRaises(GateError) as caught:
            prepare_action(self.store, first.id, self.cap, self.preflight, NOW)
        self.assertEqual(caught.exception.code, 'proposal_not_executable')

    def test_reply_arriving_after_approval_blocks_actual_prepare(self):
        self.stored_draft()
        proposal = propose_send(self.store, self.draft_ref, dict(self.message, external_revision='rev1'), self.preflight)
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        with self.assertRaises(GateError) as caught:
            prepare_action(self.store, proposal.id, self.cap, dict(self.preflight, recent_replies=True), NOW)
        self.assertEqual(caught.exception.code, 'contact_blocked')
        self.assertEqual(self.store.list('action'), [])

    def test_account_pause_blocks_other_selected_contact_before_send(self):
        self.stored_draft()
        proposal = propose_send(self.store, self.draft_ref, dict(self.message, external_revision='rev1'), self.preflight)
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        account = self.store.get('account', 'a1')
        self.store.put('account', account.id, dict(account.data, contact_blocked=True), account.revision)
        with self.assertRaises(GateError) as caught:
            prepare_action(self.store, proposal.id, self.cap, self.preflight, NOW)
        self.assertEqual(caught.exception.code, 'contact_blocked')

    def test_second_proposal_cannot_send_same_provider_draft_again(self):
        self.stored_draft()
        first = propose_send(self.store, self.draft_ref, dict(self.message, external_revision='rev1'), self.preflight)
        second = create_proposal(self.store, first.operation, first.connection_id, first.item_ids, first.payload)
        for proposal in (first, second):
            approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        prepare_action(self.store, first.id, self.cap, self.preflight, NOW)
        with self.assertRaises(GateError) as caught:
            prepare_action(self.store, second.id, self.cap, self.preflight, NOW)
        self.assertEqual(caught.exception.code, 'reconciliation_required')
        self.assertEqual(len(self.store.list('action')), 1)

    def test_current_approved_version_emits_one_send_intent(self):
        self.stored_draft()
        proposal = propose_send(self.store, self.draft_ref, dict(self.message, external_revision='rev1'), self.preflight)
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        intent = prepare_action(self.store, proposal.id, self.cap, self.preflight, NOW)
        self.assertEqual(intent.operation, 'email.send')
        self.assertEqual(intent.payload['message']['body'], self.message['body'])
        self.assertEqual(intent.payload['draft_ref']['object_id'], 'draft1')
        with self.assertRaises(GateError):
            prepare_action(self.store, proposal.id, self.cap, self.preflight, NOW)
        self.assertEqual(len(self.store.list('action')), 1)


if __name__ == '__main__':
    unittest.main()
