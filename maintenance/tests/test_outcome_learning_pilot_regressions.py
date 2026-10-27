"""Pilot learning regressions use confirmed local effects, never real providers."""
from aclad.models import GateError, canonical
from aclad.outcome_learning import (outcome_context, propose_outcome_rule, refresh_outcome_observations,
                                    relevant_outcome_rules)
from aclad.store import Store
from tests.test_outcome_observations import OutcomeFixture


class PilotLearningRegressions(OutcomeFixture):
    def test_missing_message_context_recovers_reviewed_frozen_strategy(self):
        # Ignoring the immutable approved plan makes an ordinary send unlearnable.
        self.send()
        observation, = refresh_outcome_observations(self.store)
        self.assertEqual(observation.data['context'], {'objective': 'Meeting', 'approach': 'Inventory'})
        rule = propose_outcome_rule(self.store, {'task': 'email', 'objective': 'Meeting'},
                                    'Try a short inventory question.', [observation.id])
        self.assertEqual(rule.data['status'], 'candidate')
        self.assertEqual(relevant_outcome_rules(self.store, rule.data['context']), [])

    def read_context(self, campaign_id='campaign', task='email'):
        return outcome_context(self.store, campaign_id, task)

    def test_learning_read_after_dnc_preserves_complete_sample_and_outreach_block(self):
        from aclad.outreach import generation_context
        self.send('a')
        self.send('b')
        self.review_reply('a', classification='do_not_contact')
        refresh_outcome_observations(self.store)
        before = self.store.snapshot()
        output = self.read_context()
        observation, = output['observations']
        self.assertEqual(observation['proposal_context'],
                         {'task': 'email', 'objective': 'Meeting', 'approach': 'Inventory'})
        self.assertEqual(observation['sample'], {'exposed': 2, 'replied': 1, 'meetings': 0,
                                                'checked_without_reply': 1, 'unobserved': 0})
        self.assertEqual(self.store.snapshot(), before, 'The evidence reader must not mutate canonical state.')
        with self.assertRaises(GateError) as caught:
            generation_context(self.store, 'campaign', 'a', 'contact-a')
        self.assertEqual(caught.exception.code, 'contact_blocked')
        rule = propose_outcome_rule(self.store, observation['proposal_context'],
                                    'Hypothesis: try a short question; small observational sample.',
                                    observation['evidence_ids'])
        self.assertEqual(rule.data['status'], 'candidate')
        self.store.close()
        self.store = Store(self.directory, self.scope)
        self.assertEqual(self.store.get('rule', rule.id), rule)
        self.assertEqual(relevant_outcome_rules(self.store, rule.data['context']), [])

    def test_learning_read_rejects_nonexistent_campaign_and_unknown_task(self):
        for campaign, task, code in [('missing', 'email', 'campaign_required'),
                                      ('campaign', 'send', 'invalid_rule_scope')]:
            with self.subTest(campaign=campaign, task=task):
                with self.assertRaises(GateError) as caught:
                    self.read_context(campaign, task)
                self.assertEqual(caught.exception.code, code)

    def test_learning_read_excludes_unsent_and_other_campaign_observations(self):
        self.assertEqual(self.read_context()['observations'], [])
        self.send('a')
        refresh_outcome_observations(self.store)
        self.store.put('campaign', 'other', {'icp_id': 'other-icp', 'icp_revision': 1}, None)
        self.assertEqual(self.read_context('other')['observations'], [])
        self.assertEqual(len(self.read_context()['observations']), 1)

    def test_learning_read_marks_unprojected_new_reply_stale(self):
        self.send('a')
        refresh_outcome_observations(self.store)
        self.review_reply('a')
        before = self.store.snapshot()
        output = self.read_context()
        self.assertEqual(output['status'], 'refresh_required')
        self.assertTrue(all(row['proposal_context'] is None for row in output['observations']))
        self.assertEqual(self.store.snapshot(), before)
        refresh_outcome_observations(self.store)
        self.assertEqual(self.read_context()['status'], 'current')

    def test_dispatched_learning_read_does_not_recover_unrelated_inflight_action(self):
        from aclad.commands import dispatch
        self.store.put('action', 'unrelated', {'operation': 'accounts.search', 'status': 'in_flight',
                                              'prepared_at': '2020-01-01T00:00:00Z'}, None)
        before = self.store.snapshot()
        output = dispatch(self.store, 'outcome-context', {'campaign_id': 'campaign'})
        self.assertEqual(output['status'], 'current')
        self.assertEqual(self.store.snapshot(), before)

    def test_fallback_preserves_approved_snapshot_after_mutable_plan_and_fact_changes(self):
        self.send()
        first, = refresh_outcome_observations(self.store)
        plan = self.store.get('outreach_plan', 'plan')
        self.store.put('outreach_plan', plan.id, dict(plan.data, steps=[]), plan.revision)
        account = self.store.get('account', 'a')
        self.store.put('account', account.id, dict(account.data, industry='Manufacturing'), account.revision)
        self.assertEqual(refresh_outcome_observations(self.store), [first])
        self.assertNotIn('industry', first.data['context'])
        self.assertNotIn('variant', first.data['context'])
        self.assertNotIn('Draft body', canonical(self.read_context()))
        self.assertNotIn('Reviewed sent body', canonical(self.read_context()))

    def test_legacy_without_frozen_basis_retains_unknown_scope(self):
        _, intent, _ = self.send()
        action = self.store.get('action', intent.action_id)
        # Model a pre-snapshot successful action; the mutable plan is no evidence
        # of the strategy approved for that historical send.
        content = dict(action.data['payload'])
        del content['learning_basis']
        self.store.put('action', action.id, dict(action.data, payload=content), action.revision)
        observation, = refresh_outcome_observations(self.store)
        self.assertEqual(observation.data['context'], {})
        view, = self.read_context()['observations']
        self.assertIsNone(view['proposal_context'])
        self.assertEqual(view['sample']['exposed'], 1)
        with self.assertRaises(GateError) as caught:
            propose_outcome_rule(self.store, {'task': 'email', 'objective': 'Meeting'},
                                 'Try questions.', view['evidence_ids'])
        self.assertEqual(caught.exception.code, 'learning_evidence_scope_mismatch')

    def test_unrepresentable_snapshot_strategy_does_not_drop_exposure(self):
        plan = self.store.get('outreach_plan', 'plan')
        steps = [dict(step, objective='x' * 301, angle='') for step in plan.data['steps']]
        self.store.put('outreach_plan', plan.id, dict(plan.data, steps=steps), plan.revision)
        self.send()
        observation, = refresh_outcome_observations(self.store)
        self.assertEqual(observation.data['context'], {})
        self.assertEqual(observation.data['exposure_count'], 1)

    def test_action_ids_are_still_not_observation_evidence(self):
        _, intent, _ = self.send()
        observation, = refresh_outcome_observations(self.store)
        with self.assertRaises(GateError) as caught:
            propose_outcome_rule(self.store, {'task': 'email', 'objective': 'Meeting'},
                                 'Try a question.', [observation.id, intent.action_id])
        self.assertEqual(caught.exception.code, 'learning_evidence_required')
        self.assertFalse(any(row.data.get('scope_kind') == 'performance' for row in self.store.list('rule')))

    def test_other_seller_store_cannot_read_local_learning(self):
        from aclad.models import Scope
        self.send()
        refresh_outcome_observations(self.store)
        other = Store(self.directory.parent / 'other', Scope('p', 'other', 'other'))
        self.addCleanup(other.close)
        other.put('campaign', 'campaign', {'icp_id': 'icp', 'icp_revision': 1}, None)
        self.assertEqual(outcome_context(other, 'campaign')['observations'], [])

    def test_campaign_proposal_context_intersects_strategies_and_keeps_negative_cohort(self):
        plan = self.store.get('outreach_plan', 'plan')
        steps = [dict(step, angle='Distribution') if step['contact_id'] == 'contact-b' else step
                 for step in plan.data['steps']]
        self.store.put('outreach_plan', plan.id, dict(plan.data, steps=steps), plan.revision)
        self.send('a')
        self.send('b')
        self.review_reply('a')
        refresh_outcome_observations(self.store)
        output = self.read_context()
        self.assertEqual(output.get('proposal_context'), {'task': 'email', 'objective': 'Meeting'})
        self.assertEqual(set(output['evidence_ids']), {row['id'] for row in output['observations']})
        rule = propose_outcome_rule(self.store, output['proposal_context'],
                                    'Try a concise opening; retain both strategies in review.',
                                    output['evidence_ids'])
        self.assertEqual(rule.data['sample'], {'exposed': 2, 'replied': 1, 'unobserved': 0})
        self.assertEqual(rule.data['status'], 'candidate')
