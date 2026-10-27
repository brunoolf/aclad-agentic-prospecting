from dataclasses import asdict
from aclad.prospecting import confirm_roles, select_contacts, prepare_prospecting, open_campaign, record_candidates, apply_enrichment, check_account
from aclad.models import Capability, ExternalRef, GateError
from tests.support import StateTest, NOW

class ProspectingTests(StateTest):
    def setUp(self):
        super().setUp()
        self.store.put('campaign','c',{'status':'active','icp_id':'i','icp_revision':1},None)
        self.store.put('account','a',{'campaign_id':'c','selected':True},None)
        self.store.put('contact','p',{'campaign_id':'c','account_id':'a','selected':False},None)
        self.cap = Capability('people.reveal_email','reveal','data-1','visible','authenticated','allowed','verified','paid')
        self.limits = {'max_items':5,'max_credits':'5','cost_known':True,'cost_acknowledged':True}
    def test_unselected_contact_cannot_be_revealed(self):
        with self.assertRaises(GateError) as caught:
            prepare_prospecting(self.store,'c','people.reveal_email',['p'],self.cap,self.limits)
        self.assertEqual(caught.exception.code,'selection_required')
        self.assertEqual(self.store.list('proposal'),[])
    def test_reveal_only_selected_contact_ids(self):
        select_contacts(self.store,'c',['p'])
        proposal = prepare_prospecting(self.store,'c','people.reveal_email',['p'],self.cap,self.limits)
        self.assertEqual(proposal.item_ids,['p'])
    def test_role_confirmation_required_before_people_search(self):
        cap = Capability('people.search','search','data-1','visible','authenticated','allowed','verified','free')
        with self.assertRaises(GateError):
            prepare_prospecting(self.store,'c','people.search',['a'],cap,self.limits)
        confirm_roles(self.store,'c','a',[{'title':'CFO','seniority':'executive','max_contacts':2}])
        proposal = prepare_prospecting(self.store,'c','people.search',['a'],cap,self.limits)
        self.assertEqual(proposal.payload['roles'][0]['title'],'CFO')
    def test_coupled_search_and_reveal_does_not_create_proposal(self):
        with self.assertRaises(GateError) as caught:
            prepare_prospecting(self.store,'c','people.search',['a'],self.cap,self.limits)
        self.assertEqual(caught.exception.code,'search_reveal_coupled')
    def test_unknown_cost_without_acknowledged_bound_is_rejected(self):
        select_contacts(self.store,'c',['p'])
        cap = Capability('people.reveal_email','reveal','data-1','visible','authenticated','allowed','verified','unknown')
        with self.assertRaises(GateError):
            prepare_prospecting(self.store,'c','people.reveal_email',['p'],cap,{'max_items':5})
    def test_incidental_email_is_not_revealed_again(self):
        current = self.store.get('contact','p')
        self.store.put('contact','p',dict(current.data,email='seller@example.test'),current.revision)
        select_contacts(self.store,'c',['p'])
        with self.assertRaises(GateError) as caught:
            prepare_prospecting(self.store,'c','people.reveal_email',['p'],self.cap,self.limits)
        self.assertEqual(caught.exception.code,'email_already_available')
    def test_candidate_ingestion_requires_successful_matching_evidence(self):
        with self.assertRaises(GateError):
            record_candidates(self.store,'c','account',[{'id':'other'}],'missing-action')
        self.assertIsNone(self.store.get('account','other'))
    def test_search_result_registers_unselected_candidates(self):
        candidate = {'id':'new','name':'Synthetic','external_ref':asdict(ExternalRef('data','t','data-1','external-1')),'source_at':NOW}
        self.store.put('action','search-1',{'operation':'accounts.search','status':'succeeded','connection_id':'data-1','result':{'candidates':[candidate]}},None)
        rows = record_candidates(self.store,'c','account',[candidate],'search-1')
        self.assertFalse(rows[0].data['selected'])
        self.assertEqual(rows[0].data['eligibility'],'needs_review')
    def test_create_campaign_is_resumable_without_silent_overwrite(self):
        row = open_campaign(self.store,'new','nurturing')
        self.assertEqual(open_campaign(self.store,'new','nurturing'),row)
        with self.assertRaises(GateError):
            open_campaign(self.store,'new','different objective')

    def test_enrichment_applies_only_the_persisted_selected_result(self):
        item = {'id':'a','fields':{'employees':100},'provenance':{'source':'data-1','collected_at':NOW,'basis':'licensed'}}
        self.store.put('action','enrich-1',{'operation':'companies.enrich','status':'succeeded','connection_id':'data-1','payload':{'campaign_id':'c','item_ids':['a']},'item_ids':['a'],'result':{'items':[item]}},None)
        records = apply_enrichment(self.store,'enrich-1',[item])
        self.assertEqual(records[0].data['employees'],100)
        self.assertEqual(records[0].data['provenance']['employees']['source'],'data-1')
        with self.assertRaises(GateError):
            apply_enrichment(self.store,'enrich-1',[dict(item,fields={'employees':999})])
    def test_crm_check_persists_eligibility_from_complete_evidence(self):
        seller = ExternalRef('crm','t','crm-1','seller-a')
        observation = {'account_id':'a','owner_ref':asdict(seller),'nurturing':True}
        self.store.put('action','check-1',{'operation':'crm.read','status':'succeeded','connection_id':'crm-1','result':{'complete':True,'observations':[observation]}},None)
        row = check_account(self.store,'c','a',observation,'check-1',seller,{})
        self.assertEqual(row.data['eligibility'],'eligible')
        with self.assertRaises(GateError):
            check_account(self.store,'c','a',dict(observation,do_not_contact=True),'check-1',seller,{})

    def test_rechecking_crm_does_not_lose_confirmed_sync_status(self):
        from dataclasses import asdict
        seller = ExternalRef('crm','t','crm-1','seller-a')
        old = self.store.get('account','a')
        self.store.put('account','a',dict(old.data,crm_status='confirmed',owner_ref=asdict(seller)),old.revision)
        observation = {'account_id':'a','owner_ref':asdict(seller)}
        self.store.put('action','check-2',{'operation':'crm.read','status':'succeeded','connection_id':'crm-1','result':{'complete':True,'observations':[observation]}},None)
        row = check_account(self.store,'c','a',observation,'check-2',seller,{})
        self.assertEqual(row.data['crm_status'],'confirmed')
        self.assertEqual(row.data['eligibility'],'eligible')
