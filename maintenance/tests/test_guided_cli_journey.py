"""Seller-facing CLI setup through real domain commands, with isolated fake providers."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase


class GuidedCliJourneyTests(TestCase):
    def test_new_seller_two_icps_readonly_crm_and_resume(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / 'Seller folder with spaces'
            runtime = Path(__file__).resolve().parents[2] / 'plugins/aclad-prospecting/runtime'
            env = {**os.environ, 'PYTHONPATH': str(runtime)}
            def call(command, data=None, expected=0):
                result = subprocess.run([sys.executable, '-m', 'aclad', '--workspace', str(root), command],
                    input=json.dumps(data or {}), text=True, capture_output=True, cwd=directory, env=env)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return json.loads(result.stdout)
            def answer(field, value):
                return call('setup-answer', {'field': field, 'value': value})
            def complete(block):
                return call('setup-block-complete', {'block_id': block, 'reviewed_by': 'Seller'})
            call('workspace-init', {'name': 'Seller'})
            self.assertEqual(call('setup-next')['block_id'], 'workspace')
            call('environment-check', {'facts': {'surface': 'codex-local', 'runtime_version': '3.13',
                'durable_state': True, 'state_accessible_to_executor': True, 'identity_resolved': True,
                'tools_verified': True, 'scheduler_verified': False}})
            complete('workspace')
            for field, value in [('language', 'pt-BR'), ('partner.name', 'Synthetic Partner'),
                ('partner.website', 'https://partner.example.invalid'), ('seller.name', 'Seller'),
                ('seller.territory', ['BR']), ('seller.size_bands', ['Todos']),
                ('setup.prospecting_history', 'new'),
                ('partner.offerings', [{'id': 'netsuite', 'name': 'Oracle NetSuite', 'kind': 'netsuite',
                    'status': 'approved', 'approved_by': 'Seller', 'source_ids': ['synthetic-site-review']}])]:
                answer(field, value)
            complete('identity')
            self.assertEqual(call('setup-status')['current_block'], 'connections')
            blocked = call('setup-block-complete', {'block_id': 'connections', 'reviewed_by': 'Seller'}, 2)
            self.assertEqual(blocked['error']['code'], 'setup_block_incomplete')
            tools = []
            for provider, conn, operations in [('netsuite', 'crm', ['crm.read']),
                ('apollo', 'data', ['connection.identity', 'accounts.search', 'people.search']),
                ('outlook', 'mail', ['email.read', 'email.create_draft', 'email.send'])]:
                tools.extend({'provider': provider, 'connection_id': conn, 'operation': op,
                    'tool_name': 'synthetic.' + op, 'account_identity': 'seller@example.invalid',
                    'cost': 'free'} for op in operations)
            caps = call('connections-discover', {'visible_tools': tools, 'visibility_complete': True})
            for cap in caps:
                call('connections-record-probe', {'capability': cap, 'response': {
                    'connection_id': cap['connection_id'], 'status_code': 200,
                    'account_identity': 'seller@example.invalid', 'evidence': 'Synthetic native response'}})
            complete('connections')
            answer('seller.writing_style', 'Consultivo, médio, profissional próximo')
            complete('communication')
            answer('schedule_preferences.mode', 'manual')
            complete('automation')
            ids=[]
            for name, industry in [('Financeiro São Paulo', 'financial'), ('Indústria Brasil', 'manufacturing')]:
                answer('icp.criteria.industries', [industry])
                answer('icp.criteria.subindustries', [])
                icp = call('icp-propose', {'name': name, 'description': 'Perfil estratégico revisado',
                    'criteria': [{'field': 'industry', 'operator': 'in', 'value': [industry], 'basis': 'hypothesis'}],
                    'exclusions': [], 'source_ids': [], 'strategic': True})
                approved = call('icp-approve', {'id': icp['id'], 'revision': icp['revision'], 'approved_by': 'Seller'})
                ids.append((approved['id'], approved['revision']))
            complete('icps')
            call('campaign-create', {'campaign_id': 'financeiro', 'objective': 'Gerar reuniões para NetSuite'})
            call('icp-bind', {'campaign_id': 'financeiro', 'icp_id': ids[0][0], 'revision': ids[0][1]})
            complete('campaign')
            status = call('setup-status')
            self.assertTrue(status['complete'])
            self.assertTrue(status['connections']['crm_read_only'])
            self.assertEqual(call('icp-catalog')['total_count'], 2)
            self.assertEqual(call('campaign-context', {'campaign_id': 'financeiro'})['next_stage'], 'account_search')
            search_cap = next(cap for cap in call('connections-discover', {'visible_tools': tools, 'visibility_complete': True})
                              if cap['operation'] == 'accounts.search')
            proposal = call('prospecting-propose', {'campaign_id': 'financeiro', 'operation': 'accounts.search',
                'item_ids': ['financeiro'], 'capability': search_cap, 'limits': {'max_items': 10}})
            from aclad.models import now_utc
            intent = call('prepare-action', {'proposal_id': proposal['id'], 'capability': search_cap,
                'preflight': {}, 'now': now_utc()})
            call('record-result', {'result': {'action_id': intent['action_id'], 'status': 'succeeded',
                'external_refs': [], 'data': {'candidates': []}}})
            resumed = call('resume')
            self.assertTrue(resumed['setup']['complete'])
            self.assertTrue((root / 'contexto/configuracao.md').is_file())
            self.assertTrue((root / 'contexto/icps/index.md').is_file())
            self.assertTrue((root / 'campanhas/index.md').is_file())
            self.assertNotIn('Synthetic Partner', (root / 'contexto/resultados.md').read_text())
