"""Project setup boundaries, native probes and persisted operational intents."""
from contextlib import closing
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aclad.approvals import create_proposal, prepare_action
from aclad.connections import discover, prepare_bound_probe
from aclad.hooks import handle_hook
from aclad.models import Capability, GateError, Scope, now_utc
from aclad.store import Store
from aclad.workspace import initialize_workspace


class GuidedRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'Seller project'
        self.runtime = str(Path(__file__).resolve().parents[2] / 'plugins/aclad-prospecting/runtime')

    def test_workspace_init_requires_explicit_selected_folder(self):
        result = subprocess.run([sys.executable, '-m', 'aclad', 'workspace-init'],
            input='{"name":"Seller"}', capture_output=True, text=True, cwd=self.tmp.name,
            env={**os.environ, 'PYTHONPATH': self.runtime})
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'workspace_selection_required')
        self.assertFalse((Path(self.tmp.name) / '.aclad').exists())

    def test_project_native_action_requires_guided_setup_even_generic_proposal(self):
        info = initialize_workspace(self.root, 'Seller')
        with closing(Store(info['state_dir'], Scope(info['partner_id'], info['seller_id'], info['instance_id']))) as store:
            cap = Capability('accounts.search', 'native.search', 'data', 'visible',
                             'authenticated', 'allowed', 'verified', 'free')
            store.put('connection', 'data', {'capability': asdict(cap), 'account_identity': 'seller'}, None)
            proposal = create_proposal(store, 'accounts.search', 'data', ['campaign'], {'query': 'manufacturing'})
            with self.assertRaises(GateError) as error:
                prepare_action(store, proposal.id, cap, {}, now_utc())
            self.assertEqual(error.exception.code, 'setup_required')
            self.assertFalse(store.list('action'))

    def test_prepared_free_native_probe_has_one_matching_hook_dispatch(self):
        info = initialize_workspace(self.root, 'Seller')
        with closing(Store(info['state_dir'], Scope(info['partner_id'], info['seller_id'], info['instance_id']))) as store:
            cap = discover(store, [{'operation': 'email.read', 'tool_name': 'mail.profile',
                'connection_id': 'mail', 'provider': 'outlook', 'account_identity': 'seller',
                'cost': 'free'}], True)[0]
            # Preparation must permit an identity/read check before a verified
            # capability or campaign exists, without authorizing mail actions.
            prepare_bound_probe(store, cap, native_input={})
            event = {'session_id': 's', 'cwd': str(self.root), 'hook_event_name': 'PreToolUse',
                     'tool_name': 'mail.profile', 'tool_input': {}}
            with patch.dict(os.environ, {}, clear=True):
                allowed = handle_hook('codex', 'PreToolUse', event)
                replay = handle_hook('codex', 'PreToolUse', event)
            self.assertEqual(allowed, {})
            self.assertEqual(replay['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertFalse(store.list('action'))

    def test_probe_does_not_authorize_changed_native_arguments(self):
        info = initialize_workspace(self.root, 'Seller')
        with closing(Store(info['state_dir'], Scope(info['partner_id'], info['seller_id'], info['instance_id']))) as store:
            cap = discover(store, [{'operation': 'crm.read', 'tool_name': 'crm.read',
                'connection_id': 'crm', 'provider': 'netsuite', 'account_identity': 'seller',
                'cost': 'free'}], True)[0]
            prepare_bound_probe(store, cap, native_input={'query': 'SELECT id FROM employee LIMIT 1'})
            event = {'session_id': 's', 'cwd': str(self.root), 'hook_event_name': 'PreToolUse',
                     'tool_name': 'crm.read', 'tool_input': {'query': 'SELECT * FROM transaction'}}
            with patch.dict(os.environ, {}, clear=True):
                denied = handle_hook('claude', 'PreToolUse', event)
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')

class GuidedScheduleScopeTests(unittest.TestCase):
    def setUp(self):
        from tests.test_scheduling import SchedulingTests
        SchedulingTests.setUp(self)
        SchedulingTests.ready(self)
        from aclad.setup_flow import start_setup
        start_setup(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_schedule_cannot_watch_an_unregistered_campaign(self):
        from aclad.scheduling import schedule_request
        with self.assertRaises(GateError) as error:
            schedule_request(self.store, self.valid, self.capability)
        self.assertEqual(error.exception.code, 'schedule_campaign_required')
        self.assertFalse(self.store.list('schedule'))

    def test_empty_bound_campaign_can_be_watched_before_first_email(self):
        from aclad.onboarding import save_answer
        save_answer(self.store, 'icp.criteria.industries', [])
        save_answer(self.store, 'icp.criteria.subindustries', [])
        from aclad.icps import propose_icp, approve_icp, bind_icp
        from aclad.prospecting import open_campaign
        from aclad.scheduling import schedule_request
        icp = propose_icp(self.store, [{'field': 'country', 'operator': 'in',
            'value': ['BR'], 'basis': 'hypothesis'}], [], [], True, name='Brasil')
        icp = approve_icp(self.store, icp.id, icp.revision, 'seller')
        open_campaign(self.store, 'campaign', 'Apresentar NetSuite')
        bind_icp(self.store, 'campaign', icp.id, icp.revision)
        request = schedule_request(self.store, self.valid, self.capability)
        self.assertEqual(request['status'], 'request_prepared')
        self.assertFalse(self.store.list('message'))
        self.assertEqual(request['schedule']['scope_ids'], ['campaign'])
