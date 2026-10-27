import tempfile
import unittest
from aclad.models import GateError, Scope
from aclad.store import Store
from aclad.profiles import apply_import
from aclad.onboarding import next_question, save_answer, environment_readiness, selected_writing_examples


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scope = Scope('partner', 'seller', 'instance')
        self.store = Store(self.tmp.name, self.scope)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_portuguese_and_spanish_interviews_resume_without_repeating(self):
        self.assertEqual(next_question(self.store)['field'], 'language')
        save_answer(self.store, 'language', 'pt-BR')
        question = next_question(self.store)
        self.assertEqual(question['language'], 'pt-BR')
        self.assertIn('perfil', question['question'])
        save_answer(self.store, 'import_choice', 'start')
        save_answer(self.store, 'partner.name', 'Fictício')
        self.assertEqual(next_question(self.store)['field'], 'partner.website')
        save_answer(self.store, 'partner.website', 'https://partner.example')
        self.store.close()
        self.store = Store(self.tmp.name, self.scope)
        self.assertEqual(next_question(self.store)['field'], 'partner.products')
        save_answer(self.store, 'language', 'es')
        self.assertIn('productos', next_question(self.store)['question'])

    def test_import_filled_fields_skipped(self):
        apply_import(self.store, {'format': 'aclad-profile', 'version': 1,
            'created_at': '2026-10-22T00:00:00Z',
            'sections': {'partner': {'name': 'Fictício', 'website': 'https://partner.example', 'products': ['ERP']}}},
            ['partner.name', 'partner.website', 'partner.products'])
        save_answer(self.store, 'language', 'pt-BR')
        save_answer(self.store, 'import_choice', 'imported')
        self.assertEqual(next_question(self.store)['field'], 'partner.differentiators')

    def test_writing_examples_used_only_if_explicitly_selected(self):
        save_answer(self.store, 'seller.writing_examples', [{'id': 'one', 'text': 'Olá'}, {'id': 'two', 'text': 'Oi'}])
        self.assertEqual(selected_writing_examples(self.store), [])
        save_answer(self.store, 'seller.selected_example_ids', ['two'])
        self.assertEqual(selected_writing_examples(self.store), [{'id': 'two', 'text': 'Oi'}])
        with self.assertRaises(GateError):
            save_answer(self.store, 'seller.selected_example_ids', ['missing'])

    def test_unknown_fields_never_become_executable_configuration(self):
        with self.assertRaises(GateError):
            save_answer(self.store, 'hooks', 'run arbitrary command')

    def test_cloud_without_durable_state_is_limited(self):
        result = environment_readiness(self.store, {'surface': 'chatgpt-cloud', 'durable_state': False})
        self.assertEqual(result['status'], 'state_unavailable')
        self.assertFalse(result['can_schedule'])
        self.assertFalse(result['can_external_actions'])
        self.assertFalse(result['can_paid_actions'])

    def test_runtime_identity_tools_and_remote_guarantees_required(self):
        good = {'surface': 'codex-local', 'runtime_version': '3.11.0',
                'durable_state': True, 'identity_resolved': True,
                'tools_verified': True, 'scheduler_verified': True,
                'state_accessible_to_executor': True}
        self.assertEqual(environment_readiness(self.store, good)['status'], 'ready')
        self.assertFalse(environment_readiness(self.store, {**good, 'runtime_version': '3.10'})['can_external_actions'])
        cloud = environment_readiness(self.store, {**good, 'surface': 'claude-cloud'})
        self.assertEqual(cloud['status'], 'state_unavailable')
        self.assertTrue(environment_readiness(self.store, {**good, 'surface': 'claude-cloud',
            'remote_conditional_updates': True, 'remote_concurrency': True,
            'remote_durable_events': True, 'remote_recovery_verified': True,
            'remote_access_control_verified': True})['can_schedule'])

    def test_unknown_connection_keeps_independent_stages_available(self):
        result = environment_readiness(self.store, {'surface': 'cowork-local',
            'runtime_version': '3.13', 'durable_state': True, 'identity_resolved': True,
            'state_accessible_to_executor': True, 'tools_verified': False})
        self.assertEqual(result['status'], 'limited')
        self.assertTrue(result['can_configure'])
        self.assertFalse(result['can_external_actions'])
        self.assertIn('connect_tools', result['next_steps'])


if __name__ == '__main__':
    unittest.main()
