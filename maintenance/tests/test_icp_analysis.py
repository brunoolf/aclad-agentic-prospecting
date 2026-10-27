import copy
import json
from pathlib import Path
import unittest

from aclad.icp_analysis import analyze_icps
from aclad.models import ExternalRef, GateError


NOW = '2026-10-22T12:00:00Z'
SELLER = ExternalRef('crm-demo', 'tenant-demo', 'connection-demo', 'seller-a')


class IcpAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.accounts = json.loads((Path(__file__).parent / 'fixtures/icp_accounts.json').read_text())
        self.coverage = {'scope': 'accessible_subset', 'complete': False,
                         'filters': ['current-visible-accounts'], 'as_of': NOW}

    def analyze(self):
        return analyze_icps(self.accounts, SELLER, self.coverage)

    def test_populations_count_enterprises_not_opportunities(self):
        result = self.analyze()
        self.assertEqual(set(result), {'partner_customers', 'seller_customers', 'seller_prospects'})
        self.assertEqual(result['partner_customers']['population_count'], 2)
        self.assertEqual(result['seller_customers']['population_count'], 1)
        self.assertEqual(result['seller_prospects']['population_count'], 1)
        self.assertEqual(result['seller_prospects']['unclassified_count'], 1)
        self.assertEqual(result['seller_prospects']['interpretation'], 'effort_not_success')

    def test_partial_access_never_claims_full_company(self):
        result = self.analyze()
        for profile in result.values():
            self.assertEqual(profile['coverage'], self.coverage)
            self.assertTrue(profile['limitations'])
            self.assertNotIn('confidence', profile)
        self.coverage['filters'].append('later')
        self.assertEqual(result['partner_customers']['coverage']['filters'], ['current-visible-accounts'])

    def test_revenue_uses_exact_decimal_currency_and_year_groups(self):
        dimensions = self.analyze()['partner_customers']['dimensions']
        money = dimensions['annual_revenue']
        self.assertEqual(money['known_count'], 2)
        groups = {(g['currency'], g['year']): g for g in money['groups']}
        self.assertEqual(groups[('BRL', 2025)]['total'], '1000000.50')
        self.assertEqual(groups[('USD', 2026)]['total'], '2500000.25')
        self.assertNotIn('deal_value', dimensions)
        self.assertEqual(self.analyze()['seller_prospects']['dimensions']['annual_revenue']['unknown_count'], 1)

    def test_unknown_dimensions_are_visible_without_filling_from_other_fields(self):
        dimensions = self.analyze()['partner_customers']['dimensions']
        self.assertEqual(dimensions['employees']['known_count'], 1)
        self.assertEqual(dimensions['employees']['unknown_count'], 1)
        self.assertEqual(dimensions['subindustry']['unknown_count'], 2)
        self.assertEqual(dimensions['country']['distribution'], [{'value':'BR','count':1}, {'value':'US','count':1}])

    def test_invalid_fields_are_reported_without_losing_enterprise_count(self):
        self.accounts[0]['employees'] = -1
        self.accounts[1]['employees'] = -1
        self.accounts[2]['annual_revenue']['amount'] = 10.2
        result = self.analyze()['partner_customers']
        self.assertEqual(result['population_count'], 2)
        self.assertEqual(result['dimensions']['employees']['unknown_count'], 2)
        self.assertEqual(result['dimensions']['annual_revenue']['known_count'], 1)
        self.assertTrue(any(e['field'] == 'employees' for e in result['errors']))
        self.assertTrue(any(e['field'] == 'annual_revenue' for e in result['errors']))

    def test_incompatible_years_not_merged_even_with_same_currency(self):
        self.accounts[2]['annual_revenue']['currency'] = 'BRL'
        groups = self.analyze()['partner_customers']['dimensions']['annual_revenue']['groups']
        self.assertEqual({g['year'] for g in groups}, {2025, 2026})

    def test_conflicting_duplicate_status_is_unclassified_not_guessed(self):
        self.accounts[1]['is_customer'] = False
        result = self.analyze()['partner_customers']
        self.assertEqual(result['population_count'], 1)
        self.assertEqual(result['unclassified_count'], 2)
        self.assertTrue(any(e['code'] == 'conflicting_duplicate' for e in result['errors']))

    def test_full_external_identity_prevents_fusing_distinct_accounts(self):
        self.accounts[1] = copy.deepcopy(self.accounts[0])
        self.accounts[1]['ref']['tenant_id'] = 'other-tenant'
        result = self.analyze()['partner_customers']
        self.assertEqual(result['population_count'], 3)

    def test_invalid_ref_is_counted_as_problem_not_a_fabricated_account(self):
        self.accounts.append({'ref': {'object_id':'bad'}, 'is_customer':True})
        result = self.analyze()['partner_customers']
        self.assertEqual(result['population_count'], 2)
        self.assertEqual(result['invalid_record_count'], 1)

    def test_invalid_coverage_or_nonboolean_status_is_rejected_or_reported(self):
        for coverage in ({}, dict(self.coverage, scope='global'),
                         dict(self.coverage, scope=[]), dict(self.coverage, complete='yes')):
            with self.assertRaises(GateError):
                analyze_icps(self.accounts, SELLER, coverage)
        self.accounts[0]['is_customer'] = 'true'
        self.accounts[1]['is_customer'] = 'true'
        result = self.analyze()['partner_customers']
        self.assertEqual(result['population_count'], 1)
        self.assertTrue(any(e['field'] == 'is_customer' for e in result['errors']))
