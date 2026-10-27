"""A reviewed answer can proceed while the cold sequence stays paused."""
from dataclasses import asdict
import unittest
import tests.test_messages as message_fixture
from aclad.approvals import approve, prepare_action
from aclad.delivery import record_delivery
from aclad.followup import start_review, apply_review, finish_review
from aclad.messages import propose_draft, propose_send
from aclad.models import Capability, GateError, ToolResult

NOW = message_fixture.NOW
LATER = '2026-10-23T12:00:00Z'


class ReplyResolutionTests(unittest.TestCase):
    def setUp(self):
        message_fixture.MessagesTests.setUp(self)
        self.store.put('message', 'sent-original', {'campaign_id': 'c1',
            'message': self.message, 'conversation_ref': asdict(self.draft_ref)}, None)

    def tearDown(self):
        message_fixture.MessagesTests.tearDown(self)

    def observe(self, classification='question', **extra):
        event = {'external_ref': dict(asdict(self.draft_ref), object_id='reply-' + classification),
            'conversation_ref': asdict(self.draft_ref), 'account_id': 'a1', 'contact_id': 'x1',
            'kind': 'email', 'occurred_at': NOW, 'source_revision': '1',
            'classification': classification, 'evidence': 'Synthetic selected reply', **extra}
        run = start_review(self.store, 'manual', NOW)
        report = apply_review(self.store, run.id, [event], [], [], NOW)
        finish_review(self.store, run.id, NOW)
        return self.store.get('action', report['findings'][0]['pending_action_id'])

    def resolve(self, action, decision='respond', **extra):
        from aclad.followup import resolve_review
        return resolve_review(self.store, action.id, action.revision,
            self.store.get('contact', 'x1').revision, self.store.get('account', 'a1').revision,
            decision, 'seller-review-evidence', NOW, **extra)

    def test_question_resolution_allows_one_approved_answer_without_resuming_sequence(self):
        action = self.observe()
        resolution = self.resolve(action)
        message = dict(self.message, body='Here is the answer you requested.', reviewed_response_id=resolution.id)
        draft = propose_draft(self.store, 'c1', message)
        self.assertEqual(draft.payload['reply_to_conversation_ref'], asdict(self.draft_ref))
        with self.assertRaises(GateError):
            propose_draft(self.store, 'c1', message)  # one resolution cannot create a second reply
        draft_cap = Capability('email.create_draft', 'email.create_draft', 'mail1',
            'visible', 'authenticated', 'allowed', 'verified', 'free')
        approve(self.store, draft.id, draft.revision, draft.digest, 'seller', NOW)
        intent = prepare_action(self.store, draft.id, draft_cap, {}, NOW)
        record_delivery(self.store, ToolResult(intent.action_id, 'succeeded', [self.draft_ref], {}), draft.id)
        preflight = dict(self.preflight, recent_replies=True,
            reviewed_reply_event_id=resolution.data['event_id'], latest_reply_event_id=resolution.data['event_id'])
        send = propose_send(self.store, self.draft_ref, dict(message, external_revision='rev1'), preflight)
        with self.assertRaises(GateError):
            prepare_action(self.store, send.id, self.cap, preflight, NOW)
        approve(self.store, send.id, send.revision, send.digest, 'seller', NOW)
        sent = prepare_action(self.store, send.id, self.cap, preflight, NOW)
        record_delivery(self.store, ToolResult(sent.action_id, 'succeeded', [self.draft_ref], {}), draft.id)
        self.assertTrue(self.store.get('contact', 'x1').data['sequence_paused'])
        self.assertTrue(self.store.get('contact', 'x1').data['contact_blocked'])
        self.assertEqual(self.store.get('action', action.id).data['status'], 'resolved')
        self.assertEqual(self.store.get('decision', resolution.id).data['status'], 'used')
        with self.assertRaises(GateError):
            propose_draft(self.store, 'c1', message)

    def test_resolution_preserves_dnc_bounce_and_preexisting_manual_blocks(self):
        for classification in ('bounce', 'do_not_contact'):
            action = self.observe(classification)
            with self.assertRaises(GateError):
                self.resolve(action)
        self.assertTrue(self.store.get('contact', 'x1').data['do_not_contact'])

    def test_preexisting_manual_block_cannot_be_removed_by_reply_resolution(self):
        contact = self.store.get('contact', 'x1')
        self.store.put('contact', 'x1', dict(contact.data, contact_blocked=True), contact.revision)
        action = self.observe()
        for decision in ('respond', 'resume_sequence'):
            with self.assertRaises(GateError):
                self.resolve(action, decision)

    def test_interest_response_keeps_account_paused_and_new_reply_blocks_send(self):
        action = self.observe('interested')
        resolution = self.resolve(action)
        message = dict(self.message, reviewed_response_id=resolution.id)
        proposal = propose_draft(self.store, 'c1', message)
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        self.observe('question')
        cap = Capability('email.create_draft', 'email.create_draft', 'mail1',
            'visible', 'authenticated', 'allowed', 'verified', 'free')
        with self.assertRaises(GateError):
            prepare_action(self.store, proposal.id, cap, {}, NOW)
        self.assertTrue(self.store.get('account', 'a1').data['sequence_paused'])

    def test_resolution_is_versioned_and_new_reply_invalidates_permission(self):
        from aclad.followup import resolve_review
        action = self.observe()
        with self.assertRaises(GateError):
            resolve_review(self.store, action.id, action.revision, 0,
                self.store.get('account', 'a1').revision, 'respond', 'evidence', NOW)
        resolution = self.resolve(action)
        self.observe('interested')
        with self.assertRaises(GateError):
            propose_draft(self.store, 'c1', dict(self.message, reviewed_response_id=resolution.id))

    def test_not_now_date_produces_reviewable_due_work_and_explicit_resume(self):
        self.observe('not_now', resume_at=LATER)
        run = start_review(self.store, 'scheduled', LATER)
        report = apply_review(self.store, run.id, [], [], [], LATER)
        finish_review(self.store, run.id, LATER)
        due = [item for item in report['pending_actions'] if item['type'] == 'review_resume']
        self.assertEqual(len(due), 1)
        self.assertTrue(self.store.get('contact', 'x1').data['sequence_paused'])
        action = self.store.get('action', due[0]['id'])
        self.resolve(action, 'resume_sequence')
        self.assertFalse(self.store.get('contact', 'x1').data['sequence_paused'])
        self.assertFalse(self.store.get('contact', 'x1').data['contact_blocked'])
        run = start_review(self.store, 'manual', LATER)
        repeated = apply_review(self.store, run.id, [], [], [], LATER)
        finish_review(self.store, run.id, LATER)
        self.assertFalse(repeated['notify'])
