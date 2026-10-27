import tempfile
import unittest

from aclad.icps import propose_icp, approve_icp, bind_icp
from aclad.models import GateError, Scope
from aclad.store import Store


class IcpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, Scope('partner-a','seller-a','instance-a'))
        self.criterion = {'field':'industry','operator':'in','value':['manufacturing'],'basis':'hypothesis'}

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def propose(self, criteria=None, exclusions=None, source_ids=None, strategic=True):
        return propose_icp(self.store, [self.criterion] if criteria is None else criteria,
                           [] if exclusions is None else exclusions,
                           [] if source_ids is None else source_ids, strategic)

    def test_strategic_profile_without_history_is_explicit_hypothesis_not_active(self):
        proposed = self.propose()
        self.assertEqual(proposed.data['status'], 'proposed')
        self.assertTrue(proposed.data['strategic'])
        self.assertEqual(proposed.data['criteria'][0]['basis'], 'hypothesis')
        self.store.put('campaign','new',{},None)
        with self.assertRaises(GateError):
            bind_icp(self.store,'new',proposed.id,proposed.revision)

    def test_unsupported_evidence_requires_actual_private_source(self):
        criterion = dict(self.criterion,basis='evidence')
        with self.assertRaises(GateError):
            self.propose([criterion], strategic=False)
        with self.assertRaises(GateError):
            self.propose([criterion], source_ids=['missing'], strategic=False)
        self.store.put('analysis','source-1',{'partner_customers':{'population_count':2}},None)
        profile = self.propose([criterion], source_ids=['source-1'], strategic=False)
        self.assertEqual(profile.data['source_ids'], ['source-1'])

    def test_approval_requires_exact_content_revision_and_named_seller(self):
        proposed = self.propose()
        with self.assertRaises(GateError):
            approve_icp(self.store, proposed.id, proposed.revision + 1, 'seller-a')
        with self.assertRaises(GateError):
            approve_icp(self.store, proposed.id, proposed.revision, '')
        active = approve_icp(self.store, proposed.id, proposed.revision, 'seller-a')
        self.assertEqual(active.data['status'], 'active')
        self.assertEqual(active.data['approved_by'], 'seller-a')

    def test_new_revision_cannot_retarget_existing_campaign(self):
        proposed = self.propose()
        active = approve_icp(self.store, proposed.id, proposed.revision, 'seller-a')
        self.store.put('campaign','campaign-1',{'status':'active'},None)
        first = bind_icp(self.store,'campaign-1',active.id,active.revision)
        new_data = dict(active.data, status='proposed', criteria=[dict(self.criterion,value=['services'])])
        revised = self.store.put('icp',active.id,new_data,active.revision)
        newer = approve_icp(self.store,revised.id,revised.revision,'seller-a')
        campaign = self.store.get('campaign','campaign-1')
        self.assertEqual(campaign.data['icp_revision'], first.data['icp_revision'])
        self.assertEqual(campaign.data['icp_snapshot']['criteria'][0]['value'], ['manufacturing'])
        self.assertIn(str(active.revision), newer.data['approved_versions'])

    def test_rebinding_existing_campaign_to_other_version_requires_new_campaign(self):
        a = self.propose()
        a = approve_icp(self.store,a.id,a.revision,'seller-a')
        b = self.propose([dict(self.criterion,value=['services'])])
        b = approve_icp(self.store,b.id,b.revision,'seller-a')
        self.store.put('campaign','campaign-1',{},None)
        original = bind_icp(self.store,'campaign-1',a.id,a.revision)
        self.assertEqual(bind_icp(self.store,'campaign-1',a.id,a.revision).revision,original.revision)
        with self.assertRaises(GateError):
            bind_icp(self.store,'campaign-1',b.id,b.revision)

    def test_revenue_requires_decimal_currency_and_year_and_known_fields(self):
        valid = {'field':'annual_revenue','operator':'gte','basis':'hypothesis',
                 'value':{'amount':'1000000.50','currency':'BRL','year':2025}}
        self.propose([valid])
        for invalid in (dict(valid,value={'amount':'10'}),
                        dict(valid,value={'amount':10.1,'currency':'BRL','year':2025}),
                        dict(valid,field='deal_value'),dict(valid,operator='exec'),
                        dict(valid,basis='fact'),dict(valid,unexpected='command')):
            with self.subTest(invalid=invalid), self.assertRaises(GateError):
                self.propose([invalid])

    def test_partner_exclusions_survive_personal_divergence_and_binding(self):
        self.store.put('profile','current',{'partner':{'industries':['manufacturing']},
            'seller':{'territory':['BR']},'icp':{'exclusions':['Do not contact public agencies']}},None)
        proposed = self.propose([{'field':'country','operator':'in','value':['US'],'basis':'hypothesis'}])
        self.assertEqual(proposed.data['partner_exclusions'], ['Do not contact public agencies'])
        self.assertTrue(proposed.data['divergences'])
        active = approve_icp(self.store,proposed.id,proposed.revision,'seller-a')
        self.store.put('campaign','campaign-1',{},None)
        campaign = bind_icp(self.store,'campaign-1',active.id,active.revision)
        self.assertEqual(campaign.data['icp_snapshot']['partner_exclusions'], ['Do not contact public agencies'])

    def test_no_empty_profile_or_missing_campaign_is_silently_accepted(self):
        with self.assertRaises(GateError):
            self.propose(criteria=[])
        proposed = self.propose()
        active = approve_icp(self.store,proposed.id,proposed.revision,'seller-a')
        with self.assertRaises(GateError):
            bind_icp(self.store,'missing',active.id,active.revision)

    def test_malformed_predicate_enums_are_domain_errors(self):
        for changes in ({'operator':[]}, {'basis':{}}, {'field':['country']}):
            with self.subTest(changes=changes), self.assertRaises(GateError):
                self.propose([dict(self.criterion, **changes)])

    def test_changed_source_cannot_support_stale_icp_approval(self):
        source = self.store.put('analysis','analysis-a',{},None)
        proposed = self.propose([dict(self.criterion,basis='evidence')],
                                source_ids=['analysis-a'],strategic=False)
        self.store.put('analysis','analysis-a',{'new_evidence':True},source.revision)
        with self.assertRaises(GateError):
            approve_icp(self.store,proposed.id,proposed.revision,'seller-a')

    def test_edited_revision_cannot_claim_unprovided_evidence(self):
        proposed = self.propose()
        edited = self.store.put('icp',proposed.id,
            dict(proposed.data,criteria=[dict(self.criterion,basis='evidence')]),proposed.revision)
        with self.assertRaises(GateError):
            approve_icp(self.store,edited.id,edited.revision,'seller-a')
