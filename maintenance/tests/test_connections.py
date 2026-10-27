import tempfile
import unittest
from aclad.models import Capability, GateError, Scope
from aclad.store import Store
from aclad.connections import discover, record_probe, connection_guidance, normalize_result, prepare_probe


class ConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, Scope('partner', 'seller', 'instance'))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def tool(self, **overrides):
        return {'tool_name': 'native.find', 'operation': 'crm.find_accounts',
                'connection_id': 'hubspot-one', 'provider': 'hubspot',
                'account_identity': 'tenant-a:user-a', 'cost': 'free', **overrides}

    def test_missing_tool_is_not_proof_of_absence(self):
        self.store.put('profile', 'current', {'tool_suggestions': ['hubspot']}, None)
        missing = discover(self.store, [], False)[0]
        self.assertEqual(missing.visibility, 'unknown')
        self.assertEqual(missing.auth, 'unknown')
        self.assertEqual(missing.operation, 'crm.read')
        self.assertEqual(discover(self.store, [], True)[0].visibility, 'not_visible')

    def test_operations_use_canonical_policy_names(self):
        operations = ['accounts.enrich', 'contacts.search', 'contacts.reveal', 'email.draft', 'crm.write_account']
        capabilities = discover(self.store, [self.tool(operation=operation) for operation in operations], True)
        self.assertEqual({cap.operation for cap in capabilities},
            {'companies.enrich', 'people.search', 'people.reveal_email', 'email.create_draft', 'crm.write'})

    def test_name_does_not_prove_authentication(self):
        capability = discover(self.store, [self.tool()], True)[0]
        self.assertEqual(capability.visibility, 'visible')
        self.assertEqual(capability.auth, 'unknown')
        self.assertEqual(capability.verification, 'declared')

    def test_probes_distinguish_401_403_and_success(self):
        capability = discover(self.store, [self.tool()], True)[0]
        failed = record_probe(self.store, capability, {'status_code': 401, 'connection_id': 'hubspot-one'})
        self.assertEqual(failed.auth, 'failed')
        denied = record_probe(self.store, capability, {'status_code': 403, 'connection_id': 'hubspot-one'})
        self.assertEqual(denied.permission, 'denied')
        verified = record_probe(self.store, capability, {'status_code': 200,
            'connection_id': 'hubspot-one', 'account_identity': 'tenant-a:user-a', 'evidence': 'read-probe-1'})
        self.assertEqual((verified.auth, verified.permission, verified.verification),
                         ('authenticated', 'allowed', 'verified'))

    def test_unknown_cost_or_write_probe_not_automatically_executed(self):
        for operation, cost in (('crm.find_accounts', 'unknown'), ('email.send', 'free')):
            capability = discover(self.store, [self.tool(operation=operation, cost=cost)], True)[0]
            with self.assertRaises(GateError):
                prepare_probe(capability)
        capability = discover(self.store, [self.tool()], True)[0]
        self.assertEqual(prepare_probe(capability)['tool_name'], 'native.find')

    def test_switch_identity_invalidates_verification_and_probe(self):
        old = discover(self.store, [self.tool()], True)[0]
        record_probe(self.store, old, {'status_code': 200, 'connection_id': 'hubspot-one',
            'account_identity': 'tenant-a:user-a', 'evidence': 'old'})
        new = discover(self.store, [self.tool(account_identity='tenant-b:user-b')], True)[0]
        self.assertEqual(new.verification, 'declared')
        self.assertEqual(new.auth, 'unknown')
        with self.assertRaises(GateError):
            record_probe(self.store, old, {'status_code': 200, 'connection_id': 'hubspot-one', 'evidence': 'late'})

    def test_guidance_does_not_invent_url(self):
        capability = discover(self.store, [self.tool()], True)[0]
        guidance = connection_guidance(capability, [{'provider': 'hubspot',
            'operations': ['crm.find_accounts'], 'surface': 'codex-local'}])
        self.assertNotIn('official_url', guidance)
        self.assertIn('login', guidance['next_step'])

    def test_normalize_rejects_other_connection_or_tenant(self):
        binding = {'tool_name': 'native.create', 'operation': 'crm.write_account',
            'connection_id': 'one', 'provider': 'hubspot', 'tenant_id': 'tenant-a',
            'result': {'status': 'status', 'object_id': 'id'}}
        for raw in ({'connection_id': 'two'}, {'connection_id': 'one', 'tenant_id': 'tenant-b'}):
            with self.assertRaises(GateError):
                normalize_result(binding, raw, 'action')
        result = normalize_result(binding, {'connection_id': 'one', 'tenant_id': 'tenant-a',
            'status': 'succeeded', 'id': '42'}, 'action')
        self.assertEqual(result.external_refs[0].object_id, '42')
        self.assertEqual(result.status, 'succeeded')
        self.assertEqual(normalize_result(binding, {'connection_id': 'one', 'tenant_id': 'tenant-a',
            'status': 'succeeded'}, 'action').status, 'unknown')

    def test_incomplete_probe_is_not_verified(self):
        capability = discover(self.store, [self.tool()], True)[0]
        result = record_probe(self.store, capability, {'status_code': 200, 'connection_id': 'hubspot-one'})
        self.assertEqual(result.verification, 'declared')


if __name__ == '__main__':
    unittest.main()
