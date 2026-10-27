"""Fresh-registry CLI walkthrough: no direct Store writes seed the journey."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from aclad.models import now_utc

NOW = now_utc()


class FirstUseTests(unittest.TestCase):
    def test_first_use_to_saved_selected_accounts_and_new_chat_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = str(Path(directory) / 'persistent private registry')
            environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / 'plugins/aclad-prospecting/runtime'))
            def call(command, data=None):
                result = subprocess.run([sys.executable, '-m', 'aclad', '--registry-dir', registry, command],
                    input=json.dumps(data or {}), text=True, capture_output=True, cwd=directory, env=environment)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return json.loads(result.stdout)
            installation = call('instance-init', {'name': 'Synthetic partner seller'})
            self.assertEqual(call('instance-locate')['instance_id'], installation['instance_id'])
            call('setup-answer', {'field': 'language', 'value': 'pt-BR'})
            call('environment-check', {'facts': {'surface': 'codex-local', 'runtime_version': '3.13',
                'durable_state': True, 'state_accessible_to_executor': True, 'identity_resolved': True,
                'tools_verified': True}})
            caps = call('connections-discover', {'visible_tools': [
                {'operation': 'accounts.search', 'tool_name': 'fake.search', 'connection_id': 'data',
                 'provider': 'data', 'account_identity': 'seller', 'cost': 'free'},
                {'operation': 'crm.read', 'tool_name': 'fake.read', 'connection_id': 'crm',
                 'provider': 'crm', 'account_identity': 'seller', 'cost': 'free'}], 'visibility_complete': True})
            caps = {cap['operation']: call('connections-record-probe', {'capability': cap,
                'response': {'connection_id': cap['connection_id'], 'status_code': 200,
                    'account_identity': 'seller', 'evidence': 'Synthetic host probe'}}) for cap in caps}
            icp = call('icp-propose', {'criteria': [{'field': 'country', 'operator': 'in',
                'value': ['BR'], 'basis': 'hypothesis'}], 'exclusions': [], 'source_ids': [], 'strategic': True})
            icp = call('icp-approve', {'id': icp['id'], 'revision': icp['revision'], 'approved_by': 'seller'})
            call('campaign-create', {'campaign_id': 'c', 'objective': 'Synthetic nurturing'})
            call('icp-bind', {'campaign_id': 'c', 'icp_id': icp['id'], 'revision': icp['revision']})
            def observed(operation, ids, data):
                proposal = call('proposal-create', {'operation': operation, 'connection_id': caps[operation]['connection_id'],
                    'item_ids': ids, 'payload': {'campaign_id': 'c'}})
                intent = call('prepare-action', {'proposal_id': proposal['id'], 'capability': caps[operation], 'preflight': {}, 'now': NOW})
                call('record-result', {'result': {'action_id': intent['action_id'], 'status': 'succeeded', 'external_refs': [], 'data': data}})
                return intent['action_id']
            candidate = {'id': 'a', 'name': 'Synthetic company', 'source_at': NOW, 'country': 'BR',
                'external_ref': {'provider': 'data', 'tenant_id': 't', 'connection_id': 'data', 'object_id': 'remote-a'}}
            evidence = observed('accounts.search', ['c'], {'candidates': [candidate]})
            call('candidates-record', {'campaign_id': 'c', 'kind': 'account', 'candidates': [candidate], 'evidence_id': evidence})
            seller = {'provider': 'crm', 'tenant_id': 't', 'connection_id': 'crm', 'object_id': 'seller'}
            observation = {'account_id': 'a', 'owner_ref': seller, 'nurturing': True}
            evidence = observed('crm.read', ['a'], {'complete': True, 'observations': [observation]})
            call('account-check', {'campaign_id': 'c', 'account_id': 'a', 'observation': observation,
                'evidence_id': evidence, 'seller_ref': seller, 'rules': {}})
            call('accounts-select', {'campaign_id': 'c', 'account_ids': ['a']})
            snapshot = call('resume')
            account = next(row for row in snapshot['records'] if row['kind'] == 'account' and row['id'] == 'a')
            self.assertTrue(account['data']['selected'])
            self.assertEqual(account['data']['eligibility'], 'eligible')
            self.assertEqual(call('instance-locate')['state_dir'], installation['state_dir'])
