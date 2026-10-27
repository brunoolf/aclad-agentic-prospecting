"""Adversarial regressions against real local persistence and action gates."""
from dataclasses import asdict, replace
from pathlib import Path

from aclad.approvals import create_proposal, prepare_action
from aclad.commands import dispatch
from aclad.connections import discover, record_probe
from aclad.models import GateError
from aclad.workspace import initialize_workspace, locate_workspace
from tests.support import NOW, StateTest


class ConnectionAuthenticationRegressionTests(StateTest):
    def connections(self):
        tools = [
            {'provider': 'outlook', 'connection_id': connection, 'operation': operation,
             'tool_name': connection + '.' + operation, 'account_identity': identity,
             'cost': 'free'}
            for connection, identity, operations in (
                ('mail', 'seller@partner.example', ('email.read', 'calendar.read')),
                ('other-mail', 'other@partner.example', ('calendar.read',)),
            ) for operation in operations
        ]
        capabilities = discover(self.store, tools, True)
        identities = {tool['connection_id']: tool['account_identity'] for tool in tools}
        verified = []
        for capability in capabilities:
            verified.append(record_probe(self.store, capability, {
                'connection_id': capability.connection_id, 'status_code': 200,
                'account_identity': identities[capability.connection_id], 'evidence': 'fixture-identity',
            }))
        return {(cap.connection_id, cap.operation): cap for cap in verified}

    def calendar_intent(self, capability):
        proposal = create_proposal(self.store, 'calendar.read', capability.connection_id,
                                   ['campaign'], {'campaign_id': 'campaign'})
        return prepare_action(self.store, proposal.id, capability, {}, NOW)

    def test_shared_mailbox_401_blocks_previously_verified_sibling_action(self):
        """Leaving a sibling verified after revoked authentication must fail."""
        capabilities = self.connections()
        record_probe(self.store, capabilities['mail', 'email.read'], {
            'connection_id': 'mail', 'status_code': 401,
        })
        with self.assertRaises(GateError) as caught:
            self.calendar_intent(capabilities['mail', 'calendar.read'])
        self.assertEqual(caught.exception.code, 'capability_unverified')
        self.assertEqual(self.store.list('action'), [])
        # Independent connected accounts retain their own proof.
        self.assertEqual(self.calendar_intent(capabilities['other-mail', 'calendar.read']).operation,
                         'calendar.read')

    def test_operation_permission_403_keeps_verified_sibling_action_available(self):
        """An operation-specific denial must not revoke unrelated permissions."""
        capabilities = self.connections()
        record_probe(self.store, capabilities['mail', 'email.read'], {
            'connection_id': 'mail', 'status_code': 403,
        })
        self.assertEqual(self.calendar_intent(capabilities['mail', 'calendar.read']).operation,
                         'calendar.read')


class MissingWorkspaceMarkerRegressionTests(StateTest):
    def test_missing_child_marker_cannot_resume_parent_seller(self):
        """Skipping a damaged child workspace must not choose another seller."""
        parent = Path(self.tmp.name) / 'parent-seller'
        child = parent / 'child-seller'
        outer = initialize_workspace(parent, 'Parent seller')
        inner = initialize_workspace(child, 'Child seller')
        self.assertNotEqual(outer['seller_id'], inner['seller_id'])
        (child / '.aclad/workspace.json').unlink()
        paths = [parent / '.aclad/state.sqlite', child / '.aclad/state.sqlite']
        original = [path.read_bytes() for path in paths]
        with self.assertRaises(GateError) as caught:
            locate_workspace(child)
        self.assertEqual(caught.exception.code, 'state_unavailable')
        self.assertEqual([path.read_bytes() for path in paths], original)
        self.assertFalse((child / '.aclad/workspace.json').exists())

    def test_normal_child_directory_resumes_existing_parent_workspace(self):
        """Fail closed only at an ACLAD boundary, not ordinary subdirectories."""
        parent = Path(self.tmp.name) / 'seller'
        identity = initialize_workspace(parent, 'Seller')
        child = parent / 'campaigns' / 'hotels'
        child.mkdir(parents=True)
        self.assertEqual(locate_workspace(child)['seller_id'], identity['seller_id'])


class BoundProbeRegressionTests(StateTest):
    def discovered(self, **overrides):
        return discover(self.store, [{'provider': 'outlook', 'connection_id': 'mail',
            'tool_name': 'mail.read', 'operation': 'email.read', 'cost': 'free',
            'account_identity': 'seller@partner.example', **overrides}], True)[0]

    def probe(self, capability):
        return dispatch(self.store, 'connections-prepare-probe', {'capability': asdict(capability)})

    def test_probe_cannot_replace_inventory_paid_or_unknown_cost_with_free(self):
        """A caller's free claim cannot bypass the inventory's cost approval gate."""
        for cost in ('paid', 'unknown'):
            with self.subTest(cost=cost):
                capability = self.discovered(cost=cost)
                before = self.store.snapshot()
                with self.assertRaises(GateError) as caught:
                    self.probe(replace(capability, cost='free'))
                self.assertEqual(caught.exception.code, 'capability_unverified')
                self.assertEqual(self.store.snapshot(), before)

    def test_initial_free_probe_reads_canonical_binding_without_bootstrap(self):
        """Probing before authentication must remain possible without recovery effects."""
        capability = self.discovered()
        self.store.put('action', 'interrupted', {'status': 'in_flight', 'operation': 'email.send',
            'prepared_at': '2020-01-01T00:00:00Z'}, None)
        before = self.store.snapshot()
        self.assertEqual(self.probe(capability), {'operation': 'email.read', 'tool_name': 'mail.read',
            'connection_id': 'mail', 'read_only': True, 'cost': 'free'})
        self.assertEqual(self.store.snapshot(), before)

    def test_probe_rejects_foreign_or_reconnected_binding(self):
        """An absent or obsolete account generation must not yield a probe intent."""
        previous = self.discovered()
        for capability in (replace(previous, connection_id='foreign'),
                           replace(previous, tool_name='unobserved.read')):
            with self.subTest(capability=capability):
                with self.assertRaises(GateError) as caught:
                    self.probe(capability)
                self.assertEqual(caught.exception.code, 'capability_unverified')
        self.discovered(account_identity='another@partner.example')
        with self.assertRaises(GateError) as caught:
            self.probe(previous)
        self.assertEqual(caught.exception.code, 'capability_unverified')
