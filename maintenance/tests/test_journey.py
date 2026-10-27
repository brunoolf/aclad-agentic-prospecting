"""Complete synthetic chat-host bridge journey; no live connector or hook needed."""
from dataclasses import asdict
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from aclad.accounts import select_accounts
from aclad.approvals import approve, create_proposal, prepare_action, record_result
from aclad.connections import discover, record_probe
from aclad.crm import propose_crm, prepare_crm_item, record_crm_item
from aclad.delivery import record_delivery
from aclad.followup import start_review, apply_review, finish_review
from aclad.icp_analysis import analyze_icps
from aclad.icps import propose_icp, approve_icp, bind_icp
from aclad.learning import capture_correction, relevant_rules
from aclad.messages import propose_draft, propose_send
from aclad.profiles import save_profile
from aclad.models import ExternalRef, GateError, Scope, ToolResult
from aclad.onboarding import save_answer, environment_readiness
from aclad.outreach import briefing_context, plan_outreach
from aclad.prospecting import (open_campaign, prepare_prospecting, record_candidates,
                              check_account, apply_enrichment, confirm_roles, select_contacts)
from aclad.recovery import bootstrap, checkpoint
from aclad.store import Store
from tests.support import FakeBridge


NOW = '2026-10-22T12:00:00Z'
LATER = '2026-10-22T13:00:00Z'


class JourneyTests(unittest.TestCase):
    def _journey(self, surface, workspace=False):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'private'
            scope = Scope('partner-a','seller-a',surface)
            if workspace:
                root = Path(temp).resolve() / 'Seller project'
                created = subprocess.run([sys.executable,'-m','aclad','--workspace',str(root),'workspace-init'],
                    input=json.dumps({'name':'Seller'}),text=True,capture_output=True,cwd=temp,
                    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[2]/'plugins/aclad-prospecting/runtime')})
                self.assertEqual(created.returncode,0,created.stdout+created.stderr)
                info=json.loads(created.stdout)
                directory=Path(info['state_dir'])
                scope=Scope(info['partner_id'],info['seller_id'],info['instance_id'])
            store = Store(directory,scope)
            bridge = FakeBridge()
            seller = ExternalRef('crm-demo','tenant-demo','connection-demo','seller-a')
            sender = ExternalRef('outlook','tenant-demo','mail-1','seller@example.invalid')
            tools = [
                ('accounts.search','data-1','demo-data','free'),
                ('companies.enrich','data-1','demo-data','paid'),
                ('people.search','data-1','demo-data','free'),
                ('people.reveal_email','data-1','demo-data','paid'),
                ('crm.read','connection-demo','crm-demo','free'),
                ('crm.write','connection-demo','crm-demo','free'),
                ('email.create_draft','mail-1','outlook','free'),
                ('email.send','mail-1','outlook','free'),
            ]
            if workspace:
                tools.append(('calendar.read','calendar','calendar','free'))
            try:
                for field,value in [('language','pt-BR'),('partner.name','Parceiro Fictício'),
                                    ('partner.products',['ERP']),('seller.name','Vendedor Fictício'),
                                    ('seller.territory',['BR']),('seller.crm_user_id','seller-a'),
                                    ('seller.writing_style','Direto'),('schedule_preferences.mode','combined')]:
                    save_answer(store,field,value)
                # The synthetic seller explicitly reviews the commercial offer before generation.
                settings = store.get('profile', 'current').data
                save_profile(store, dict(settings, partner=dict(settings['partner'], offerings=[{
                    'id': 'netsuite', 'name': 'NetSuite', 'kind': 'netsuite',
                    'status': 'approved', 'approved_by': 'seller-a', 'source_ids': ['reviewed-partner-offer']}])))
                readiness = environment_readiness(store,{'surface':surface,'runtime_version':'3.13',
                    'durable_state':True,'state_accessible_to_executor':True,
                    'identity_resolved':True,'tools_verified':True,'scheduler_verified':False})
                self.assertTrue(readiness['can_external_actions'])
                self.assertFalse(readiness['can_schedule'])
                caps = discover(store,[{'operation':op,'tool_name':'fake.'+op,'connection_id':conn,
                    'provider':provider,'cost':cost,
                    'account_identity':sender.object_id if conn=='mail-1' else seller.object_id}
                    for op,conn,provider,cost in tools],True)
                capabilities = {cap.operation:record_probe(store,cap,{'connection_id':cap.connection_id,
                    'status_code':200,'evidence':'synthetic-capability-fixture',
                    'account_identity':sender.object_id if cap.operation.startswith('email.') else seller.object_id}) for cap in caps}

                def result(intent,data,object_id):
                    provider = next(provider for op,conn,provider,cost in tools if op==intent.operation)
                    ref = ExternalRef(provider,'tenant-demo',intent.connection_id,object_id)
                    bridge.results[intent.action_id] = ToolResult(intent.action_id,'succeeded',[ref],data)
                    return bridge.call(intent)

                def execute(proposal, data, object_id, preflight=None, authorize=False):
                    if authorize:
                        approve(store,proposal.id,proposal.revision,proposal.digest,'seller-a',NOW)
                    intent=prepare_action(store,proposal.id,capabilities[proposal.operation],preflight or {},NOW)
                    return intent,result(intent,data,object_id)

                rows=json.loads((Path(__file__).parent/'fixtures/icp_accounts.json').read_text())
                profiles=analyze_icps(rows,seller,{'scope':'accessible_subset','complete':False,'filters':[],'as_of':NOW})
                self.assertEqual([profiles[key]['population_count'] for key in
                    ('partner_customers','seller_customers','seller_prospects')],[2,1,1])
                store.put('analysis','analysis-1',{'profiles':profiles},None)
                icp=propose_icp(store,[{'field':'industry','operator':'in','value':['manufacturing'],'basis':'evidence'}],[],['analysis-1'],False)
                icp=approve_icp(store,icp.id,icp.revision,'seller-a')
                open_campaign(store,'campaign-1','Nova prospecção')
                bind_icp(store,'campaign-1',icp.id,icp.revision)

                search=prepare_prospecting(store,'campaign-1','accounts.search',['campaign-1'],capabilities['accounts.search'],{})
                accounts=[{'id':id,'name':'Synthetic '+id,'source_at':NOW,'industry':'manufacturing',
                           'external_ref':asdict(ExternalRef('demo-data','tenant-demo','data-1','external-'+id))}
                          for id in ('account-a','account-b')]
                intent,outcome=execute(search,{'candidates':accounts},'account-search-result')
                record_result(store,outcome)
                record_candidates(store,'campaign-1','account',accounts,intent.action_id)
                observations=[{'account_id':account['id'],'owner_ref':asdict(seller),'nurturing':True} for account in accounts]
                read=create_proposal(store,'crm.read',seller.connection_id,['account-a','account-b'],{'campaign_id':'campaign-1'})
                checked,outcome=execute(read,{'complete':True,'observations':observations,'users':[asdict(seller)]},'crm-lookup')
                record_result(store,outcome)
                for observation in observations:
                    check_account(store,'campaign-1',observation['account_id'],observation,checked.action_id,seller,{})
                select_accounts(store,'campaign-1',['account-a'])
                self.assertFalse(store.get('account','account-b').data['selected'])

                limits={'max_items':1,'max_credits':'1','cost_acknowledged':True}
                proposal=prepare_prospecting(store,'campaign-1','companies.enrich',['account-a'],capabilities['companies.enrich'],limits)
                item={'id':'account-a','fields':{'employees':150,'industry':'manufacturing'},
                      'provenance':{'source':'data-1','collected_at':NOW,'basis':'licensed'}}
                enriched,outcome=execute(proposal,{'items':[item]},'company-enrichment',authorize=True)
                record_result(store,outcome)
                apply_enrichment(store,enriched.action_id,[item])
                confirm_roles(store,'campaign-1','account-a',[{'title':'CFO','seniority':'executive','max_contacts':1}])
                people=prepare_prospecting(store,'campaign-1','people.search',['account-a'],capabilities['people.search'],{})
                candidates=[{'id':'contact-a','account_id':'account-a','title':'CFO','source_at':NOW,
                             'external_ref':asdict(ExternalRef('demo-data','tenant-demo','data-1','candidate-a'))}]
                searched,outcome=execute(people,{'candidates':candidates},'people-search-result')
                record_result(store,outcome)
                record_candidates(store,'campaign-1','contact',candidates,searched.action_id)
                with self.assertRaises(GateError):
                    prepare_prospecting(store,'campaign-1','people.reveal_email',['contact-a'],capabilities['people.reveal_email'],limits)
                select_contacts(store,'campaign-1',['contact-a'])
                reveal=prepare_prospecting(store,'campaign-1','people.reveal_email',['contact-a'],capabilities['people.reveal_email'],limits)
                contact_item={'id':'contact-a','fields':{'email':'buyer@example.invalid'},
                    'provenance':{'source':'data-1','collected_at':NOW,'basis':'licensed'}}
                revealed,outcome=execute(reveal,{'items':[contact_item]},'revealed-contact',authorize=True)
                record_result(store,outcome)
                apply_enrichment(store,revealed.action_id,[contact_item])

                changes=[{'local_id':'account-a','entity':'account','external_ref':None,'before':{},
                          'after':{'name':'Synthetic Account A'},'links':{},'provenance':[enriched.action_id]},
                         {'local_id':'contact-a','entity':'contact','external_ref':None,'before':{},
                          'after':{'email':'buyer@example.invalid'},'links':{'account_id':'account-a'},'provenance':[revealed.action_id]}]
                crm=propose_crm(store,'campaign-1',changes,seller)
                approve(store,crm.id,crm.revision,crm.digest,'seller-a',NOW)
                crm_preflight={'checked_at':NOW,'connection_id':seller.connection_id,'ownership_allowed':True,
                    'contact_allowed':True,'opportunity_allowed':True,'external_revision':'new'}
                for change in crm.payload['changes']:
                    applied=prepare_crm_item(store,crm.id,change['change_id'],capabilities['crm.write'],crm_preflight,NOW)
                    record_crm_item(store,result(applied,{},'remote-'+change['local_id']))
                self.assertEqual(store.get('contact','contact-a').data['crm_status'],'confirmed')

                capture_correction(store,'Long opening','Keep my opening short','personal:email',True,'explicit-preference-1')
                briefing=briefing_context(store,'campaign-1','account-a')
                self.assertEqual(briefing['icp_revision'],icp.revision)
                steps=[{'id':'step-'+str(n),'contact_id':'contact-a','channel':'email','objective':'Conversation',
                        'angle':'Inventory visibility','delay_days':delay,
                        'cadence_basis':{'type':'seller_decision','evidence_id':'cadence-decision-1'},
                        'stop_conditions':['reply','do_not_contact']} for n,delay in [(1,0),(2,3)]]
                if workspace:
                    for step in steps:
                        step['learning_context']={'objective':'Conversation','approach':'Inventory visibility',
                                                  'variant':'question','source_ids':[]}
                plan_outreach(store,'campaign-1',steps,[])
                content={'account_id':'account-a','contact_id':'contact-a','sender_ref':asdict(sender),
                    'to':['buyer@example.invalid'],'cc':[],'bcc':[],'subject':'Inventory visibility',
                    'body':'How are you managing inventory across plants?','attachments':[],
                    'source_ids':[enriched.action_id],'plan_step_id':'step-1','offering_ids':['netsuite']}
                if workspace:
                    content['learning_context']=steps[0]['learning_context']
                draft=propose_draft(store,'campaign-1',content)
                drafted,outcome=execute(draft,{},'draft-a',authorize=True)
                message=record_delivery(store,outcome,draft.id)
                draft_ref=ExternalRef(**message.data['draft_ref'])
                mail_preflight={'checked_at':NOW,'connection_id':'mail-1','ownership_allowed':True,
                    'contact_allowed':True,'opportunity_allowed':True,'external_revision':'revision-1',
                    'sender_connection_id':'mail-1','sender_object_id':sender.object_id,
                    'crm_confirmed':True,'recent_replies':False}
                send=propose_send(store,draft_ref,dict(content,external_revision='revision-1'),mail_preflight)
                with self.assertRaises(GateError):
                    prepare_action(store,send.id,capabilities['email.send'],mail_preflight,NOW)
                self.assertFalse(any(call.operation=='email.send' for call in bridge.calls))
                conversation=asdict(ExternalRef('outlook','tenant-demo','mail-1','thread-a'))
                sent,outcome=execute(send,{'sent_at':NOW,'conversation_ref':conversation},'sent-a',mail_preflight,True)
                message=record_delivery(store,outcome,draft.id)
                self.assertEqual(message.data['next_action']['due_at'],'2026-10-25T12:00:00Z')

                # Explicit compact/reopen path: no hooks are installed or called.
                sequence=checkpoint(store).event_sequence
                store.close()
                store=Store(directory,scope)
                self.assertGreaterEqual(bootstrap(store,LATER).event_sequence,sequence)
                self.assertEqual(relevant_rules(store,'personal:email')[0].data['instruction'],'Keep my opening short')
                self.assertEqual(store.get('campaign','campaign-1').data['icp_revision'],icp.revision)
                event={'external_ref':asdict(ExternalRef('outlook','tenant-demo','mail-1','reply-a')),
                    'conversation_ref':conversation,'account_id':'account-a','contact_id':'contact-a',
                    'kind':'email','occurred_at':LATER,'source_revision':'1','classification':'interested',
                    'evidence':'Synthetic selected reply: interested in discussing inventory.'}
                run=start_review(store,'manual',LATER)
                report=apply_review(store,run.id,[event],[{'connection_id':'mail-1','source':'email',
                    'next_cursor':'cursor-1','complete':True}],[],LATER)
                finish_review(store,run.id,LATER)
                self.assertTrue(report['notify'])
                self.assertTrue(report['pending_actions'])
                self.assertTrue(store.get('account','account-a').data['contact_blocked'])
                run=start_review(store,'scheduled',LATER)
                repeated=apply_review(store,run.id,[event],[],[],LATER)
                finish_review(store,run.id,LATER)
                self.assertFalse(repeated['notify'])
                self.assertEqual(len([call for call in bridge.calls if call.operation=='email.send']),1)
                self.assertEqual([call.payload['item_ids'] for call in bridge.calls
                    if call.operation=='companies.enrich'],[['account-a']])
                self.assertEqual([call.payload['item_ids'] for call in bridge.calls
                    if call.operation=='people.reveal_email'],[['contact-a']])
                if workspace:
                    from aclad.meetings import record_meetings
                    from aclad.outcome_learning import propose_outcome_rule, review_outcome_rule, relevant_outcome_rules
                    item={'ref':asdict(ExternalRef('calendar','tenant-demo','calendar','meeting-a')),
                          'source_revision':'1','status':'confirmed','starts_at':'2026-11-01T12:00:00Z',
                          'ends_at':'2026-11-01T13:00:00Z','participant_refs':[candidates[0]['external_ref']]}
                    proposal=create_proposal(store,'calendar.read','calendar',['account-a'],{'campaign_id':'campaign-1','account_ids':['account-a']})
                    intent,outcome=execute(proposal,{'items':[item],'complete':True},'calendar-page')
                    record_result(store,outcome)
                    record_meetings(store,'campaign-1',intent.action_id,[{
                        **{key:value for key,value in item.items() if key!='participant_refs'},
                        'account_id':'account-a','contact_ids':['contact-a']}])
                    observation=next(r for r in store.list('analysis') if r.data.get('type')=='outcome_observation')
                    self.assertEqual(observation.data['exposure_count'],1)
                    rule=propose_outcome_rule(store,{'task':'email','objective':'Conversation'},
                                             'Ask a short inventory question.',[observation.id])
                    self.assertEqual(rule.data['status'],'candidate')
                    reviewed=review_outcome_rule(store,rule.id,rule.revision,'approve','seller-reviewed-observation')
                    self.assertEqual(relevant_outcome_rules(store,{'task':'email','objective':'Conversation'}),[reviewed])
                    resumed=subprocess.run([sys.executable,'-m','aclad','resume'],input='{}',text=True,capture_output=True,cwd=root,
                        env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[2]/'plugins/aclad-prospecting/runtime')})
                    self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
                    numeric=(root/'contexto/resultados.md').read_text()
                    for line in ('| Contas buscadas | 2 |','| E-mails enviados | 1 |',
                                 '| Respostas humanas recebidas | 1 |','| Reuniões marcadas | 1 |'):
                        self.assertIn(line,numeric)
                    for secret in ('Parceiro Fictício','buyer@example.invalid','account-a','manufacturing','seller-a'):
                        self.assertNotIn(secret,numeric)
                    self.assertIn('Ask a short inventory question.',(root/'contexto/aprendizados.md').read_text())

            finally:
                store.close()

    def test_codex_local_journey_without_hooks(self):
        self._journey('codex-local')

    def test_cowork_local_journey_without_hooks(self):
        self._journey('cowork-local')
