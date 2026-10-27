"""Outcome learning observes approved sends, never draft intent or mailbox content."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from aclad.approvals import approve, prepare_action, create_proposal, record_result
from aclad.delivery import record_delivery
from aclad.followup import apply_review, start_review, finish_review
from aclad.messages import propose_draft, propose_send
from aclad.models import Capability, ExternalRef, GateError, Scope, ToolResult, canonical
from aclad.outcome_learning import refresh_outcome_observations, validate_learning_context
from aclad.store import Store
from aclad.prospecting import record_candidates

NOW = '2026-10-22T12:00:00Z'
LATER = '2026-10-23T12:00:00Z'


class OutcomeFixture(TestCase):
    """Build sends through distinct draft/send approvals and real result APIs."""
    workspace = False

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'state'
        scope = Scope('p', 's', 'i')
        if self.workspace:
            from aclad.workspace import initialize_workspace
            initialized = initialize_workspace(Path(self.tmp.name) / 'Seller project', 'Seller')
            self.workspace_root = Path(initialized['root'])
            self.directory = Path(initialized['state_dir'])
            scope = Scope(initialized['partner_id'], initialized['seller_id'], initialized['instance_id'])
        self.scope = scope
        self.store = Store(self.directory, scope)
        self.addCleanup(lambda: self.store.close())
        self.store.put('campaign', 'campaign', {'icp_id': 'icp', 'icp_revision': 1}, None)
        self.sender = ExternalRef('mail', 'tenant', 'mail', 'seller@example.com')
        for operation in ('email.send', 'email.create_draft'):
            cap = Capability(operation, operation, 'mail', 'visible', 'authenticated', 'allowed', 'verified', 'free')
            self.store.put('connection', operation, {'account_identity': self.sender.object_id,
                           'capability': asdict(cap)}, None)
        for identifier in ('a', 'b'):
            self.store.put('account', identifier, {'selected': True, 'campaign_id': 'campaign',
                                                 'crm_status': 'confirmed'}, None)
            self.store.put('contact', 'contact-' + identifier, {'selected': True, 'campaign_id': 'campaign',
                           'account_id': identifier, 'crm_status': 'confirmed'}, None)
        self.store.put('outreach_plan', 'plan', {'campaign_id': 'campaign', 'icp_id': 'icp', 'icp_revision': 1,
            'steps': [{'id': 'step-' + account + '-' + str(index), 'contact_id': 'contact-' + account,
                       'channel': 'email', 'objective': 'Meeting', 'angle': 'Inventory', 'delay_days': index,
                       'learning_context': {'objective': 'Meeting', 'approach': 'Inventory',
                                            'variant': 'question', 'source_ids': []}}
                      for account in ('a', 'b') for index in (0, 1)]}, None)

    def send(self, account='a', index=0, edited_body='Reviewed sent body', with_context=False, defer_result=False, sent_at=NOW):
        message = {'account_id': account, 'contact_id': 'contact-' + account,
            'sender_ref': asdict(self.sender), 'to': ['buyer@example.com'], 'cc': [], 'bcc': [],
            'subject': 'Inventory', 'body': 'Draft body', 'attachments': [], 'source_ids': [],
            'plan_step_id': 'step-' + account + '-' + str(index)}
        if with_context:
            message['learning_context'] = next(step['learning_context'] for step in
                self.store.get('outreach_plan', 'plan').data['steps'] if step['id'] == message['plan_step_id'])
        draft = propose_draft(self.store, 'campaign', message)
        approve(self.store, draft.id, draft.revision, draft.digest, 'seller', NOW)
        cap = Capability('email.create_draft', 'email.create_draft', 'mail', 'visible', 'authenticated', 'allowed', 'verified', 'free')
        intent = prepare_action(self.store, draft.id, cap, {}, NOW)
        draft_ref = ExternalRef('mail', 'tenant', 'mail', 'draft-' + draft.id)
        record_delivery(self.store, ToolResult(intent.action_id, 'succeeded', [draft_ref], {}), draft.id)
        preflight = {'connection_id': 'mail', 'checked_at': NOW, 'ownership_allowed': True,
            'contact_allowed': True, 'opportunity_allowed': True, 'external_revision': 'r1',
            'sender_connection_id': 'mail', 'sender_object_id': self.sender.object_id,
            'crm_confirmed': True, 'recent_replies': False}
        proposal = propose_send(self.store, draft_ref, dict(message, body=edited_body, external_revision='r1'), preflight)
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        cap = Capability('email.send', 'email.send', 'mail', 'visible', 'authenticated', 'allowed', 'verified', 'free')
        intent = prepare_action(self.store, proposal.id, cap, preflight, NOW)
        sent = ExternalRef('mail', 'tenant', 'mail', 'sent-' + draft.id)
        result = ToolResult(intent.action_id, 'succeeded', [sent], {'sent_at': sent_at,
                 'conversation_ref': asdict(ExternalRef('mail', 'tenant', 'mail', 'thread-' + account))})
        if not defer_result:
            record_delivery(self.store, result, draft.id)
        return draft.id, intent, result

    def source_industry(self, account='a', industry='Manufacturing'):
        operation = 'accounts.search'
        cap = Capability(operation, operation, 'prospect', 'visible', 'authenticated', 'allowed', 'verified', 'free')
        if not self.store.get('connection', operation):
            self.store.put('connection', operation, {'account_identity': 'seller-prospect', 'capability': asdict(cap)}, None)
        proposal = create_proposal(self.store, operation, 'prospect', [account], {'campaign_id': 'campaign'})
        intent = prepare_action(self.store, proposal.id, cap, {}, NOW)
        ref = ExternalRef('prospect', 'tenant', 'prospect', 'company-' + account)
        candidate = {'id': account, 'industry': industry, 'external_ref': asdict(ref), 'source_at': NOW}
        record_result(self.store, ToolResult(intent.action_id, 'succeeded', [ref],
                                            {'complete': True, 'candidates': [candidate]}))
        record_candidates(self.store, 'campaign', 'account', [candidate], intent.action_id)
        return intent.action_id

    def review_reply(self, account='a', classification='interested', identifier='reply-a', revision='1'):
        run = start_review(self.store, 'manual', LATER, ['campaign'])
        event = {'external_ref': asdict(ExternalRef('mail', 'tenant', 'mail', identifier)),
            'conversation_ref': asdict(ExternalRef('mail', 'tenant', 'mail', 'thread-' + account)),
            'source_revision': revision, 'evidence': 'native-message', 'occurred_at': LATER,
            'kind': 'email', 'account_id': account, 'contact_id': 'contact-' + account,
            'classification': classification}
        apply_review(self.store, run.id, [event], [{'connection_id': 'mail', 'source': 'email',
                     'complete': True, 'next_cursor': 'next'}], [], LATER)
        finish_review(self.store, run.id, LATER)


class OutcomeObservationTests(OutcomeFixture):
    def test_empty_state_has_no_inferred_learning(self):
        self.assertEqual(refresh_outcome_observations(self.store), [])
        self.assertEqual(self.store.list('rule'), [])

    def test_confirmed_version_and_unknown_facts(self):
        message_id, intent, _ = self.send()
        observation, = refresh_outcome_observations(self.store)
        version, = observation.data['exposures'][0]['versions']
        self.assertEqual(version['message_id'], message_id)
        self.assertEqual(version['action_id'], intent.action_id)
        self.assertEqual(version['message_digest'], __import__('hashlib').sha256(canonical(
            self.store.get('action', intent.action_id).data['payload']['message']).encode()).hexdigest())
        self.assertNotIn('industry', observation.data['context'])
        self.assertNotIn('persona', observation.data['context'])
        self.assertNotIn('Reviewed sent body', canonical(observation.data))

    def test_followups_and_replays_deduplicate_exposure(self):
        self.send(index=0)
        _, intent, result = self.send(index=1)
        first, = refresh_outcome_observations(self.store)
        self.assertEqual(first.data['exposure_count'], 1)
        self.assertEqual(len(first.data['exposures'][0]['versions']), 2)
        record_delivery(self.store, result, self.store.get('action', intent.action_id).data['payload']['message_id'])
        self.assertEqual(refresh_outcome_observations(self.store), [first])

    def test_positive_and_negative_sequence_outcomes(self):
        self.send('a', 0)
        self.send('a', 1)
        self.send('b', 0)
        self.review_reply()
        row, = refresh_outcome_observations(self.store)
        self.assertEqual(row.data['exposure_count'], 2)
        self.assertEqual(row.data['replied_account_count'], 1)
        self.assertEqual(row.data['checked_without_reply'], 1)
        self.assertEqual(row.data['attribution'], 'sequence')
        self.assertEqual({x['account_id'] for x in row.data['exposures']}, {'a', 'b'})
        self.assertTrue(row.data['limitations'])

    def test_single_positive_is_candidate_not_active(self):
        self.send()
        self.review_reply()
        row, = refresh_outcome_observations(self.store)
        self.assertEqual(row.data['status'], 'candidate')
        self.assertFalse(any(r.data.get('status') == 'active' for r in self.store.list('rule')))

    def test_new_results_refresh_after_restart_without_learn(self):
        self.send()
        self.store.close()
        self.store = Store(self.directory, Scope('p', 's', 'i'))
        row, = refresh_outcome_observations(self.store)
        self.assertEqual(refresh_outcome_observations(self.store), [row])

    def test_unknown_result_and_fake_sent_flag_are_not_exposure(self):
        self.store.put('message', 'fake', {'campaign_id': 'campaign', 'status': 'sent',
            'message': {'account_id': 'a'}, 'current_message': {'account_id': 'a'},
            'send_action_id': 'missing'}, None)
        self.assertEqual(refresh_outcome_observations(self.store), [])

    def test_factual_context_requires_exact_provider_provenance(self):
        context = {'industry': 'Manufacturing', 'source_ids': ['missing']}
        with self.assertRaises(GateError):
            validate_learning_context(self.store, context, account_id='a', contact_id='contact-a')
        source_id = self.source_industry()
        self.assertEqual(validate_learning_context(self.store, dict(context, source_ids=[source_id]),
                         account_id='a', contact_id='contact-a')['industry'], 'Manufacturing')
        with self.assertRaises(GateError):
            validate_learning_context(self.store, dict(context, source_ids=[source_id]), account_id='b')

    def test_conflicting_opaque_reply_revision_is_unclassified(self):
        self.send()
        self.review_reply()
        self.review_reply(classification='auto', revision='opaque-revision')
        row, = refresh_outcome_observations(self.store)
        self.assertEqual(row.data['replied_account_count'], 0)

    def test_mismatched_sent_reference_is_not_an_exposure(self):
        message_id, _, _ = self.send()
        row = self.store.get('message', message_id)
        self.store.put('message', row.id, dict(row.data, sent_ref=asdict(
            ExternalRef('mail', 'tenant', 'mail', 'unrelated'))), row.revision)
        self.assertEqual(refresh_outcome_observations(self.store), [])

    def test_external_aliases_deduplicate_account_exposure(self):
        ref = asdict(ExternalRef('crm', 'tenant', 'crm', 'same-company'))
        for identifier in ('a', 'b'):
            row = self.store.get('account', identifier)
            self.store.put('account', identifier, dict(row.data, external_ref=ref), row.revision)
        self.send('a')
        self.send('b')
        observation, = refresh_outcome_observations(self.store)
        self.assertEqual(observation.data['exposure_count'], 1)
        self.assertEqual(len(observation.data['exposures'][0]['versions']), 2)

    def test_coverage_before_latest_touch_is_not_verified_silence(self):
        self.send('a')
        self.send('b')
        self.review_reply('b')
        self.send('a', 1, sent_at='2026-10-24T12:00:00Z')
        observation, = refresh_outcome_observations(self.store)
        self.assertEqual(observation.data['checked_without_reply'], 0)
        self.assertEqual(observation.data['unobserved_count'], 1)

    def test_approved_plan_basis_survives_later_plan_revisions(self):
        _, intent, _ = self.send(with_context=True)
        action = self.store.get('action', intent.action_id)
        self.assertIn('learning_basis', action.data['payload'], 'send approval must freeze the exact plan basis')
        first, = refresh_outcome_observations(self.store)
        plan = self.store.get('outreach_plan', 'plan')
        self.store.put('outreach_plan', plan.id, dict(plan.data, steps=[], icp_revision=99), plan.revision)
        self.assertEqual(refresh_outcome_observations(self.store), [first])
