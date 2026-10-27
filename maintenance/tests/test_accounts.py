from aclad.accounts import match_account, eligibility, select_accounts
from aclad.models import ExternalRef, GateError
from tests.support import StateTest

class AccountTests(StateTest):
    def setUp(self):
        super().setUp()
        self.seller = ExternalRef('crm','tenant','crm-1','seller-a')
        self.store.put('campaign','c',{'status':'active','icp_id':'i','icp_revision':1},None)
        self.store.put('account','a',{'campaign_id':'c','selected':False,'eligibility':'eligible'},None)
    def test_domain_shared_by_two_companies_is_uncertain(self):
        result = match_account({'domain':'group.example'},
            [{'id':'a','domain':'group.example','tax_id':'1'},
             {'id':'b','domain':'group.example','tax_id':'2'}])
        self.assertEqual(result['status'],'uncertain')
    def test_tax_id_is_stronger_than_domain(self):
        result = match_account({'tax_id':'2','domain':'group.example'},
            [{'id':'a','domain':'group.example','tax_id':'1'},
             {'id':'b','domain':'group.example','tax_id':'2'}])
        self.assertEqual(result['match']['id'],'b')
    def test_name_match_requires_review(self):
        self.assertEqual(match_account({'name':'Acme'},[{'name':'Acme','id':'a'}])['status'],'uncertain')
    def test_own_nurturing_is_eligible_without_reassignment(self):
        from dataclasses import asdict
        result = eligibility({'owner_ref':asdict(self.seller),'nurturing':True,'crm_status':'verified'},self.seller,{})
        self.assertEqual(result['status'],'eligible')
        self.assertFalse(result['owner_changed'])
    def test_other_owner_active_opportunity_and_unknown_access_are_not_free(self):
        for data in ({}, {'crm_status':'verified','owner_ref':{'object_id':'other'}},{'open_opportunity':True},
                     {'crm_status':'unreachable'},{'do_not_contact':True}):
            self.assertNotEqual(eligibility(data,self.seller,{})['status'],'eligible')
    def test_selection_is_persisted_before_crm(self):
        selected = select_accounts(self.store,'c',['a'])
        self.assertTrue(selected[0].data['selected'])
        self.assertNotIn('external_ref', selected[0].data)
        self.assertGreater(self.store.snapshot().event_sequence,0)
    def test_cross_campaign_selection_has_no_partial_changes(self):
        self.store.put('account','other',{'campaign_id':'other','eligibility':'eligible'},None)
        with self.assertRaises(GateError):
            select_accounts(self.store,'c',['a','other'])
        self.assertFalse(self.store.get('account','a').data['selected'])
    def test_deselection_invalidates_proposals_involving_removed_item(self):
        select_accounts(self.store,'c',['a'])
        self.store.put('proposal','p',{'item_ids':['a'],'status':'approved'},None)
        select_accounts(self.store,'c',[])
        self.assertFalse(self.store.get('account','a').data['selected'])
        self.assertEqual(self.store.get('proposal','p').data['status'],'invalidated')


class IcpObservationTests(StateTest):
    """Supported dimensions must survive the pre-enrichment selection journey."""
    def setUp(self):
        super().setUp()
        self.seller = ExternalRef('crm', 'tenant', 'crm', 'seller')
        self.case = 0

    def campaign(self, field, operator, value):
        from aclad.icps import propose_icp, approve_icp, bind_icp
        self.case += 1
        id = 'observations-' + str(self.case)
        icp = propose_icp(self.store, [{'field': field, 'operator': operator,
            'value': value, 'basis': 'hypothesis'}], [], [], True)
        icp = approve_icp(self.store, icp.id, icp.revision, 'seller')
        self.store.put('campaign', id, {}, None)
        return bind_icp(self.store, id, icp.id, icp.revision)

    def observe(self, campaign, field, value, source='search'):
        from dataclasses import asdict
        from aclad.prospecting import record_candidates, check_account
        from tests.support import NOW
        id = campaign.id + '-account'
        candidate = {'id': id, 'name': 'Synthetic', 'source_at': NOW,
            'external_ref': asdict(ExternalRef('data', 'tenant', 'data', id))}
        if source == 'search':
            candidate[field] = value
        self.store.put('action', id + '-search', {'operation': 'accounts.search',
            'status': 'succeeded', 'connection_id': 'data', 'result': {'candidates': [candidate]}}, None)
        record_candidates(self.store, campaign.id, 'account', [candidate], id + '-search')
        observation = {'account_id': id, 'owner_ref': asdict(self.seller), 'nurturing': True}
        if source == 'crm':
            observation[field] = value
        self.store.put('action', id + '-crm', {'operation': 'crm.read',
            'status': 'succeeded', 'connection_id': 'crm',
            'result': {'complete': True, 'observations': [observation]}}, None)
        return check_account(self.store, campaign.id, id, observation, id + '-crm', self.seller, {})

    def test_search_preserves_solutions_and_subindustry_before_selection(self):
        for field, value in [('solutions', ['ERP']), ('subindustry', 'manufacturing')]:
            with self.subTest(field=field):
                campaign = self.campaign(field, 'in', value if isinstance(value, list) else [value])
                account = self.observe(campaign, field, value)
                self.assertEqual(account.data.get(field), value)
                self.assertEqual(account.data['eligibility'], 'eligible')
                self.assertTrue(select_accounts(self.store, campaign.id, [account.id])[0].data['selected'])

    def test_crm_preserves_solutions_and_subindustry_before_selection(self):
        for field, value in [('solutions', ['ERP']), ('subindustry', 'manufacturing')]:
            with self.subTest(field=field):
                campaign = self.campaign(field, 'in', value if isinstance(value, list) else [value])
                account = self.observe(campaign, field, value, 'crm')
                self.assertEqual(account.data.get(field), value)
                self.assertEqual(account.data['eligibility'], 'eligible')
                self.assertTrue(select_accounts(self.store, campaign.id, [account.id])[0].data['selected'])

    def test_invalid_categorical_observations_cannot_satisfy_negative_predicate(self):
        for source in ('search', 'crm'):
            for value in ([], [True], {'country': 'BR'}, '', '  ', True):
                with self.subTest(source=source, value=value):
                    campaign = self.campaign('country', 'not_in', ['AR'])
                    account = self.observe(campaign, 'country', value, source)
                    self.assertEqual(account.data['eligibility'], 'needs_review')
                    with self.assertRaises(GateError):
                        select_accounts(self.store, campaign.id, [account.id])
                    self.assertFalse(self.store.get('account', account.id).data.get('selected', False))

    def test_malformed_dimensions_cannot_bypass_final_selection_with_stale_eligibility(self):
        for field, operator, expected, value in [
            ('country', 'not_in', ['AR'], []), ('country', 'not_in', ['AR'], [True]),
            ('country', 'not_in', ['AR'], {'name': 'BR'}),
            ('solutions', 'not_in', ['CRM'], []), ('solutions', 'not_in', ['CRM'], [True]),
            ('employees', 'in', [1], True), ('employees', 'not_in', [2], False)]:
            with self.subTest(field=field, value=value):
                campaign = self.campaign(field, operator, expected)
                id = campaign.id + '-stale'
                self.store.put('account', id, {'campaign_id': campaign.id, 'eligibility': 'eligible', field: value}, None)
                with self.assertRaises(GateError) as caught:
                    select_accounts(self.store, campaign.id, [id])
                self.assertEqual(caught.exception.code, 'icp_eligibility_unknown')
                self.assertFalse(self.store.get('account', id).data.get('selected', False))
