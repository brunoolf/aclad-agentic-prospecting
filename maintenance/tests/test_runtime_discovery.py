"""The operator can discover contracts before it has a seller workspace."""
import inspect
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RuntimeDiscoveryTests(unittest.TestCase):
    def call(self, directory, *arguments, text='{not-json'):
        env = dict(os.environ, ACLAD_REGISTRY_DIR=str(Path(directory) / 'registry'))
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2] / 'plugins/aclad-prospecting/runtime')
        return subprocess.run([sys.executable, '-m', 'aclad', *arguments], cwd=directory,
                              input=text, capture_output=True, text=True, env=env)

    def test_help_lists_operational_commands_without_state_or_json(self):
        with tempfile.TemporaryDirectory() as directory:
            response = self.call(directory, 'help')
            self.assertEqual(response.returncode, 0, response.stderr + response.stdout)
            result = json.loads(response.stdout)
            for name in ('setup-answer', 'generation-context', 'send-propose', 'meetings-record',
                         'outcome-propose', 'workspace-init', 'status'):
                self.assertIn(name, result['commands'])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_discovery_finishes_with_open_stdin_and_broken_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, ACLAD_REGISTRY_DIR=str(Path(directory) / 'registry'))
            env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2] / 'plugins/aclad-prospecting/runtime')
            process = subprocess.Popen([sys.executable, '-m', 'aclad', '--workspace',
                str(Path(directory) / 'missing'), 'schema', 'profile'], cwd=directory,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env)
            try:
                # Stdin remains open: discovery must not wait for JSON or resolve state.
                self.assertEqual(process.wait(timeout=5), 0)
                output, error = process.communicate()
                self.assertIn('seller', json.loads(output)['input_schema']['properties'], error)
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_command_schema_exposes_actual_required_and_optional_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            response = self.call(directory, 'schema', 'generation-context')
            self.assertEqual(response.returncode, 0, response.stderr + response.stdout)
            schema = json.loads(response.stdout)['input_schema']
            self.assertEqual(schema['required'], ['campaign_id', 'account_id'])
            self.assertEqual(set(schema['properties']),
                             {'campaign_id', 'account_id', 'contact_id', 'task', 'plan_step_id'})
            self.assertEqual(schema['properties']['task']['default'], 'email')
            self.assertFalse(schema['additionalProperties'])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_profile_schema_and_setup_fields_keep_real_nested_types(self):
        with tempfile.TemporaryDirectory() as directory:
            response = self.call(directory, 'schema', 'profile')
            self.assertEqual(response.returncode, 0, response.stderr + response.stdout)
            schema = json.loads(response.stdout)['input_schema']
            seller = schema['properties']['seller']['properties']
            self.assertEqual(seller['territory'], {'type': 'array', 'items': {'type': 'string'}})
            self.assertEqual(seller['portfolio'], {'type': 'string'})
            self.assertEqual(seller['writing_style'], {'type': 'string'})
            response = self.call(directory, 'schema', 'setup-answer')
            fields = json.loads(response.stdout)['fields']
            self.assertEqual(fields['partner.name'], {'type': 'string'})
            self.assertEqual(fields['partner.offerings']['type'], 'array')
            self.assertNotIn('partner.id', fields)
            # Dotted keys inside this object are literal package sections, not
            # paths that onboarding._assign can traverse as separate objects.
            self.assertNotIn('imported_review_pending.icp.criteria', fields)
            self.assertIn('icp.criteria', fields['imported_review_pending']['properties'])

    def test_dataclass_schema_preserves_optional_nullable_fields_without_running_factories(self):
        from aclad.contracts import _annotation_schema

        def default_items():
            raise AssertionError('Discovery must not execute a default factory')

        @dataclass
        class Envelope:
            operation: str
            account_identity: str | None = None
            items: list[str] = field(default_factory=default_items)

        schema = _annotation_schema(Envelope)
        self.assertEqual(schema['required'], ['operation'])
        self.assertEqual(schema['properties']['account_identity'],
                         {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'default': None})
        self.assertEqual(schema['properties']['items'], {'type': 'array', 'items': {'type': 'string'}})

    def test_send_schema_describes_external_ref_and_not_campaign_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            response = self.call(directory, 'schema', 'send-propose')
            self.assertEqual(response.returncode, 0, response.stderr + response.stdout)
            schema = json.loads(response.stdout)['input_schema']
            self.assertEqual(schema['required'], ['draft_ref', 'current_draft', 'preflight'])
            self.assertEqual(set(schema['properties']['draft_ref']['required']),
                             {'provider', 'tenant_id', 'connection_id', 'object_id'})

    def test_setup_examples_can_be_executed_without_guessing_field_types(self):
        with tempfile.TemporaryDirectory() as directory:
            response = self.call(directory, 'examples', 'setup-answer')
            self.assertEqual(response.returncode, 0, response.stderr + response.stdout)
            examples = json.loads(response.stdout)['examples']
            self.assertGreaterEqual(len(examples), 3)
            initialized = self.call(directory, '--workspace', directory, 'workspace-init',
                                    text='{"name":"Exemplo isolado"}')
            self.assertEqual(initialized.returncode, 0, initialized.stdout)
            for example in examples:
                saved = self.call(directory, '--workspace', directory, 'setup-answer',
                                  text=json.dumps(example['input']))
                self.assertEqual(saved.returncode, 0, saved.stdout)
            resumed = self.call(directory, '--workspace', directory, 'status', text='{}')
            profiles = [row for row in json.loads(resumed.stdout)['records']
                        if row['kind'] == 'profile' and row['id'] == 'current']
            self.assertEqual(profiles[0]['data']['seller']['territory'], ['SP', 'MG'])

    def test_examples_match_real_routing_and_message_validation(self):
        from aclad.commands import COMMANDS
        from importlib import import_module
        from aclad.messages import _message
        with tempfile.TemporaryDirectory() as directory:
            response = self.call(directory, 'examples')
            self.assertEqual(response.returncode, 0, response.stderr + response.stdout)
            examples = json.loads(response.stdout)['examples']
            for example in examples:
                command = example['command']
                if command not in COMMANDS:
                    continue
                module, name, with_store = COMMANDS[command]
                function = getattr(import_module('aclad.' + module), name)
                inspect.signature(function).bind(*([None] if with_store else []), **example['input'])
                if command == 'draft-propose':
                    self.assertEqual(_message(example['input']['message'])['attachments'], [])
                if command == 'send-propose':
                    self.assertEqual(_message(example['input']['current_draft'])['attachments'], [])

    def test_free_read_probe_route_only_returns_intent_without_state_changes(self):
        from aclad.commands import dispatch
        from aclad.models import GateError, Scope
        from aclad.store import Store
        with tempfile.TemporaryDirectory() as directory:
            from contextlib import closing
            with closing(Store(directory, Scope('partner', 'seller', 'instance'))) as store:
                from aclad.connections import discover
                capability = asdict(discover(store, [{'operation': 'crm.read',
                    'tool_name': 'observed.crm.read', 'connection_id': 'observed-connection',
                    'provider': 'example', 'cost': 'free', 'account_identity': 'seller-example'}], True)[0])
                before = store.snapshot()
                try:
                    intent = dispatch(store, 'connections-prepare-probe', {'capability': capability})
                except GateError as exc:
                    self.fail(f'Probe discovery route unavailable: {exc.code}')
                self.assertEqual(intent, {'operation': 'crm.read', 'tool_name': 'observed.crm.read',
                    'connection_id': 'observed-connection', 'read_only': True, 'cost': 'free'})
                self.assertEqual(store.snapshot(), before)

    def test_probe_route_preserves_paid_unknown_and_write_gates(self):
        from aclad.commands import dispatch
        from aclad.models import GateError, Scope
        from aclad.store import Store
        with tempfile.TemporaryDirectory() as directory:
            from contextlib import closing
            with closing(Store(directory, Scope('partner', 'seller', 'instance'))) as store:
                for operation, cost, code in [('crm.read', 'paid', 'probe_requires_cost_approval'),
                    ('crm.read', 'unknown', 'probe_requires_cost_approval'),
                    ('people.reveal_email', 'free', 'unsafe_probe'), ('email.send', 'free', 'unsafe_probe')]:
                    from aclad.connections import discover
                    capability = asdict(discover(store, [{'operation': operation,
                        'tool_name': 'observed.tool', 'connection_id': 'observed-connection',
                        'provider': 'example', 'cost': cost, 'account_identity': 'seller-example'}], True)[0])
                    before = store.snapshot()
                    with self.subTest(operation=operation, cost=cost), self.assertRaises(GateError) as raised:
                        dispatch(store, 'connections-prepare-probe', {'capability': capability})
                    self.assertEqual(raised.exception.code, code)
                    self.assertEqual(store.snapshot(), before)

    def test_portfolio_route_reads_review_state_without_mutating_profile_or_checkpoint(self):
        from aclad.commands import dispatch
        from aclad.models import GateError, Scope
        from aclad.profiles import save_profile
        from aclad.store import Store
        with tempfile.TemporaryDirectory() as directory:
            from contextlib import closing
            with closing(Store(directory, Scope('partner', 'seller', 'instance'))) as store:
                save_profile(store, {'partner': {'name': 'Parceiro Exemplo', 'offerings': [
                    {'id': 'netsuite', 'name': 'NetSuite', 'kind': 'netsuite', 'status': 'pending_review',
                     'source_ids': ['research-example']}]}})
                before = store.snapshot()
                try:
                    context = dispatch(store, 'portfolio-context', {})
                except GateError as exc:
                    self.fail(f'Portfolio discovery route unavailable: {exc.code}')
                self.assertEqual(context['offerings'], [])
                self.assertEqual(context['pending_offering_ids'], ['netsuite'])
                self.assertEqual(context['status'], 'review_required')
                self.assertEqual(len(context['digest']), 64)
                self.assertEqual(store.snapshot(), before)

    def test_unknown_command_is_actionable_and_does_not_initialize_a_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            response = self.call(directory, 'send-draft', text='{}')
            self.assertEqual(response.returncode, 2, response.stdout)
            error = json.loads(response.stdout)['error']
            self.assertEqual(error['code'], 'unknown_command')
            self.assertIn('help', error['hint'])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_unknown_discovery_topic_is_sanitized_without_state(self):
        with tempfile.TemporaryDirectory() as directory:
            response = self.call(directory, 'schema', 'invented-command')
            self.assertEqual(response.returncode, 2, response.stderr + response.stdout)
            self.assertTrue(response.stdout, 'Discovery must return a structured error')
            self.assertEqual(json.loads(response.stdout)['error']['code'], 'unknown_command')
            self.assertEqual(list(Path(directory).iterdir()), [])
