"""An authenticated account may try an untested operation only with explicit bounded consent."""
from dataclasses import asdict
import unittest
from aclad.approvals import create_proposal, approve, prepare_action, record_result
from aclad.models import Capability, GateError, ToolResult, now_utc
from tests import test_guided_onboarding as onboarding_fixture


class OperationValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = onboarding_fixture.GuidedOnboardingTests('test_start_is_idempotent_and_resume_preserves_reviews')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.full_manual()
        self.store = self.fixture.store
        self.cap = Capability(**next(row.data['capability'] for row in self.store.list('connection')
            if row.data['capability']['operation'] == 'accounts.search'))
        self.assertEqual(self.cap.verification, 'declared')

    def proposal(self, bounded=True):
        from aclad.prospecting import prepare_prospecting
        return prepare_prospecting(self.store, 'campaign-one', 'accounts.search', ['campaign-one'],
                                   self.cap, {'max_items':5} if bounded else {})

    def test_first_free_search_is_explicitly_reviewed_before_trying_permission(self):
        proposal=self.proposal()
        self.assertIn('operation_validation', proposal.payload)
        with self.assertRaises(GateError) as error:
            prepare_action(self.store,proposal.id,self.cap,{},now_utc())
        self.assertEqual(error.exception.code,'approval_required')
        self.assertFalse(self.store.list('action'))
        approve(self.store,proposal.id,proposal.revision,proposal.digest,'seller',now_utc())
        intent=prepare_action(self.store,proposal.id,self.cap,{},now_utc())
        self.assertEqual(intent.operation,'accounts.search')
        self.assertEqual(self.cap.verification,'declared')
        record_result(self.store,ToolResult(intent.action_id,'succeeded',[],{'candidates':[]}))
        current=next(row.data['capability'] for row in self.store.list('connection')
                     if row.data['capability']['operation']=='accounts.search')
        self.assertEqual(current['verification'],'verified')
        self.assertEqual(current['permission'],'allowed')

    def test_permission_attempt_cannot_be_unbounded(self):
        proposal=self.proposal(False)
        approve(self.store,proposal.id,proposal.revision,proposal.digest,'seller',now_utc())
        with self.assertRaises(GateError) as error:
            prepare_action(self.store,proposal.id,self.cap,{},now_utc())
        self.assertEqual(error.exception.code,'validation_limit_required')

    def test_failed_attempt_does_not_promote_operation(self):
        proposal=self.proposal()
        approve(self.store,proposal.id,proposal.revision,proposal.digest,'seller',now_utc())
        intent=prepare_action(self.store,proposal.id,self.cap,{},now_utc())
        record_result(self.store,ToolResult(intent.action_id,'failed',[],{'definitive_no_effect':True}))
        current=next(row.data['capability'] for row in self.store.list('connection')
                     if row.data['capability']['operation']=='accounts.search')
        self.assertEqual(current['verification'],'declared')

    def test_permission_denial_cannot_be_reclassified_as_trial(self):
        row=next(row for row in self.store.list('connection') if row.data['capability']['operation']=='accounts.search')
        blocked={**row.data['capability'],'permission':'denied','verification':'failed'}
        self.store.put('connection',row.id,dict(row.data,capability=blocked),row.revision)
        proposal=create_proposal(self.store,'accounts.search',self.cap.connection_id,['campaign-one'],{'limits':{'max_items':1}})
        self.assertNotIn('operation_validation',proposal.payload)
        approve(self.store,proposal.id,proposal.revision,proposal.digest,'seller',now_utc())
        with self.assertRaises(GateError):
            prepare_action(self.store,proposal.id,Capability(**blocked),{},now_utc())

    def test_generic_proposal_cannot_bypass_campaign_and_approved_icp(self):
        cap = next(row.data['capability'] for row in self.store.list('connection')
                   if row.data['capability']['operation']=='accounts.search')
        from aclad.connections import record_probe
        verified=record_probe(self.store,Capability(**cap),{'connection_id':cap['connection_id'],
            'status_code':200,'account_identity':'seller@partner.example','evidence':'Synthetic operation proof'})
        proposal=create_proposal(self.store,'accounts.search',verified.connection_id,['campaign-one'],
                                 {'query':'Unscoped arbitrary companies','limits':{'max_items':5}})
        with self.assertRaises(GateError) as error:
            prepare_action(self.store,proposal.id,verified,{},now_utc())
        self.assertEqual(error.exception.code,'campaign_required')
        self.assertFalse(self.store.list('action'))

    def test_authenticated_untested_draft_channel_can_plan_before_approved_first_call(self):
        from aclad.outreach import _channel_available
        self.assertTrue(_channel_available(self.store,'email'))
