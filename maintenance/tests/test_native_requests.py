"""Native arguments remain tied to the reviewed canonical proposal."""
from copy import deepcopy
from dataclasses import asdict, replace
import os
import unittest
from unittest.mock import patch

from aclad.approvals import approve, create_proposal, prepare_action
from aclad.hooks import handle_hook
from aclad.messages import propose_draft
from aclad.models import Capability, GateError, now_utc
import tests.test_messages as baseline
try:
    from aclad.native_requests import bind_native_request, validate_native_request
except ImportError:
    bind_native_request = validate_native_request = None


class NativeRequestTests(unittest.TestCase):
    setUp = baseline.MessagesTests.setUp
    tearDown = baseline.MessagesTests.tearDown

    def draft(self):
        return propose_draft(self.store, 'c1', self.message)

    def args(self):
        return {'to': [{'email': 'buyer@example.com', 'name': 'Buyer'}],
                'subject': self.message['subject'], 'text_content': self.message['body']}

    def mapping(self):
        return {'message.to':'to','message.cc':'cc','message.bcc':'bcc',
                'message.subject':'subject','message.body':'text_content'}

    def bind(self, proposal=None, args=None, mapping=None):
        self.assertIsNotNone(bind_native_request, 'Native proposal mapping is missing')
        p = proposal or self.draft()
        return bind_native_request(self.store, p.id, p.revision,
            args if args is not None else self.args(), mapping if mapping is not None else self.mapping())

    def test_binding_changes_digest_before_approval_and_real_native_input_matches_hook(self):
        original = self.draft()
        bound = self.bind(original)
        self.assertEqual(bound.revision, original.revision + 1)
        self.assertNotEqual(bound.digest, original.digest)
        self.assertEqual(bound.payload['native_request']['input'], self.args())
        approve(self.store, bound.id, bound.revision, bound.digest, 'seller', now_utc())
        cap = Capability(**self.store.get('connection', 'email.create_draft').data['capability'])
        intent = prepare_action(self.store, bound.id, cap, {}, now_utc())
        event={'session_id':'s','cwd':self.temp.name,'hook_event_name':'PreToolUse',
               'tool_name':cap.tool_name,'tool_input':self.args()}
        env={'ACLAD_STATE_DIR':self.temp.name,'ACLAD_PARTNER_ID':'p',
             'ACLAD_SELLER_ID':'s','ACLAD_INSTANCE_ID':'i'}
        with patch.dict(os.environ,env):
            self.assertEqual(handle_hook('codex','PreToolUse',event),{})
            changed=deepcopy(event); changed['tool_input']['text_content']='Unreviewed body'
            self.assertEqual(handle_hook('codex','PreToolUse',changed)['hookSpecificOutput']['permissionDecision'],'deny')
        self.assertEqual(self.store.get('action',intent.action_id).data['payload']['native_request']['input'],self.args())

    def test_changed_body_recipient_and_extra_hidden_recipient_never_bind(self):
        for args in (dict(self.args(),text_content='Changed'),
                     dict(self.args(),to=[{'email':'other@example.com'}]),
                     dict(self.args(),bcc=['hidden@example.com']),
                     dict(self.args(),html_content='<p>Hidden content</p>'),
                     dict(self.args(),reply_to='unexpected@example.com')):
            with self.subTest(args=args),self.assertRaises(GateError):self.bind(args=args)

    def test_mapping_cannot_omit_approved_recipients_or_use_a_wrong_source(self):
        for changed in ({k:v for k,v in self.mapping().items() if k!='message.to'},
                        dict(self.mapping(), **{'message.to':'other'})):
            with self.subTest(mapping=changed),self.assertRaises(GateError):self.bind(mapping=changed)

    def test_existing_approval_must_be_reissued_for_native_binding(self):
        p=self.draft(); approve(self.store,p.id,p.revision,p.digest,'seller',now_utc())
        bound=self.bind(p)
        self.assertEqual(bound.status,'proposed')
        self.assertNotIn('approval',self.store.get('proposal',p.id).data)
        with self.assertRaises(GateError):approve(self.store,p.id,p.revision,p.digest,'seller',now_utc())

    def test_started_or_unknown_action_cannot_be_rebound(self):
        for state in ('in_flight','unknown','succeeded'):
            p=self.draft()
            self.store.put('action','action-'+p.id,{'proposal_id':p.id,'status':state},None)
            with self.subTest(state=state),self.assertRaises(GateError):self.bind(p)

    def test_stored_input_tamper_and_tool_change_fail_validation(self):
        bound=self.bind()
        tampered=deepcopy(bound.payload)
        tampered['native_request']['input']['to']=[{'email':'other@example.com'}]
        with self.assertRaises(GateError):validate_native_request(self.store,replace(bound,payload=tampered))
        row=self.store.get('connection','email.create_draft')
        cap=dict(row.data['capability'],tool_name='different.tool')
        self.store.put('connection',row.id,dict(row.data,capability=cap),row.revision)
        with self.assertRaises(GateError):validate_native_request(self.store,bound)

    def test_send_can_only_reference_reviewed_draft_not_compose_new_mail(self):
        payload={'draft_ref':asdict(self.draft_ref),'message':self.message}
        p=create_proposal(self.store,'email.send','mail1',['x1'],payload)
        bound=self.bind(p,{'draft_id':'draft1'},{'draft_ref.object_id':'draft_id'})
        self.assertEqual(bound.payload['native_request']['input']['draft_id'],'draft1')
        with self.assertRaises(GateError):self.bind(p,{'draft_id':'other'},{'draft_ref.object_id':'draft_id'})
        with self.assertRaises(GateError):self.bind(p,{'draft_id':'draft1','body':'new'},{'draft_ref.object_id':'draft_id'})

    def test_generic_mapping_requires_exact_canonical_values_and_complete_coverage(self):
        self.store.put('connection','search',{'account_identity':'seller',
            'capability':asdict(Capability('accounts.search','search.tool','data','visible',
                'authenticated','allowed','verified','free'))},None)
        p=create_proposal(self.store,'accounts.search','data',['c1'],{'query':'finance','limit':30})
        bound=self.bind(p,{'search':'finance','max_results':30},{'query':'search','limit':'max_results'})
        validate_native_request(self.store,bound)
        for args,mapping in (({'search':'other'},{'query':'search'}),
                ({'search':'finance','extra':'not approved'},{'query':'search'}),
                ({'search':'finance'},{})):
            with self.subTest(args=args),self.assertRaises(GateError):self.bind(p,args,mapping)

    def test_selected_external_identity_is_a_bound_source_and_changes_invalidate_it(self):
        self.store.put('connection','enrich',{'account_identity':'seller',
            'capability':asdict(Capability('companies.enrich','enrich.tool','data','visible',
                'authenticated','allowed','verified','free'))},None)
        row=self.store.get('account','a1')
        ref={'provider':'data','tenant_id':'tenant','connection_id':'data','object_id':'company-remote'}
        self.store.put('account',row.id,dict(row.data,external_ref=ref),row.revision)
        p=create_proposal(self.store,'companies.enrich','data',['a1'],{'campaign_id':'c1'})
        bound=self.bind(p,{'company_id':'company-remote'},
            {'items.a1.external_ref.object_id':'company_id'})
        validate_native_request(self.store,bound)
        row=self.store.get('account','a1')
        self.store.put('account',row.id,dict(row.data,external_ref=dict(ref,object_id='changed')),row.revision)
        with self.assertRaises(GateError):validate_native_request(self.store,bound)


    def test_native_hook_rejects_connection_revoked_after_intent(self):
        p=self.bind(); approve(self.store,p.id,p.revision,p.digest,'seller',now_utc())
        row=self.store.get('connection','email.create_draft')
        cap=Capability(**row.data['capability'])
        prepare_action(self.store,p.id,cap,{},now_utc())
        self.store.put('connection',row.id,dict(row.data,capability=asdict(replace(cap,permission='denied',verification='failed'))),row.revision)
        event={'session_id':'s','cwd':self.temp.name,'hook_event_name':'PreToolUse',
               'tool_name':cap.tool_name,'tool_input':self.args()}
        env={'ACLAD_STATE_DIR':self.temp.name,'ACLAD_PARTNER_ID':'p',
             'ACLAD_SELLER_ID':'s','ACLAD_INSTANCE_ID':'i'}
        with patch.dict(os.environ,env):
            result=handle_hook('codex','PreToolUse',event)
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')


    def native_event(self):
        p=self.bind(); approve(self.store,p.id,p.revision,p.digest,'seller',now_utc())
        cap=Capability(**self.store.get('connection','email.create_draft').data['capability'])
        intent=prepare_action(self.store,p.id,cap,{},now_utc())
        event={'session_id':'s','cwd':self.temp.name,'hook_event_name':'PreToolUse',
               'tool_name':cap.tool_name,'tool_input':self.args()}
        env={'ACLAD_STATE_DIR':self.temp.name,'ACLAD_PARTNER_ID':'p',
             'ACLAD_SELLER_ID':'s','ACLAD_INSTANCE_ID':'i'}
        return intent,event,env

    def test_bound_native_action_can_be_dispatched_only_once_before_result(self):
        intent,event,env=self.native_event()
        with patch.dict(os.environ,env):
            first=handle_hook('codex','PreToolUse',event)
            second=handle_hook('codex','PreToolUse',event)
        self.assertEqual(first,{})
        self.assertEqual(second['hookSpecificOutput']['permissionDecision'],'deny')
        row=self.store.get('action',intent.action_id)
        self.assertEqual(row.data['status'],'in_flight')
        self.assertTrue(row.data['native_dispatched_at'])

    def test_mismatched_native_input_does_not_consume_original_dispatch(self):
        _,event,env=self.native_event()
        changed=deepcopy(event); changed['tool_input']['subject']='Unapproved subject'
        with patch.dict(os.environ,env):
            denied=handle_hook('claude','PreToolUse',changed)
            valid=handle_hook('claude','PreToolUse',event)
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'],'deny')
        self.assertEqual(valid,{})

class NativeCrmTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from aclad.models import Scope, ExternalRef
        from aclad.store import Store
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name, Scope('p','s','i'))
        self.addCleanup(self.store.close)
        self.owner=ExternalRef('crm','tenant','crm1','seller')
        self.cap=Capability('crm.write','crm.write','crm1','visible','authenticated','allowed','verified','free')
        self.store.put('connection','crm',{'account_identity':'seller','capability':asdict(self.cap)},None)
        self.store.put('campaign','c',{},None)
        self.store.put('account','a',{'selected':True,'campaign_id':'c','crm_status':'verified','owner_ref':asdict(self.owner)},None)
        self.now=now_utc()
        self.preflight={'connection_id':'crm1','checked_at':self.now,'external_revision':'new',
            'ownership_allowed':True,'contact_allowed':True,'opportunity_allowed':True}

    def proposal(self):
        from aclad.crm import propose_crm
        p=propose_crm(self.store,'c',[{'local_id':'a','entity':'account','external_ref':None,
            'before':{},'after':{'name':'Acme'},'links':{},'provenance':[]}],self.owner)
        approve(self.store,p.id,p.revision,p.digest,'seller',self.now)
        return p

    def test_native_crm_child_is_bound_before_parent_approved_execution(self):
        from aclad.crm import prepare_crm_item
        p=self.proposal()
        intent=prepare_crm_item(self.store,p.id,p.payload['changes'][0]['change_id'],self.cap,
            self.preflight,self.now,native_input={'fields':{'name':'Acme','owner':'seller'}},
            field_mapping={'change.after.name':'fields.name','owner_ref.object_id':'fields.owner'})
        self.assertEqual(intent.payload['native_request']['input'],{'fields':{'name':'Acme','owner':'seller'}})
        child=self.store.get('proposal',self.store.get('action',intent.action_id).data['proposal_id'])
        self.assertEqual(child.data['status'],'approved')
        self.assertEqual(child.data['approval']['revision'],child.data['revision'])

    def test_native_crm_cannot_omit_approved_fields_or_owner(self):
        from aclad.crm import prepare_crm_item
        for args,mapping in (({'fields':{'name':'Acme'}},{'change.after.name':'fields.name'}),
                             ({'fields':{'owner':'seller'}},{'owner_ref.object_id':'fields.owner'})):
            p=self.proposal()
            with self.subTest(mapping=mapping),self.assertRaises(GateError):
                prepare_crm_item(self.store,p.id,p.payload['changes'][0]['change_id'],self.cap,
                    self.preflight,self.now,native_input=args,field_mapping=mapping)
        self.assertFalse(self.store.list('action'))
