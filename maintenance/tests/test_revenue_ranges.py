"""The reviewed monetary contract must reach provider search and final selection."""
from dataclasses import asdict

from aclad.accounts import select_accounts
from aclad import icp_analysis
from aclad.icps import propose_icp, approve_icp, bind_icp
from aclad.models import Capability, GateError
from aclad.prospecting import prepare_prospecting
from tests.support import StateTest


class RevenueRangesTests(StateTest):
    def predicate(self, operator='between', value=None):
        return {'field': 'annual_revenue', 'operator': operator, 'basis': 'hypothesis',
                'value': value or {'lower': '100', 'upper': '200', 'currency': 'BRL'}}

    def test_amount_without_year_preserves_source_without_inventing_date(self):
        observed = {'amount': '125.00', 'currency': 'BRL', 'source': 'crm',
                    'collected_at': '2026-10-26T12:00:00Z', 'estimated': True}
        self.assertEqual(icp_analysis.money(observed), observed)
        self.assertEqual(icp_analysis.money({'amount': '1', 'currency': 'USD', 'year': 2025}),
                         {'amount': '1', 'currency': 'USD', 'year': 2025})

    def test_ranges_are_contained_outside_or_explicitly_unknown(self):
        self.assertTrue(hasattr(icp_analysis, 'revenue_match'), 'Shared revenue_match contract is missing')
        predicate = self.predicate()
        for observed, expected in [
            ({'lower': '120', 'upper': '180', 'currency': 'BRL', 'estimated': True}, 'match'),
            ({'lower': '210', 'upper': '250', 'currency': 'BRL'}, 'no_match'),
            ({'lower': '80', 'upper': '120', 'currency': 'BRL'}, 'unknown'),
            ({'amount': '150', 'currency': 'USD'}, 'unknown'),
            ({'amount': '150'}, 'unknown'), (None, 'unknown')]:
            with self.subTest(observed=observed):
                self.assertEqual(icp_analysis.revenue_match(observed, predicate), expected)

    def test_bound_and_explicit_year_do_not_invent_midpoint_or_exchange_rate(self):
        self.assertTrue(hasattr(icp_analysis, 'revenue_match'), 'Shared revenue_match contract is missing')
        predicate = self.predicate('gte', {'amount': '100', 'currency': 'BRL', 'year': 2025})
        self.assertEqual(icp_analysis.revenue_match({'lower': '80', 'upper': '200', 'currency': 'BRL', 'year': 2025}, predicate), 'unknown')
        self.assertEqual(icp_analysis.revenue_match({'amount': '150', 'currency': 'BRL'}, predicate), 'unknown')
        self.assertEqual(icp_analysis.revenue_match({'amount': '150', 'currency': 'BRL', 'year': 2024}, predicate), 'unknown')

    def test_invalid_values_ranges_and_provenance_are_rejected(self):
        for value in ({'amount': 10, 'currency': 'BRL'}, {'lower': '200', 'upper': '100', 'currency': 'BRL'},
                      {'amount': '10', 'lower': '10', 'upper': '20', 'currency': 'BRL'},
                      {'amount': '10', 'currency': 'BRL', 'year': True},
                      {'amount': '10', 'currency': 'BRL', 'estimated': 'yes'},
                      {'amount': '10', 'currency': 'BRL', 'collected_at': 'today'}):
            with self.subTest(value=value), self.assertRaises(GateError):
                icp_analysis.money(value)

    def campaign(self, predicate):
        icp = propose_icp(self.store, [predicate], [], [], True)
        approved = approve_icp(self.store, icp.id, icp.revision, 'seller')
        self.store.put('campaign', 'c', {}, None)
        return bind_icp(self.store, 'c', approved.id, approved.revision)

    def test_final_selection_revalidates_approved_revenue_instead_of_trusting_eligible_flag(self):
        campaign = self.campaign(self.predicate('gte', {'amount': '100', 'currency': 'BRL', 'year': 2025}))
        self.store.put('account', 'outside', {'campaign_id': 'c', 'eligibility': 'eligible',
            'annual_revenue': {'amount': '50', 'currency': 'BRL', 'year': 2025}}, None)
        with self.assertRaises(GateError) as caught:
            select_accounts(self.store, 'c', ['outside'])
        self.assertEqual(caught.exception.code, 'account_outside_icp')
        self.assertFalse(self.store.get('account', 'outside').data.get('selected', False))

    def test_unknown_overlap_requires_review_and_contained_range_can_be_selected(self):
        self.campaign(self.predicate())
        for id, revenue in [('partial', {'lower': '80', 'upper': '120', 'currency': 'BRL'}),
                            ('inside', {'lower': '110', 'upper': '190', 'currency': 'BRL'})]:
            self.store.put('account', id, {'campaign_id': 'c', 'eligibility': 'eligible', 'annual_revenue': revenue}, None)
        with self.assertRaises(GateError) as caught:
            select_accounts(self.store, 'c', ['partial'])
        self.assertEqual(caught.exception.code, 'icp_eligibility_unknown')
        self.assertTrue(select_accounts(self.store, 'c', ['inside'])[0].data['selected'])

    def test_provider_search_receives_the_exact_approved_structured_contract(self):
        campaign = self.campaign(self.predicate())
        cap = Capability('accounts.search', 'search', 'data', 'visible', 'authenticated', 'allowed', 'verified', 'free')
        proposal = prepare_prospecting(self.store, 'c', 'accounts.search', ['c'], cap, {})
        self.assertEqual(proposal.payload['filters']['criteria'], campaign.data['icp_snapshot']['criteria'])
        self.assertEqual(proposal.payload['filters']['exclusions'], [])

    def test_analysis_reports_yearless_ranges_without_summing_midpoints(self):
        from aclad.models import ExternalRef
        seller = ExternalRef('crm', 'tenant', 'crm', 'seller')
        rows = [{'ref': asdict(ExternalRef('crm', 'tenant', 'crm', id)), 'is_customer': True,
                 'owner_ref': asdict(seller), 'annual_revenue': value} for id, value in
                [('a', {'amount': '100', 'currency': 'BRL'}),
                 ('b', {'lower': '100', 'upper': '200', 'currency': 'BRL', 'estimated': True})]]
        analysis = icp_analysis.analyze_icps(rows, seller, {'scope': 'whole_company', 'complete': True,
                    'filters': [], 'as_of': '2026-10-26T12:00:00Z'})
        revenue = analysis['partner_customers']['dimensions']['annual_revenue']
        self.assertEqual(revenue['known_count'], 2)
        group = revenue['groups'][0]
        self.assertNotIn('year', group)
        self.assertEqual(group['range_count'], 1)
        self.assertNotIn('total', group)

    def test_between_operator_is_specific_to_structured_revenue_ranges(self):
        with self.assertRaises(GateError) as caught:
            propose_icp(self.store, [{'field': 'employees', 'operator': 'between', 'value': 10, 'basis': 'hypothesis'}], [], [], True)
        self.assertEqual(caught.exception.code, 'invalid_icp_predicate')
