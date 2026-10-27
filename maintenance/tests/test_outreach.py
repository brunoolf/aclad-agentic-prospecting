import tempfile
import unittest
from pathlib import Path

from aclad.learning import capture_correction
from aclad.models import GateError, Scope
from aclad.outreach import briefing_context, plan_outreach
from aclad.store import Store


class OutreachTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name), Scope('p', 's', 'i'))
        self.store.put('profile', 'current', {'partner': {'authorized_references': ['Approved customer']},
                       'seller': {'writing_style': 'Direct', 'language': 'pt-BR'}}, None)
        self.store.put('icp', 'icp1', {'status': 'approved'}, None)
        self.store.put('campaign', 'c1', {'icp_id': 'icp1', 'icp_revision': 1}, None)
        self.store.put('account', 'a1', {'selected': True, 'campaign_id': 'c1',
            'facts': [{'text': 'Expanded a factory', 'source': 'company-site', 'observed_at': '2026-10-21T12:00:00Z'},
                      {'text': 'Unverified claim'}],
            'hypotheses': ['May need inventory visibility'], 'missing': ['ERP'],
            'history': [], 'proof': ['Approved customer', 'Unapproved customer']}, None)
        self.store.put('contact', 'x1', {'selected': True, 'campaign_id': 'c1', 'account_id': 'a1'}, None)
        self.store.put('connection', 'mail', {'capability': {'operation': 'email.create_draft',
            'connection_id': 'mail1', 'visibility': 'visible', 'auth': 'authenticated',
            'permission': 'allowed', 'verification': 'verified'}}, None)
        self.step = {'id': 'step1', 'contact_id': 'x1', 'channel': 'email',
            'objective': 'Meeting', 'angle': 'Inventory', 'delay_days': 3,
            'cadence_basis': {'type': 'seller_decision', 'evidence_id': 'decision-1'},
            'stop_conditions': ['reply', 'do_not_contact']}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_briefing_separates_facts_hypotheses_and_authorized_proof(self):
        capture_correction(self.store, 'long', 'short', 'personal:briefing', True, 'e1')
        capture_correction(self.store, 'old', 'unconfirmed', 'personal:briefing', False, 'e2')
        context = briefing_context(self.store, 'c1', 'a1')
        self.assertEqual([f['text'] for f in context['facts']], ['Expanded a factory'])
        self.assertEqual(context['hypotheses'], ['May need inventory visibility'])
        self.assertEqual(context['approved_proof'], ['Approved customer'])
        self.assertEqual(context['history'], [])
        self.assertEqual([r['instruction'] for r in context['personal_rules']], ['short'])
        self.assertIn('ERP', context['missing'])

    def test_briefing_recovers_reviewed_methodology_for_its_stage(self):
        campaign = self.store.get('campaign', 'c1')
        rule = {'id': 'method1', 'source_file': 'guide.pdf', 'source_page': 1,
            'source_date': None, 'reviewed_at': '2026-10-22T00:00:00Z', 'stage': 'briefing',
            'industry': None, 'persona': None, 'audience': 'partner', 'status': 'approved',
            'rule': 'Label need as hypothesis', 'valid_until': None}
        self.store.put('campaign', 'c1', dict(campaign.data, playbooks=[rule]), campaign.revision)
        context = briefing_context(self.store, 'c1', 'a1')
        self.assertEqual([r['id'] for r in context['playbooks']], ['method1'])

    def test_unsourced_cadence_and_unavailable_channel_are_blocked(self):
        for change, expected in [({'cadence_basis': {}}, 'cadence_basis_required'),
                                 ({'channel': 'sms'}, 'channel_unavailable'),
                                 ({'delay_days': -1}, 'invalid_delay')]:
            with self.subTest(change=change), self.assertRaises(GateError) as caught:
                plan_outreach(self.store, 'c1', [dict(self.step, **change)], [])
            self.assertEqual(caught.exception.code, expected)
        self.assertEqual(self.store.list('outreach_plan'), [])

    def test_plan_preserves_campaign_icp_and_contact_without_external_action(self):
        plan = plan_outreach(self.store, 'c1', [self.step], [])
        self.assertEqual(plan.data['icp_id'], 'icp1')
        self.assertEqual(plan.data['icp_revision'], 1)
        self.assertEqual(plan.data['steps'][0]['contact_id'], 'x1')
        self.assertEqual(self.store.list('action'), [])

    def test_campaign_keeps_older_approved_icp_version(self):
        icp = self.store.get('icp', 'icp1')
        self.store.put('icp', icp.id, dict(icp.data, approved_versions={'1': {'revision': 1, 'criteria': {'industry': 'Manufacturing'}}}), icp.revision)
        plan = plan_outreach(self.store, 'c1', [self.step], [])
        self.assertEqual(plan.data['icp_revision'], 1)

    def test_other_campaign_contact_and_stale_icp_are_blocked(self):
        contact = self.store.get('contact', 'x1')
        self.store.put('contact', 'x1', dict(contact.data, campaign_id='other'), contact.revision)
        with self.assertRaises(GateError) as caught:
            plan_outreach(self.store, 'c1', [self.step], [])
        self.assertEqual(caught.exception.code, 'selection_required')


if __name__ == '__main__':
    unittest.main()
