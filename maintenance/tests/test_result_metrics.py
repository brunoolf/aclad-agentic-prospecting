from dataclasses import replace

from aclad.accounts import select_accounts
from aclad.models import Event
from aclad.followup import start_review, apply_review, finish_review
from tests.support import StateTest, NOW
from tests.results_support import seed_results, result_ref


class MetricTests(StateTest):
    def test_acceptance_rates(self):
        from aclad.result_metrics import calculate_results
        from aclad.results import render_results
        seed_results(self.store)
        metrics = calculate_results(self.store)
        self.assertEqual((metrics.searched_accounts, metrics.ever_selected_accounts,
                          metrics.contacted_accounts, metrics.sent_messages,
                          metrics.human_reply_messages, metrics.replied_accounts,
                          metrics.booked_meetings), (100, 30, 10, 20, 4, 3, 2))
        self.assertEqual([(r.numerator, r.denominator) for r in
            (metrics.selection, metrics.approach, metrics.reply, metrics.booking, metrics.reply_to_booking)],
            [(30, 100), (10, 30), (3, 10), (2, 10), (2, 3)])
        for rate in ('30,00%', '33,33%', '20,00%', '66,67%'):
            self.assertIn(rate, render_results(metrics))

    def test_duplicates_revisions_selection_and_campaign_union(self):
        from aclad.result_metrics import calculate_results
        from aclad.prospecting import record_candidates, open_campaign
        seed_results(self.store)
        original = calculate_results(self.store)
        record_candidates(self.store, 'campaign', 'account', self.store.get('action', 'search').data['result']['candidates'], 'search')
        select_accounts(self.store, 'campaign', [])
        self.assertEqual(calculate_results(self.store).ever_selected_accounts, 30)
        self.assertEqual(calculate_results(self.store).current_selected_accounts, 0)
        select_accounts(self.store, 'campaign', [f'a{i}' for i in range(30)])
        open_campaign(self.store, 'other', 'Other')
        for row in self.store.list('account'):
            self.store.put('account', row.id, dict(row.data, campaign_ids=['campaign', 'other']), row.revision)
        self.store.record_event(Event('shared-search', 'other', 'candidates_recorded', NOW,
            {'kind': 'account', 'evidence_id': 'search', 'count': 100, 'item_ids': [f'a{i}' for i in range(100)]}))
        self.store.record_event(Event('shared-selection', 'other', 'accounts_selected', NOW,
            {'item_ids': [f'a{i}' for i in range(30)]}))
        # One native reply is still one message after provider revisions.
        event = self.store.list('decision')[0].data.get('event')
        run = start_review(self.store, 'manual', NOW)
        apply_review(self.store, run.id, [{**event, 'source_revision': '2'}], [], [], NOW)
        finish_review(self.store, run.id, NOW)
        metrics = calculate_results(self.store)
        self.assertEqual(metrics.sent_messages, original.sent_messages)
        self.assertEqual(metrics.human_reply_messages, original.human_reply_messages)
        self.assertEqual(metrics.searched_accounts, 100)
        self.assertEqual(metrics.ever_selected_accounts, 30)
        self.assertTrue(all(r.numerator <= r.denominator for r in
            (metrics.selection, metrics.approach, metrics.reply, metrics.booking, metrics.reply_to_booking)))

    def test_drafts_unknowns_bounces_and_unchecked_coverage(self):
        from aclad.result_metrics import calculate_results
        from aclad.results import render_results
        empty = calculate_results(self.store)
        self.assertIn('N/D', render_results(empty))
        seed_results(self.store)
        for state in ('drafted', 'unknown', 'failed'):
            self.store.put('message', state, {'status': state, 'campaign_id': 'campaign',
                'message': {'account_id': 'a0', 'contact_id': 'c0'}, 'sent_ref': result_ref(state)}, None)
        events = [{'external_ref': result_ref(kind), 'conversation_ref': result_ref('thread-0'),
            'account_id': 'a0', 'contact_id': 'c0', 'kind': 'email', 'occurred_at': NOW,
            'source_revision': '1', 'classification': kind, 'evidence': 'Saved automatic result'}
            for kind in ('auto', 'bounce', 'needs_review')]
        run = start_review(self.store, 'manual', NOW)
        apply_review(self.store, run.id, events, [], [], NOW)
        finish_review(self.store, run.id, NOW)
        metrics = calculate_results(self.store)
        self.assertEqual((metrics.sent_messages, metrics.human_reply_messages), (20, 4))
        self.assertEqual(metrics.reply_conversations_checked, 10)
        self.assertEqual(metrics.calendar_accounts_checked, 10)
        self.assertEqual(metrics.account_sources_checked, 1)
        self.assertIn('Cobertura', render_results(replace(metrics, reply_conversations_checked=0)))

    def test_same_name_is_not_canonical_identity(self):
        from aclad.result_metrics import calculate_results
        from aclad.prospecting import open_campaign, record_candidates
        open_campaign(self.store, 'campaign', 'Objective')
        candidates = [{'id': key, 'name': 'Identical name', 'source_at': NOW,
            'external_ref': result_ref(key, 'apollo', 'prospect')} for key in ('one', 'two')]
        self.store.put('action', 'search', {'status': 'succeeded', 'operation': 'accounts.search',
            'connection_id': 'prospect', 'result': {'candidates': candidates}}, None)
        record_candidates(self.store, 'campaign', 'account', candidates, 'search')
        self.assertEqual(calculate_results(self.store).searched_accounts, 2)
        self.assertEqual(calculate_results(self.store).account_sources_checked, 0)

    def test_unrelated_send_proof_and_cross_campaign_reply_do_not_count(self):
        from aclad.result_metrics import calculate_results
        seed_results(self.store)
        action = self.store.get('action', 'sent-0-0')
        self.store.put('action', action.id, dict(action.data, payload={
            'message_id': 'another-message', 'message': action.data['payload']['message']}), action.revision)
        self.assertEqual(calculate_results(self.store).sent_messages, 19)

    def test_legacy_subset_is_unverified_instead_of_inventing_population(self):
        from aclad.result_metrics import calculate_results
        from aclad.prospecting import open_campaign
        open_campaign(self.store, 'campaign', 'Objective')
        candidates = [{'id': key, 'external_ref': result_ref(key, 'apollo', 'prospect')} for key in ('one', 'two')]
        self.store.put('action', 'legacy-search', {'status': 'succeeded', 'operation': 'accounts.search',
            'connection_id': 'prospect', 'result': {'candidates': candidates, 'complete': True}}, None)
        for candidate in candidates:
            self.store.put('account', candidate['id'], dict(candidate, campaign_id='campaign'), None)
        self.store.record_event(Event('legacy', 'campaign', 'candidates_recorded', NOW,
            {'kind': 'account', 'evidence_id': 'legacy-search', 'count': 1}))
        metrics = calculate_results(self.store)
        self.assertEqual(metrics.searched_accounts, 0)
        self.assertEqual((metrics.account_sources_checked, metrics.account_sources_total), (0, 1))
