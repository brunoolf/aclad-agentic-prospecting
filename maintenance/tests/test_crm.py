from dataclasses import asdict
from aclad.crm import propose_crm, reconcile_crm, prepare_crm_item, record_crm_item
from aclad.approvals import approve
from aclad.models import ExternalRef, Capability, ToolResult, GateError
from tests.support import StateTest, NOW

class CrmTests(StateTest):
    def setUp(self):
        super().setUp()
        self.owner = ExternalRef('crm','tenant','crm-1','seller-a')
        self.cap = Capability('crm.write','crm_write','crm-1','visible','authenticated','allowed','verified','free')
        self.store.put('connection','crm-1',{'capability':asdict(self.cap),'account_identity':'seller-a'},None)
        self.store.put('campaign','c',{'status':'active'},None)
        for id in ('a','b'):
            self.store.put('account',id,{'selected':True,'campaign_id':'c','crm_status':'verified','owner_ref':asdict(self.owner)},None)
        self.changes = [{'local_id':id,'entity':'account','external_ref':None,'before':{},'after':{'name':id},'links':{},'provenance':[]} for id in ('a','b')]
        self.preflight = {'checked_at':NOW,'connection_id':'crm-1','external_revision':'new','ownership_allowed':True,'contact_allowed':True,'opportunity_allowed':True}
    def reviewed(self):
        proposal = propose_crm(self.store,'c',self.changes,self.owner)
        approve(self.store,proposal.id,proposal.revision,proposal.digest,'seller-a',NOW)
        return proposal
    def test_unresolved_owner_prevents_proposal(self):
        with self.assertRaises(GateError) as caught:
            propose_crm(self.store,'c',self.changes,ExternalRef('crm','tenant','crm-1','unknown'))
        self.assertEqual(caught.exception.code,'owner_unresolved')
    def test_preview_preserves_old_new_and_owner(self):
        proposal = propose_crm(self.store,'c',self.changes,self.owner)
        self.assertEqual(proposal.payload['owner_ref'],asdict(self.owner))
        self.assertEqual(proposal.payload['changes'][0]['before'],{})
        self.assertEqual(proposal.payload['changes'][0]['after'],{'name':'a'})
    def test_item_execution_requires_batch_approval(self):
        proposal = propose_crm(self.store,'c',self.changes,self.owner)
        with self.assertRaises(GateError):
            prepare_crm_item(self.store,proposal.id,proposal.payload['changes'][0]['change_id'],self.cap,self.preflight,NOW)
    def test_partial_batch_keeps_success_and_unknown_visible(self):
        proposal = self.reviewed()
        first = prepare_crm_item(self.store,proposal.id,proposal.payload['changes'][0]['change_id'],self.cap,self.preflight,NOW)
        record_crm_item(self.store,ToolResult(first.action_id,'succeeded',[ExternalRef('crm','tenant','crm-1','remote-a')],{}))
        second = prepare_crm_item(self.store,proposal.id,proposal.payload['changes'][1]['change_id'],self.cap,self.preflight,NOW)
        record_crm_item(self.store,ToolResult(second.action_id,'unknown',[],{}))
        self.assertEqual(self.store.get('account','a').data['crm_status'],'confirmed')
        self.assertNotEqual(self.store.get('account','b').data['crm_status'],'confirmed')
        self.assertEqual(self.store.get('action',second.action_id).data['status'],'unknown')
    def test_unknown_create_is_reconciled_without_new_intent(self):
        proposal = self.reviewed()
        change_id = proposal.payload['changes'][0]['change_id']
        intent = prepare_crm_item(self.store,proposal.id,change_id,self.cap,self.preflight,NOW)
        record_crm_item(self.store,ToolResult(intent.action_id,'unknown',[],{}))
        result = reconcile_crm(self.store,intent.action_id,[{'complete':True,'local_id':'a',
            'external_ref':asdict(ExternalRef('crm','tenant','crm-1','remote-a')),
            'operation_id':intent.payload['operation_id'],'fields':{'name':'a'},'links':{},
            'owner_ref':asdict(self.owner),'evidence':'verified CRM correlation lookup'}])
        self.assertEqual(result.data['status'],'succeeded')
        self.assertEqual(self.store.get('account','a').data['crm_external_ref']['object_id'],'remote-a')
        with self.assertRaises(GateError):
            prepare_crm_item(self.store,proposal.id,change_id,self.cap,self.preflight,NOW)
    def test_partial_lookup_cannot_resolve_unknown_effect(self):
        proposal = self.reviewed()
        intent = prepare_crm_item(self.store,proposal.id,proposal.payload['changes'][0]['change_id'],self.cap,self.preflight,NOW)
        record_crm_item(self.store,ToolResult(intent.action_id,'unknown',[],{}))
        result = reconcile_crm(self.store,intent.action_id,[{'complete':False,'local_id':'a'}])
        self.assertEqual(result.data['status'],'unknown')
    def test_fresh_ownership_change_blocks_approved_item(self):
        proposal = self.reviewed()
        with self.assertRaises(GateError):
            prepare_crm_item(self.store,proposal.id,proposal.payload['changes'][0]['change_id'],self.cap,dict(self.preflight,ownership_allowed=False),NOW)
