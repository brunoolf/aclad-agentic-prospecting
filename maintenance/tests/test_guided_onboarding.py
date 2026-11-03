"""Evidence-backed setup: selected names are not working connections."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aclad.models import GateError, Scope
from aclad.store import Store
from aclad.workspace import initialize_workspace
from aclad.onboarding import environment_readiness, next_question, save_answer
from aclad.connections import discover, record_probe
try:
    from aclad import setup_flow
except ImportError:
    setup_flow = None


class GuidedOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'Seller Project'
        info = initialize_workspace(self.root, 'Test seller')
        self.scope = Scope(info['partner_id'], info['seller_id'], info['instance_id'])
        self.store = Store(self.root / '.aclad', self.scope)
        self.assertIsNotNone(setup_flow, 'guided setup module missing')
        setup_flow.start_setup(self.store)
        environment_readiness(self.store, {'surface': 'codex-local', 'runtime_version': '3.13',
            'durable_state': True, 'state_accessible_to_executor': True, 'identity_resolved': True,
            'tools_verified': True, 'scheduler_verified': True})

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def profile(self):
        for field, value in [('language','pt-BR'),('partner.name','Example Partner'),
                ('partner.website','https://partner.example'), ('seller.name','Seller'),
                ('seller.territory',['BR']),('seller.size_bands',['Todos']),
                ('partner.offerings',[{'id':'ns','name':'NetSuite','kind':'netsuite','status':'approved',
                  'approved_by':'seller','source_ids':['site-research']}]),
                ('setup.prospecting_history','new')]:
            save_answer(self.store,field,value)

    def connections(self, write=False, probe=True):
        tools=[]
        for provider, conn, operations in [('crm','crm',['crm.read']+(['crm.write'] if write else [])),
                ('data','data',['connection.identity','accounts.search','people.search','companies.enrich','people.reveal_email']),
                ('outlook','mail',['email.read','email.create_draft','email.send'])]:
            tools += [dict(provider=provider,connection_id=conn,operation=op,tool_name='native.'+op,
                account_identity='seller@partner.example',cost='free') for op in operations]
        caps=discover(self.store,tools,True)
        if probe:
            for cap in caps:
                if cap.operation in {'crm.read','email.read','connection.identity'}:
                    record_probe(self.store,cap,{'connection_id':cap.connection_id,'status_code':200,
                        'account_identity':'seller@partner.example','evidence':'native identity result'})
        return caps

    def complete(self,block):
        return setup_flow.complete_block(self.store,block,'seller')

    def before_connections(self):
        self.profile(); self.complete('workspace'); self.complete('identity')

    def before_automation(self):
        self.before_connections(); self.connections(); self.complete('connections')
        save_answer(self.store,'seller.writing_style','Consultivo, médio, profissional próximo')
        self.complete('communication')

    def full_manual(self):
        self.before_automation()
        save_answer(self.store,'schedule_preferences.mode','manual'); self.complete('automation')
        save_answer(self.store, 'icp.criteria.industries', [])
        save_answer(self.store, 'icp.criteria.subindustries', [])
        from aclad.icps import propose_icp,approve_icp,bind_icp
        from aclad.prospecting import open_campaign
        icp=propose_icp(self.store,[{'field':'country','operator':'in','value':['BR'],'basis':'hypothesis'}],
            [],[],True,name='Financeiro SP')
        icp=approve_icp(self.store,icp.id,icp.revision,'seller')
        self.icp_id=icp.id
        self.complete('icps')
        open_campaign(self.store,'campaign-one','Apresentar NetSuite')
        bind_icp(self.store,'campaign-one',icp.id,icp.revision)
        self.complete('campaign')

    def before_icps(self):
        self.before_automation()
        save_answer(self.store, 'schedule_preferences.mode', 'manual')
        self.complete('automation')

    def test_icp_asks_industry_then_subindustry_and_preserves_answers_on_resume(self):
        self.before_icps()
        question = next_question(self.store)
        self.assertEqual(question['block_id'], 'icps')
        self.assertEqual(question['field'], 'icp.criteria.industries')
        self.assertIn('indústria', question['question'].lower())
        save_answer(self.store, question['field'], ['Manufatura'])
        self.store.close(); self.store = Store(self.root / '.aclad', self.scope)
        question = next_question(self.store)
        self.assertEqual(question['field'], 'icp.criteria.subindustries')
        self.assertIn('subindústria', question['question'].lower())
        self.assertTrue(any(option['value'] == [] for option in question['options']))
        save_answer(self.store, question['field'], [])
        self.assertEqual(next_question(self.store)['missing'], ['icp.approved_named'])

    def test_icp_cannot_be_approved_without_reviewing_both_sector_questions(self):
        self.before_icps()
        from aclad.icps import propose_icp, approve_icp
        criteria = [{'field': 'country', 'operator': 'in', 'value': ['BR'], 'basis': 'hypothesis'}]
        proposed = propose_icp(self.store, criteria, [], [], True, name='Brasil')
        with self.assertRaises(GateError) as error:
            approve_icp(self.store, proposed.id, proposed.revision, 'seller')
        self.assertEqual(error.exception.code, 'icp_sector_review_required')
        self.assertEqual(self.store.get('icp', proposed.id).data['status'], 'proposed')
        save_answer(self.store, 'icp.criteria.industries', [])
        proposed = propose_icp(self.store, criteria, [], [], True, name='Brasil')
        with self.assertRaises(GateError) as error:
            approve_icp(self.store, proposed.id, proposed.revision, 'seller')
        self.assertEqual(error.exception.code, 'icp_sector_review_required')
        save_answer(self.store, 'icp.criteria.subindustries', [])
        proposed = propose_icp(self.store, criteria, [], [], True, name='Brasil')
        approved = approve_icp(self.store, proposed.id, proposed.revision, 'seller')
        scope = approved.data['approved_versions'][str(approved.revision)]['sector_scope']
        self.assertEqual(scope, {'industries': [], 'subindustries': []})
        from aclad.workflow_views import icp_catalog
        entry = next(row for row in icp_catalog(self.store)['icps'] if row['id'] == approved.id)
        self.assertEqual(entry['sector_scope'], {'industries': [], 'subindustries': []})
        document = (self.root / entry['document_path']).read_text()
        self.assertIn('"sector_scope"', document)
        self.complete('icps')

    def test_chosen_sectors_must_be_applied_to_icp_filters(self):
        self.before_icps()
        from aclad.icps import propose_icp, approve_icp
        save_answer(self.store, 'icp.criteria.industries', ['Manufatura'])
        save_answer(self.store, 'icp.criteria.subindustries', ['Alimentos'])
        criteria = [{'field': 'country', 'operator': 'in', 'value': ['BR'], 'basis': 'hypothesis'}]
        for field, values in [('industry', ['Manufatura']), ('subindustry', ['Alimentos'])]:
            proposed = propose_icp(self.store, criteria, [], [], True, name='Alimentos BR')
            with self.assertRaises(GateError) as error:
                approve_icp(self.store, proposed.id, proposed.revision, 'seller')
            self.assertEqual(error.exception.code, 'icp_sector_criteria_required')
            criteria.append({'field': field, 'operator': 'in', 'value': values, 'basis': 'hypothesis'})
        proposed = propose_icp(self.store, criteria, [], [], True, name='Alimentos BR')
        approved = approve_icp(self.store, proposed.id, proposed.revision, 'seller')
        self.assertEqual(approved.data['approved_versions'][str(approved.revision)]['criteria'], criteria)

    def test_changing_sector_answers_requires_a_new_icp_proposal(self):
        self.before_icps()
        from aclad.icps import propose_icp, approve_icp
        save_answer(self.store, 'icp.criteria.industries', [])
        save_answer(self.store, 'icp.criteria.subindustries', [])
        proposed = propose_icp(self.store, [{'field': 'industry', 'operator': 'in',
            'value': ['Manufatura'], 'basis': 'hypothesis'}], [], [], True)
        save_answer(self.store, 'icp.criteria.industries', ['Serviços'])
        with self.assertRaises(GateError) as error:
            approve_icp(self.store, proposed.id, proposed.revision, 'seller')
        self.assertEqual(error.exception.code, 'icp_context_changed')

    def test_named_legacy_icp_does_not_hide_unanswered_sector_questions(self):
        self.before_icps()
        self.store.put('icp', 'legacy', {'name': 'Brasil', 'status': 'active',
            'approved_revision': 2, 'approved_versions': {'2': {'digest': 'legacy'}}}, None)
        with self.assertRaises(GateError) as error:
            self.complete('icps')
        self.assertEqual(error.exception.code, 'setup_block_incomplete')
        self.assertEqual(next_question(self.store)['field'], 'icp.criteria.industries')

    def test_blank_sector_values_cannot_silently_mean_unrestricted(self):
        for field in ('icp.criteria.industries', 'icp.criteria.subindustries'):
            with self.subTest(field=field), self.assertRaises(GateError):
                save_answer(self.store, field, ['  '])

    def test_start_is_idempotent_and_resume_preserves_reviews(self):
        first=self.store.get('profile','guided-onboarding')
        self.assertEqual(setup_flow.start_setup(self.store),first)
        self.complete('workspace')
        self.store.close(); self.store=Store(self.root/'.aclad',self.scope)
        self.assertEqual(setup_flow.setup_status(self.store)['current_block'],'identity')
        self.assertEqual(setup_flow.start_setup(self.store),self.store.get('profile','guided-onboarding'))

    def test_cannot_skip_blocks_or_approve_missing_evidence(self):
        with self.assertRaises(GateError) as e: self.complete('connections')
        self.assertEqual(e.exception.code,'setup_block_out_of_order')
        self.complete('workspace')
        with self.assertRaises(GateError) as e: self.complete('identity')
        self.assertEqual(e.exception.code,'setup_block_incomplete')

    def test_first_question_only_current_block(self):
        first=next_question(self.store)
        self.assertEqual(first['block_id'],'workspace')
        self.assertLessEqual(len(first['fields']),3)
        self.assertEqual(first['interaction']['preferred'],'native_question')
        self.assertEqual(first['interaction']['fallback'],'chat')
        self.complete('workspace')
        self.assertEqual(next_question(self.store)['block_id'],'identity')

    def test_names_and_declared_tools_do_not_finish_connections(self):
        self.before_connections()
        save_answer(self.store,'tool_suggestions',['CRM','Apollo','Outlook'])
        self.connections(probe=False)
        with self.assertRaises(GateError) as e:self.complete('connections')
        self.assertEqual(e.exception.code,'setup_block_incomplete')
        self.assertIn('crm',setup_flow.setup_status(self.store)['connections']['missing'])

    def test_readonly_crm_and_authenticated_declared_write_tools_are_accepted(self):
        self.before_connections(); self.connections(); self.complete('connections')
        status=setup_flow.setup_status(self.store)
        self.assertEqual(status['current_block'],'communication')
        self.assertTrue(status['connections']['crm_read_only'])
        self.assertFalse(status['connections']['crm_write_available'])
        self.assertEqual(status['connections']['missing'],[])

    def test_web_is_not_prospecting_connection(self):
        self.before_connections()
        tools=[dict(operation='web.search',tool_name='web',connection_id='web',provider='web',
            account_identity='seller',cost='free')]
        discover(self.store,tools,True)
        self.assertIn('prospecting',setup_flow.setup_status(self.store)['connections']['missing'])

    def test_authentication_revocation_reopens_completed_connections(self):
        self.full_manual(); self.assertTrue(setup_flow.setup_status(self.store)['complete'])
        cap=next(row.data['capability'] for row in self.store.list('connection') if row.data['capability']['operation']=='crm.read')
        from aclad.models import Capability
        record_probe(self.store,Capability(**cap),{'connection_id':cap['connection_id'],'status_code':401,'evidence':'expired'})
        status=setup_flow.setup_status(self.store)
        self.assertFalse(status['complete']); self.assertEqual(status['current_block'],'connections')
        with self.assertRaises(GateError):setup_flow.require_operational_readiness(self.store,'accounts.search')

    def test_manual_setup_complete_and_readonly_write_is_operation_specific(self):
        self.full_manual()
        self.assertTrue(setup_flow.setup_status(self.store)['complete'])
        setup_flow.require_operational_readiness(self.store,'accounts.search')
        setup_flow.require_operational_readiness(self.store,'crm.read')
        with self.assertRaises(GateError) as e:setup_flow.require_operational_readiness(self.store,'crm.write')
        self.assertEqual(e.exception.code,'crm_write_unavailable')

    def test_initial_reads_remain_available_during_configuration(self):
        setup_flow.require_operational_readiness(self.store,'crm.read')
        setup_flow.require_operational_readiness(self.store,'email.read')
        with self.assertRaises(GateError) as e:setup_flow.require_operational_readiness(self.store,'accounts.search')
        self.assertEqual(e.exception.code,'setup_incomplete')

    def test_scheduled_choice_not_misreported_as_active(self):
        self.before_automation()
        for field,value in [('schedule_preferences.mode','scheduled'),('schedule_preferences.days',[1,2,3,4,5]),
                ('schedule_preferences.times',['10:00','14:00']),('schedule_preferences.timezone','America/Sao_Paulo')]:
            save_answer(self.store,field,value)
        self.complete('automation')
        status=setup_flow.setup_status(self.store)
        self.assertEqual(status['current_block'],'icps')
        self.assertFalse(status['automation']['active'])
        self.assertTrue(status['automation']['activation_pending'])
        self.assertFalse(status['complete'])

    def test_blank_or_ambiguous_history_answer_rejected(self):
        for value in ('','  ','sim','all',True):
            with self.subTest(value=value),self.assertRaises(GateError):
                save_answer(self.store,'setup.prospecting_history',value)
        save_answer(self.store,'setup.prospecting_history','new')

    def test_empty_reviewer_never_finishes_block(self):
        with self.assertRaises(GateError) as e:setup_flow.complete_block(self.store,'workspace',' ')
        self.assertEqual(e.exception.code,'setup_reviewer_required')

    def test_changing_profile_reopens_review_without_resetting_other_answers(self):
        self.full_manual()
        save_answer(self.store,'seller.territory',['MX'])
        status=setup_flow.setup_status(self.store)
        self.assertEqual(status['current_block'],'identity')
        self.assertFalse(status['complete'])
        self.assertEqual(self.store.get('profile','current').data['partner']['name'],'Example Partner')

    def test_smtp_send_alone_cannot_satisfy_communication(self):
        self.before_connections(); self.connections()
        discover(self.store,[dict(provider='smtp',operation='email.send',tool_name='smtp.send',
            connection_id='smtp',account_identity='seller@partner.example',cost='free')],True)
        self.assertIn('communication',setup_flow.setup_status(self.store)['connections']['missing'])

    def test_named_icp_and_bound_campaign_required_before_complete(self):
        self.before_automation();save_answer(self.store,'schedule_preferences.mode','manual');self.complete('automation')
        with self.assertRaises(GateError):self.complete('icps')
        self.store.put('icp','unnamed',{'status':'active','approved_revision':2,'approved_versions':{'2':{}}},None)
        with self.assertRaises(GateError):self.complete('icps')

    def test_setup_projection_is_private_and_has_no_database_side_effect(self):
        self.complete('workspace')
        before=self.store.snapshot().event_sequence
        self.assertTrue(hasattr(setup_flow,'refresh_setup_view'))
        setup_flow.refresh_setup_view(self.store)
        output=self.root/'contexto/configuracao.md'
        self.assertTrue(output.is_file())
        self.assertIn('Você e sua empresa',output.read_text())
        self.assertIn('Pendente',output.read_text())
        self.assertEqual(self.store.snapshot().event_sequence,before)

    def test_setup_projection_symlink_never_writes_outside_project(self):
        outside=Path(self.tmp.name)/'outside.txt';outside.write_text('preserve')
        (self.root/'contexto/configuracao.md').unlink(missing_ok=True)
        (self.root/'contexto/configuracao.md').symlink_to(outside)
        self.assertTrue(hasattr(setup_flow,'refresh_setup_view'))
        with self.assertRaises(GateError):setup_flow.refresh_setup_view(self.store)
        self.assertEqual(outside.read_text(),'preserve')

    def test_scheduled_configuration_requires_real_matching_native_confirmation(self):
        self.full_manual()
        for field,value in [('schedule_preferences.mode','scheduled'),('schedule_preferences.days',[1,2,3,4,5]),
                ('schedule_preferences.times',['10:00','14:00']),('schedule_preferences.timezone','America/Sao_Paulo')]:
            save_answer(self.store,field,value)
        self.complete('automation')
        self.assertFalse(setup_flow.setup_status(self.store)['complete'])
        from aclad.scheduling import schedule_request,record_schedule_result,next_runs
        schedule={'weekdays':[1,2,3,4,5],'times':['10:00','14:00'],'timezone':'America/Sao_Paulo',
            'scope_ids':['campaign-one'],'active':True,'notification_policy':'actionable_changes'}
        target={'mode':'project_job','workspace_path':str(self.store.workspace_root),'project_id':'project-test'}
        capability={'available':True,'verified':True,'tool_name':'native.schedule','executor_id':'executor',
            'mapping_verified':True,'target':target,'native_configuration':{
                'schedule':deepcopy(schedule),'target':target,'parameters':{'schedule':'verified'}}}
        request=schedule_request(self.store,schedule,capability)
        self.assertFalse(setup_flow.setup_status(self.store)['complete'])
        confirmed='2026-11-03T12:00:00Z'
        record_schedule_result(self.store,request['request_id'],{'status':'succeeded','native_id':'native-id',
            'evidence':'native tool confirmed','effective_schedule':schedule,'target':target,
            'confirmed_at':confirmed,'next_occurrences':next_runs(schedule,confirmed,3)})
        self.assertTrue(setup_flow.setup_status(self.store)['complete'])
        save_answer(self.store,'schedule_preferences.times',['16:00'])
        self.assertFalse(setup_flow.setup_status(self.store)['complete'])
        self.assertTrue(setup_flow.setup_status(self.store)['automation']['activation_pending'])

    def test_refused_operation_not_inherited_from_authenticated_sibling(self):
        self.before_connections();self.connections()
        row=next(r for r in self.store.list('connection') if r.data['capability']['operation']=='email.send')
        from aclad.models import Capability
        record_probe(self.store,Capability(**row.data['capability']),{'connection_id':row.data['capability']['connection_id'],
            'status_code':403,'evidence':'send not permitted'})
        self.assertIn('communication',setup_flow.setup_status(self.store)['connections']['missing'])

    def test_two_prospecting_accounts_cannot_be_combined(self):
        self.before_connections()
        tools=[]
        for conn,operations in [('one',['connection.identity','accounts.search']),('two',['connection.identity','people.search'])]:
            tools += [dict(provider='data',connection_id=conn,operation=operation,tool_name='native.'+operation,
                account_identity='seller@partner.example',cost='free') for operation in operations]
        caps=discover(self.store,tools,True)
        for cap in caps:
            if cap.operation=='connection.identity':
                record_probe(self.store,cap,{'connection_id':cap.connection_id,'status_code':200,
                    'account_identity':'seller@partner.example','evidence':'identity confirmed'})
        self.assertIn('prospecting',setup_flow.setup_status(self.store)['connections']['missing'])

    def test_adding_icps_and_campaigns_does_not_reopen_reviewed_initial_blocks(self):
        self.full_manual()
        self.store.put('icp','icp-two',{'name':'Manufatura','status':'active','approved_revision':2,
            'approved_versions':{'2':{'revision':2,'digest':'reviewed-two'}}},None)
        self.store.put('campaign','campaign-two',{'objective':'Outro objetivo','icp_id':'icp-two',
            'icp_revision':2,'icp_snapshot':{'revision':2,'digest':'reviewed-two'}},None)
        self.assertTrue(setup_flow.setup_status(self.store)['complete'])

    def test_campaign_remains_pinned_to_an_older_approved_icp_revision(self):
        self.full_manual()
        icp=self.store.get('icp',self.icp_id)
        self.store.put('icp',icp.id,dict(icp.data,approved_revision=3,approved_versions={
            **icp.data['approved_versions'],'3':{'revision':3,'digest':'new-revision'}}),icp.revision)
        status=setup_flow.setup_status(self.store)
        self.assertEqual(next(b for b in status['blocks'] if b['id']=='campaign')['status'],'complete')

    def test_automation_for_unrelated_campaign_cannot_finish_setup(self):
        self.full_manual()
        for field,value in [('schedule_preferences.mode','scheduled'),('schedule_preferences.days',[1]),
                ('schedule_preferences.times',['10:00']),('schedule_preferences.timezone','America/Sao_Paulo')]:
            save_answer(self.store,field,value)
        self.complete('automation')
        self.store.put('schedule','other-schedule',{'status':'active','native_id':'native-other',
            'evidence':'confirmed elsewhere','confirmed_at':'2026-11-03T12:00:00Z',
            'next_occurrences':['2026-11-09T13:00:00Z'],
            'target':{'mode':'project_job','project_id':'project','workspace_path':str(self.store.workspace_root)},
            'schedule':{'weekdays':[1],'times':['10:00'],'timezone':'America/Sao_Paulo','scope_ids':['other-campaign'],
                'active':True,'notification_policy':'actionable_changes'}},None)
        self.assertFalse(setup_flow.setup_status(self.store)['automation']['active'])
        self.assertFalse(setup_flow.setup_status(self.store)['complete'])

    def test_another_crm_does_not_satisfy_the_sellers_selected_crm(self):
        self.before_connections();self.connections(write=True)
        save_answer(self.store,'crm_mapping.provider','Another CRM')
        status=setup_flow.setup_status(self.store)
        self.assertIn('crm',status['connections']['missing'])
        self.assertFalse(status['connections']['crm_write_available'])

    def test_invalid_time_does_not_repeat_valid_weekdays(self):
        self.before_automation()
        for field,value in [('schedule_preferences.mode','scheduled'),('schedule_preferences.days',[1,2,3,4,5]),
                ('schedule_preferences.times',['25:00']),('schedule_preferences.timezone','America/Sao_Paulo')]:
            save_answer(self.store,field,value)
        missing=next(b for b in setup_flow.setup_status(self.store)['blocks'] if b['id']=='automation')['missing']
        self.assertIn('schedule_preferences.times',missing)
        self.assertNotIn('schedule_preferences.days',missing)

    def test_successful_first_search_does_not_reopen_completed_connections(self):
        self.full_manual()
        from aclad.approvals import create_proposal,approve,prepare_action,record_result
        from aclad.models import Capability,ToolResult,now_utc
        cap=Capability(**next(r.data['capability'] for r in self.store.list('connection')
            if r.data['capability']['operation']=='accounts.search'))
        self.assertEqual(cap.verification,'declared')
        before=next(b for b in setup_flow.setup_status(self.store)['blocks'] if b['id']=='connections')['evidence_digest']
        from aclad.prospecting import prepare_prospecting
        proposal=prepare_prospecting(self.store,'campaign-one','accounts.search',['campaign-one'],cap,{'max_items':1})
        approve(self.store,proposal.id,proposal.revision,proposal.digest,'seller',now_utc())
        intent=prepare_action(self.store,proposal.id,cap,{},now_utc())
        record_result(self.store,ToolResult(intent.action_id,'succeeded',[],{'candidates':[]}))
        current=next(r.data['capability'] for r in self.store.list('connection')
            if r.data['capability']['operation']=='accounts.search')
        self.assertEqual(current['verification'],'verified')
        status=setup_flow.setup_status(self.store)
        self.assertTrue(status['complete'])
        self.assertEqual(next(b for b in status['blocks'] if b['id']=='connections')['evidence_digest'],before)
        setup_flow.require_operational_readiness(self.store,'people.search')

    def test_unrelated_new_connection_does_not_reopen_reviewed_selection(self):
        self.full_manual()
        tools=[dict(provider=row.data['provider'],connection_id=row.data['native_connection_id'],
            operation=row.data['capability']['operation'],tool_name=row.data['capability']['tool_name'],
            account_identity=row.data['account_identity'],cost=row.data['capability']['cost'])
            for row in self.store.list('connection')]
        tools.append(dict(provider='calendar',connection_id='other',operation='calendar.read',
            tool_name='calendar.read',account_identity='other@example.invalid',cost='free'))
        discover(self.store,tools,True)
        self.assertTrue(setup_flow.setup_status(self.store)['complete'])

    def test_explicit_permission_denial_reopens_completed_connection_block(self):
        self.full_manual()
        row=next(r for r in self.store.list('connection') if r.data['capability']['operation']=='people.search')
        from aclad.models import Capability
        record_probe(self.store,Capability(**row.data['capability']),{'connection_id':row.data['capability']['connection_id'],
            'status_code':403,'evidence':'native permission denied'})
        self.assertEqual(setup_flow.setup_status(self.store)['current_block'],'connections')
        self.assertFalse(setup_flow.setup_status(self.store)['complete'])

    def test_changed_native_tool_binding_reopens_connection_review(self):
        self.full_manual()
        tools=[dict(provider=row.data['provider'],connection_id=row.data['native_connection_id'],
            operation=row.data['capability']['operation'],
            tool_name='native.replaced-search' if row.data['capability']['operation']=='accounts.search' else row.data['capability']['tool_name'],
            account_identity=row.data['account_identity'],cost=row.data['capability']['cost'])
            for row in self.store.list('connection')]
        discover(self.store,tools,True)
        self.assertEqual(setup_flow.setup_status(self.store)['current_block'],'connections')
        self.assertFalse(setup_flow.setup_status(self.store)['complete'])
