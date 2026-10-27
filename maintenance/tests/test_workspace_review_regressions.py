"""Concrete regressions reproduced by the independent 0.3.0 review."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from aclad.approvals import create_proposal
from aclad.commands import dispatch
from aclad.delivery import record_delivery
from aclad.followup import start_review, apply_review, finish_review
from aclad.instances import initialize_instance
from aclad.models import GateError
from aclad.outcome_learning import propose_outcome_rule, refresh_outcome_observations, review_outcome_rule, relevant_outcome_rules, _meeting_evidence
from aclad.result_metrics import calculate_results
from aclad.workspace_migration import preview_migration, migrate_instance
from tests.support import StateTest
from tests.test_outcome_observations import OutcomeFixture, LATER
import tests.test_meetings as meeting_tests

class MigrationCrashTests(unittest.TestCase):
    def test_hard_exit_during_backup_or_destination_copy_is_retryable(self):
        for stage in ('backup','destination'):
            with self.subTest(stage=stage), TemporaryDirectory() as temporary:
                registry=Path(temporary)/'registry';root=Path(temporary)/'Seller project'
                instance=initialize_instance(registry,'Seller')
                preview=preview_migration(registry,instance['instance_id'],root)
                script='''import os,sys
from pathlib import Path
import aclad.workspace_migration as migration
real=migration.sqlite3.connect
def exiting(database,*args,**kwargs):
 if isinstance(database,Path) and not kwargs.get('uri'):
  stage='backup' if database.parent.name=='backups' else 'destination'
  if stage==sys.argv[5]: os._exit(29)
 return real(database,*args,**kwargs)
migration.sqlite3.connect=exiting
migration.migrate_instance(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]),sys.argv[4])
'''
                proc=subprocess.run([sys.executable,'-c',script,str(registry),instance['instance_id'],str(root),preview['digest'],stage],
                    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[2]/'plugins/aclad-prospecting/runtime')})
                self.assertEqual(proc.returncode,29)
                recovered=migrate_instance(registry,instance['instance_id'],root,preview['digest'])
                self.assertEqual(recovered['instance_id'],instance['instance_id'])

class OutcomeReviewRegressions(OutcomeFixture):
    def test_evidence_append_keeps_previous_negative_sample(self):
        self.send('a',with_context=True)
        run=start_review(self.store,'manual',LATER,['campaign'])
        apply_review(self.store,run.id,[],[{'connection_id':'mail','source':'email','complete':True}],[],LATER)
        finish_review(self.store,run.id,LATER)
        negative=refresh_outcome_observations(self.store)[0]
        rule=propose_outcome_rule(self.store,{'task':'email','objective':'Meeting'},'Keep a short question.',[negative.id])
        plan=self.store.get('outreach_plan','plan');steps=plan.data['steps']
        for step in steps:
            if step['contact_id']=='contact-b':step['learning_context']['variant']='direct'
        self.store.put('outreach_plan',plan.id,dict(plan.data,steps=steps),plan.revision)
        self.send('b',with_context=True);self.review_reply('b',identifier='reply-b')
        positive=next(row for row in refresh_outcome_observations(self.store) if row.data['context'].get('variant')=='direct')
        updated=propose_outcome_rule(self.store,{'task':'email','objective':'Meeting'},'Keep a short question.',[positive.id])
        self.assertEqual(set(updated.data['observation_revisions']),{negative.id,positive.id})
        self.assertEqual(updated.data['sample'],{'exposed':2,'replied':1,'unobserved':0})

    def test_followup_requires_query_after_latest_send_for_coverage(self):
        self.send('a',index=0);self.send('b',index=0)
        run=start_review(self.store,'manual',LATER,['campaign'])
        apply_review(self.store,run.id,[],[{'connection_id':'mail','source':'email','complete':True}],[],LATER)
        finish_review(self.store,run.id,LATER)
        self.store.put('action','calendar-before-followup',{'operation':'calendar.read','status':'succeeded',
            'prepared_at':LATER,'payload':{'campaign_id':'campaign','account_ids':['a','b']},
            'result':{'complete':True,'items':[]}},None)
        self.send('a',index=1,sent_at='2026-10-24T12:00:00Z')
        metrics=calculate_results(self.store)
        self.assertEqual((metrics.reply_conversations_checked,metrics.reply_conversations_total),(1,2))
        self.assertEqual((metrics.calendar_accounts_checked,metrics.calendar_accounts_total),(1,2))

    def test_mixed_variants_preserve_one_shared_ambiguous_sequence(self):
        self.send('a',index=0,with_context=True)
        initial=refresh_outcome_observations(self.store)[0]
        rule=propose_outcome_rule(self.store,{'task':'email','objective':'Meeting','variant':'question'},'Try a question.',[initial.id])
        review_outcome_rule(self.store,rule.id,rule.revision,'approve','seller-review')
        plan=self.store.get('outreach_plan','plan');steps=plan.data['steps']
        next(step for step in steps if step['id']=='step-a-1')['learning_context']['variant']='other'
        self.store.put('outreach_plan',plan.id,dict(plan.data,steps=steps),plan.revision)
        self.send('a',index=1,with_context=True);self.review_reply()
        rows=refresh_outcome_observations(self.store)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(rows[0].data['exposures'][0]['versions']),2)
        self.assertTrue(rows[0].data['exposures'][0]['ambiguous_attribution'])
        self.assertNotIn('variant',rows[0].data['context'])
        self.assertEqual(rows[0].data['replied_account_count'],1)
        self.assertEqual(self.store.get('analysis',initial.id).data['status'],'superseded')
        self.assertEqual(relevant_outcome_rules(self.store,{'task':'email','objective':'Meeting','variant':'question'}),[])

class CalendarLearningRegression(StateTest):
    def test_shared_meeting_remains_in_both_campaign_learning(self):
        meeting_tests.MeetingTests.test_same_booking_can_link_two_campaigns_without_duplicate_record(self)
        self.assertEqual(len(_meeting_evidence(self.store,'campaign','account')),1)
        self.assertEqual(len(_meeting_evidence(self.store,'other','account')),1)

class WorkspaceDiagnosticRegressions(OutcomeFixture):
    workspace=True

    def test_status_exposes_durable_effect_when_report_repair_fails(self):
        message_id,intent,result=self.send(defer_result=True)
        with patch('aclad.workspace_files.os.replace',side_effect=OSError('disk full')):
            with self.assertRaises(GateError):record_delivery(self.store,result,message_id)
            status=dispatch(self.store,'status',{})
        self.assertEqual(status['results_report']['status'],'pending')
        self.assertTrue(any(row['id']==intent.action_id and row['data']['status']=='succeeded' for row in status['records']))

    def test_malformed_calendar_scope_rejected_before_intent(self):
        with self.assertRaises(GateError) as error:
            create_proposal(self.store,'calendar.read','calendar',['a'],{'campaign_id':'campaign','account_ids':[{'id':'a'}]})
        self.assertEqual(error.exception.code,'invalid_calendar_scope')

    def test_preexisting_malformed_calendar_scope_cannot_poison_projection(self):
        self.store.put('action','legacy-bad-calendar',{'operation':'calendar.read','status':'succeeded',
            'payload':{'campaign_id':'campaign','account_ids':[{'id':'a'}]},'result':{'complete':True,'items':[]}},None)
        status=dispatch(self.store,'status',{})
        snapshot=status if isinstance(status,dict) else asdict(status)
        self.assertTrue(any(row['id']=='legacy-bad-calendar' for row in snapshot['records']))
        self.assertTrue((self.workspace_root/'contexto/resultados.md').is_file())
