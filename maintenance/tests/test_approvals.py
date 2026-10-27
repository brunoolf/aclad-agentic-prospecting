"""Execution gates must fail closed before a native tool can be invoked."""
import copy
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from aclad.approvals import approve, create_proposal, prepare_action, record_result
from aclad.models import Capability, ExternalRef, GateError, Scope, ToolResult
from aclad.store import Store

SCOPE = Scope('partner-a', 'seller-a', 'instance-a')
NOW = '2026-10-22T12:00:00Z'


class ApprovalsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name), SCOPE)
        self.store.put('account', 'a1', {'selected': True, 'campaign_id': 'c1'}, None)
        self.cap = Capability('crm.write', 'crm_upsert', 'conn1', 'visible',
                              'authenticated', 'allowed', 'verified', 'free')
        for operation in ('crm.write', 'companies.enrich', 'accounts.search', 'email.create_draft', 'email.send'):
            self.store.put('connection', operation, {'account_identity': 'seller@tenant',
                'capability': asdict(replace(self.cap, operation=operation))}, None)
        self.preflight = {'checked_at': NOW, 'connection_id': 'conn1',
                          'ownership_allowed': True, 'contact_allowed': True,
                          'opportunity_allowed': True, 'external_revision': 'v1'}
        self.payload = {'campaign_id': 'c1', 'external_revision': 'v1',
                        'owner': 'crm-user-1', 'after': {'industry': 'Manufacturing'}}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def proposal(self, operation='crm.write', payload=None, ids=None, connection='conn1'):
        return create_proposal(self.store, operation, connection, ids or ['a1'],
                               self.payload if payload is None else payload)

    def authorize(self, proposal):
        return approve(self.store, proposal.id, proposal.revision, proposal.digest,
                       'seller-a', NOW)

    def assert_gate(self, code, function, *args, **kwargs):
        with self.assertRaises(GateError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_canonical_digest_ignores_key_order_and_covers_scope(self):
        first = self.proposal(payload={'z': 1, 'a': {'b': 2, 'c': 3}})
        reordered = self.proposal(payload={'a': {'c': 3, 'b': 2}, 'z': 1})
        self.assertEqual(first.digest, reordered.digest)
        variants = [self.proposal(operation='companies.enrich'),
                    self.proposal(connection='conn2'),
                    self.proposal(ids=['a2']), self.proposal(payload={'after': {'industry': 'Services'}})]
        self.assertTrue(all(p.digest != self.proposal().digest for p in variants))

    def test_approval_is_bound_to_revision_digest_and_proposal(self):
        first = self.proposal()
        self.assert_gate('approval_mismatch', approve, self.store, first.id, 99,
                         first.digest, 'seller-a', NOW)
        self.assert_gate('approval_mismatch', approve, self.store, first.id, 1,
                         'wrong-digest', 'seller-a', NOW)
        self.authorize(first)
        second = self.proposal()
        self.assert_gate('approval_required', prepare_action, self.store, second.id,
                         self.cap, self.preflight, NOW)

    def test_unapproved_write_and_unselected_item_are_blocked(self):
        proposal = self.proposal()
        self.assert_gate('approval_required', prepare_action, self.store, proposal.id,
                         self.cap, self.preflight, NOW)
        self.authorize(proposal)
        self.store.put('account', 'a1', {'selected': False, 'campaign_id': 'c1'}, 1)
        self.assert_gate('selection_required', prepare_action, self.store, proposal.id,
                         self.cap, self.preflight, NOW)
        self.assertEqual(self.store.list('action'), [])

    def test_mutating_approved_content_invalidates_authorization(self):
        for field in ('operation', 'connection_id', 'item_ids', 'payload'):
            with self.subTest(field=field):
                proposal = self.proposal()
                self.authorize(proposal)
                record = self.store.get('proposal', proposal.id)
                data = copy.deepcopy(record.data)
                data[field] = {'operation': 'email.send', 'connection_id': 'conn2',
                               'item_ids': ['a2'], 'payload': {'body': 'changed'}}[field]
                self.store.put('proposal', proposal.id, data, record.revision)
                self.assert_gate('proposal_changed', prepare_action, self.store,
                                 proposal.id, self.cap, self.preflight, NOW)

    def test_capability_and_connection_must_match_verified_access(self):
        proposal = self.proposal()
        self.authorize(proposal)
        for changes, code in [({'connection_id': 'other'}, 'connection_mismatch'),
                              ({'operation': 'email.send'}, 'operation_mismatch'),
                              ({'verification': 'declared'}, 'capability_unverified'),
                              ({'permission': 'denied'}, 'capability_unverified'),
                              ({'auth': 'expired'}, 'capability_unverified')]:
            with self.subTest(changes=changes):
                self.assert_gate(code, prepare_action, self.store, proposal.id,
                                 replace(self.cap, **changes), self.preflight, NOW)

    def test_write_requires_fresh_matching_and_allowed_preflight(self):
        proposal = self.proposal()
        self.authorize(proposal)
        cases = [({'checked_at': '2026-10-22T11:54:59Z'}, 'preflight_stale'),
                 ({'checked_at': '2026-10-22T12:00:01Z'}, 'preflight_stale'),
                 ({'connection_id': 'other'}, 'connection_mismatch'),
                 ({'external_revision': 'v2'}, 'external_changed'),
                 ({'ownership_allowed': False}, 'ownership_blocked'),
                 ({'contact_allowed': False}, 'contact_blocked'),
                 ({'opportunity_allowed': False}, 'opportunity_blocked')]
        for changes, code in cases:
            with self.subTest(changes=changes):
                self.assert_gate(code, prepare_action, self.store, proposal.id,
                                 self.cap, dict(self.preflight, **changes), NOW)
        self.assert_gate('preflight_required', prepare_action, self.store,
                         proposal.id, self.cap, {}, NOW)

    def test_paid_and_unknown_cost_require_approved_limits(self):
        capability = replace(self.cap, operation='companies.enrich', cost='unknown')
        binding = self.store.get('connection', 'companies.enrich')
        self.store.put('connection', binding.id, dict(binding.data, capability=asdict(capability)), binding.revision)
        proposal = self.proposal(operation='companies.enrich', payload={})
        self.authorize(proposal)
        self.assert_gate('cost_limit_required', prepare_action, self.store, proposal.id,
                         capability, {}, NOW)
        bounded = self.proposal(operation='companies.enrich', payload={'limits': {
            'max_items': 1, 'max_credits': '5', 'cost_known': False,
            'cost_acknowledged': True}})
        self.authorize(bounded)
        intent = prepare_action(self.store, bounded.id, capability, {}, NOW)
        self.assertEqual(intent.payload['limits']['max_credits'], '5')

    def test_free_search_needs_no_approval_and_unknown_operation_is_rejected(self):
        proposal = self.proposal(operation='accounts.search', payload={}, ids=['query'])
        intent = prepare_action(self.store, proposal.id,
                                replace(self.cap, operation='accounts.search'), {}, NOW)
        self.assertEqual(intent.operation, 'accounts.search')
        self.assert_gate('operation_not_allowed', create_proposal, self.store,
                         'execute_arbitrary_code', 'conn1', [], {})

    def test_replaced_connection_identity_cannot_reuse_old_approval(self):
        proposal = self.proposal()
        self.authorize(proposal)
        binding = self.store.get('connection', 'crm.write')
        self.store.put('connection', binding.id, dict(binding.data, account_identity='different@tenant'), binding.revision)
        self.assert_gate('connection_mismatch', prepare_action, self.store, proposal.id,
                         self.cap, self.preflight, NOW)

    def test_capability_without_persisted_verified_binding_is_blocked(self):
        proposal = self.proposal(connection='missing')
        self.authorize(proposal)
        self.assert_gate('capability_unverified', prepare_action, self.store, proposal.id,
                         replace(self.cap, connection_id='missing'),
                         dict(self.preflight, connection_id='missing'), NOW)

    def test_cancelled_free_proposal_cannot_execute(self):
        proposal = self.proposal(operation='accounts.search', payload={}, ids=['query'])
        record = self.store.get('proposal', proposal.id)
        self.store.put('proposal', proposal.id, dict(record.data, status='cancelled'), record.revision)
        self.assert_gate('proposal_not_executable', prepare_action, self.store, proposal.id,
                         replace(self.cap, operation='accounts.search'), {}, NOW)

    def test_draft_approval_does_not_authorize_send(self):
        draft = self.proposal(operation='email.create_draft')
        self.authorize(draft)
        send = self.proposal(operation='email.send')
        self.assert_gate('approval_required', prepare_action, self.store, send.id,
                         replace(self.cap, operation='email.send'), self.preflight, NOW)

    def test_intent_is_persisted_before_return_and_cannot_be_repeated(self):
        proposal = self.proposal()
        self.authorize(proposal)
        intent = prepare_action(self.store, proposal.id, self.cap, self.preflight, NOW)
        action = self.store.get('action', intent.action_id)
        self.assertEqual(action.data['status'], 'in_flight')
        self.assertEqual(action.data['digest'], proposal.digest)
        self.assert_gate('action_already_started', prepare_action, self.store,
                         proposal.id, self.cap, self.preflight, NOW)

    def test_commit_failure_never_returns_intent_or_leaves_action(self):
        proposal = self.proposal()
        self.authorize(proposal)
        original = self.store.transaction
        @contextmanager
        def fail_commit():
            with original():
                yield
                raise sqlite3.OperationalError('simulated storage failure')
        with patch.object(self.store, 'transaction', fail_commit):
            with self.assertRaises(sqlite3.OperationalError):
                prepare_action(self.store, proposal.id, self.cap, self.preflight, NOW)
        self.assertEqual(self.store.list('action'), [])

    def test_result_checks_connection_and_preserves_confirmed_external_ref(self):
        proposal = self.proposal()
        self.authorize(proposal)
        intent = prepare_action(self.store, proposal.id, self.cap, self.preflight, NOW)
        wrong = ToolResult(intent.action_id, 'succeeded',
                           [ExternalRef('crm', 'tenant1', 'other', 'remote1')], {})
        self.assert_gate('connection_mismatch', record_result, self.store, wrong)
        result = ToolResult(intent.action_id, 'succeeded',
                            [ExternalRef('crm', 'tenant1', 'conn1', 'remote1')], {})
        action = record_result(self.store, result)
        self.assertEqual(action.data['status'], 'succeeded')
        self.assertEqual(action.data['external_refs'][0]['object_id'], 'remote1')
        self.assertEqual(record_result(self.store, result), action)

    def test_success_without_external_evidence_stays_unknown(self):
        proposal = self.proposal()
        self.authorize(proposal)
        intent = prepare_action(self.store, proposal.id, self.cap, self.preflight, NOW)
        action = record_result(self.store, ToolResult(intent.action_id, 'succeeded', [], {}))
        self.assertEqual(action.data['status'], 'unknown')
        self.assert_gate('reconciliation_required', prepare_action, self.store,
                         proposal.id, self.cap, self.preflight, NOW)


if __name__ == '__main__':
    unittest.main()
