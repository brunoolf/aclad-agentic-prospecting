"""A restart exposes uncertainty instead of replaying an external effect."""
import tempfile
import unittest
from pathlib import Path
from dataclasses import asdict

from aclad.approvals import approve, create_proposal, prepare_action, record_result
from aclad.models import Capability, ExternalRef, GateError, Scope, ToolResult
from aclad.recovery import bootstrap, checkpoint
from aclad.store import Store

SCOPE = Scope('partner-a', 'seller-a', 'instance-a')
NOW = '2026-10-22T12:00:00Z'


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(self.path, SCOPE)
        self.store.put('account', 'a1', {'selected': True}, None)
        proposal = create_proposal(self.store, 'crm.write', 'conn1', ['a1'],
                                   {'external_revision': 'v1'})
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller-a', NOW)
        self.proposal = proposal
        self.cap = Capability('crm.write', 'write', 'conn1', 'visible',
                              'authenticated', 'allowed', 'verified', 'free')
        self.store.put('connection', 'crm', {'capability': asdict(self.cap),
                        'account_identity': 'seller@tenant'}, None)
        self.preflight = {'connection_id': 'conn1', 'checked_at': NOW,
                          'ownership_allowed': True, 'contact_allowed': True,
                          'opportunity_allowed': True, 'external_revision': 'v1'}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_bootstrap_marks_interrupted_effect_unknown_without_replay(self):
        intent = prepare_action(self.store, self.proposal.id, self.cap, self.preflight, NOW)
        self.store.close()
        self.store = Store(self.path, SCOPE)
        snapshot = bootstrap(self.store, now='2026-10-22T12:05:01Z')
        self.assertTrue(any(r.id == intent.action_id and r.data['status'] == 'unknown'
                            for r in snapshot.pending))
        with self.assertRaises(GateError) as caught:
            prepare_action(self.store, self.proposal.id, self.cap, self.preflight, NOW)
        self.assertEqual(caught.exception.code, 'reconciliation_required')
        sequence = snapshot.event_sequence
        self.assertEqual(bootstrap(self.store, now='2026-10-22T12:05:02Z').event_sequence, sequence)

    def test_live_action_is_not_recovered_by_concurrent_bootstrap(self):
        intent = prepare_action(self.store, self.proposal.id, self.cap, self.preflight, NOW)
        second = Store(self.path, SCOPE)
        try:
            snapshot = bootstrap(second, now='2026-10-22T12:04:59Z')
            action = next(r for r in snapshot.records if r.id == intent.action_id)
            self.assertEqual(action.data['status'], 'in_flight')
            self.assertFalse(action.data.get('recovery_required', False))
        finally:
            second.close()

    def test_result_releases_lease_after_recording_uncertainty(self):
        intent = prepare_action(self.store, self.proposal.id, self.cap, self.preflight, NOW)
        self.assertFalse(self.store.acquire_lease('action:' + intent.action_id, 'other', NOW, 1))
        record_result(self.store, ToolResult(intent.action_id, 'unknown', [], {}))
        self.assertTrue(self.store.acquire_lease('action:' + intent.action_id, 'other', NOW, 1))

    def test_checkpoint_retains_approval_and_external_references(self):
        intent = prepare_action(self.store, self.proposal.id, self.cap, self.preflight, NOW)
        record_result(self.store, ToolResult(intent.action_id, 'succeeded',
                      [ExternalRef('crm', 'tenant', 'conn1', 'crm-account-1')], {}))
        snapshot = checkpoint(self.store)
        action = next(r for r in snapshot.records if r.id == intent.action_id)
        proposal = next(r for r in snapshot.records if r.id == self.proposal.id)
        self.assertEqual(action.data['external_refs'][0]['object_id'], 'crm-account-1')
        self.assertEqual(proposal.data['approval']['digest'], self.proposal.digest)
        self.assertNotIn(intent.action_id, [r.id for r in snapshot.pending])

    def test_unknown_can_be_reconciled_with_confirmed_reference_without_new_intent(self):
        intent = prepare_action(self.store, self.proposal.id, self.cap, self.preflight, NOW)
        bootstrap(self.store, now='2026-10-22T12:05:01Z')
        result = ToolResult(intent.action_id, 'succeeded',
                  [ExternalRef('crm', 'tenant', 'conn1', 'crm-account-1')],
                  {'connection_id': 'conn1', 'reconciled': True})
        action = record_result(self.store, result)
        self.assertEqual(action.data['status'], 'succeeded')
        self.assertEqual(len(self.store.list('action')), 1)
        self.assertEqual(checkpoint(self.store).pending, [])


if __name__ == '__main__':
    unittest.main()
