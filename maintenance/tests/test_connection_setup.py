import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from aclad import connections, onboarding
from aclad.models import GateError, Scope
from aclad.store import Store


class ConnectionSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, Scope('partner', 'seller', 'instance'))
        self.catalog = json.loads((Path(__file__).resolve().parents[2] / 'plugins/aclad-prospecting/references/connector-catalog.json').read_text())

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def checklist(self, providers):
        self.assertTrue(callable(getattr(connections, 'connection_checklist', None)), 'persistent checklist missing')
        return connections.connection_checklist(self.store, providers, self.catalog)

    def tool(self, **changes):
        return {'provider': 'hubspot', 'connection_id': 'native-one', 'operation': 'crm.read',
                'tool_name': 'native.read', 'account_identity': 'tenant:user', 'cost': 'free', **changes}

    def test_unknown_provider_has_persistent_research_next_step(self):
        row = self.checklist(['Meu CRM'])[0]
        self.assertFalse(row['known'])
        self.assertEqual(row['support_level'], 'unknown')
        self.assertIn('pesquis', row['next_step'].lower())
        saved = connections.update_connection_step(self.store, 'Meu CRM', 'blocked', 'Confirmar produto e consultar administrador')
        self.assertEqual(self.checklist(['Meu CRM'])[0]['next_step'], saved.data['next_step'])
        self.assertEqual(self.checklist(['Meu CRM'])[0]['status'], 'blocked')

    def test_known_is_separate_from_discovered_and_authenticated(self):
        row = self.checklist(['hubspot'])[0]
        self.assertTrue(row['known'])
        self.assertFalse(row['tools_discovered'])
        self.assertFalse(row['authenticated'])
        self.assertNotEqual(row['support_level'], 'verified')
        self.assertIn('codex', row['host_paths'])
        self.assertIn('claude', row['host_paths'])

    def test_step_saved_before_first_inventory_is_not_lost_and_installation_is_separate(self):
        connections.update_connection_step(self.store, 'new-crm', 'blocked', 'Pedir habilitação ao administrador')
        self.assertEqual(self.checklist(['new-crm'])[0]['status'], 'blocked')
        connections.update_connection_step(self.store, 'hubspot', 'installed', 'Habilitar nesta conversa', 'host-installation')
        installed = self.checklist(['hubspot'])[0]
        self.assertTrue(installed['installed'])
        self.assertIsNone(installed['enabled'])
        self.assertFalse(installed['authenticated'])
        connections.update_connection_step(self.store, 'hubspot', 'enabled', 'Conectar conta', 'host-enabled')
        enabled = self.checklist(['hubspot'])[0]
        self.assertTrue(enabled['enabled'])
        self.assertFalse(enabled['authenticated'])

    def test_2xx_without_identity_cannot_verify(self):
        cap = connections.discover(self.store, [self.tool(account_identity=None)], True)[0]
        result = connections.record_probe(self.store, cap, {'status_code': 200,
            'connection_id': cap.connection_id, 'evidence': 'read-1'})
        self.assertEqual(result.verification, 'declared')
        self.assertEqual(result.auth, 'unknown')

    def test_declared_inventory_identity_does_not_replace_identity_in_probe_response(self):
        cap = connections.discover(self.store, [self.tool()], True)[0]
        result = connections.record_probe(self.store, cap, {'status_code': 200,
            'connection_id': cap.connection_id, 'evidence': 'generic-read-without-identity'})
        self.assertEqual((result.auth, result.permission, result.verification),
                         ('unknown', 'unknown', 'declared'))
        saved = next(row for row in self.store.list('connection')
                     if row.data['capability']['connection_id'] == cap.connection_id)
        self.assertIsNone(saved.data['probe']['account_identity'])

    def test_catalog_adds_required_operation_and_invalidates_derived_ready(self):
        cap = connections.discover(self.store, [self.tool(provider='outlook', operation='email.read')], True)[0]
        connections.record_probe(self.store, cap, {'status_code': 200, 'connection_id': cap.connection_id,
            'account_identity': 'tenant:user', 'evidence': 'identity-read'})
        catalog = [{'provider': 'outlook', 'operations': ['email.read']}]
        ready = connections.connection_checklist(self.store, ['outlook'], catalog)[0]
        self.assertEqual(ready['status'], 'ready')
        expanded = [{'provider': 'outlook', 'operations': ['email.read', 'email.send']}]
        for _ in range(2):
            pending = connections.connection_checklist(self.store, ['outlook'], expanded)[0]
            self.assertEqual(pending['status'], 'partially_verified')
            self.assertNotEqual(pending['inventory_signature'], ready['inventory_signature'])
            self.assertEqual(pending['pending_operations'], ['email.send'])
            self.assertIn('envio', pending['next_step'].lower())

    def test_probe_rejects_response_identity_different_from_inventory(self):
        cap = connections.discover(self.store, [self.tool()], True)[0]
        with self.assertRaises(GateError):
            connections.record_probe(self.store, cap, {'status_code': 200,
                'connection_id': cap.connection_id, 'account_identity': 'other:user', 'evidence': 'read-1'})

    def test_reconnect_recomputes_checklist_instead_of_reusing_ready_step(self):
        cap = connections.discover(self.store, [self.tool()], True)[0]
        connections.record_probe(self.store, cap, {'status_code': 200, 'connection_id': cap.connection_id,
            'account_identity': 'tenant:user', 'evidence': 'read-1'})
        self.assertTrue(self.checklist(['hubspot'])[0]['authenticated'])
        connections.discover(self.store, [self.tool(account_identity='tenant:other')], True)
        row = self.checklist(['hubspot'])[0]
        self.assertFalse(row['authenticated'])
        self.assertNotEqual(row['status'], 'ready')
        self.assertTrue(row['next_step'])

    def test_readiness_does_not_combine_operations_from_different_accounts(self):
        caps = connections.discover(self.store, [self.tool(), self.tool(connection_id='native-two',
            operation='crm.write', tool_name='native.write', account_identity='other:user')], True)
        for cap in caps:
            identity = 'tenant:user' if cap.connection_id == 'native-one' else 'other:user'
            connections.record_probe(self.store, cap, {'status_code': 200,
                'connection_id': cap.connection_id, 'account_identity': identity, 'evidence': 'synthetic-operation-proof'})
        row = self.checklist(['hubspot'])[0]
        self.assertEqual(row['status'], 'partially_verified')
        self.assertEqual(set(row['identities']), {'tenant:user', 'other:user'})

    def test_probe_cannot_replace_inventory_cost_with_caller_supplied_free_capability(self):
        cap = connections.discover(self.store, [self.tool(cost='paid')], True)[0]
        result = connections.record_probe(self.store, replace(cap, cost='free'), {'status_code': 200,
            'connection_id': cap.connection_id, 'account_identity': 'tenant:user', 'evidence': 'synthetic-operation-proof'})
        self.assertEqual(result.cost, 'paid')

    def test_catalog_includes_requested_providers_without_invented_cortex_capabilities(self):
        rows = {row['provider']: row for row in self.catalog}
        self.assertTrue({'monday', 'snov.io', 'cortex', 'smtp'} <= rows.keys())
        self.assertEqual(rows['cortex']['operations'], [])
        self.assertNotIn('email.read', rows['smtp']['operations'])

    def test_partner_interview_presents_name_and_website_together_and_saves_structured(self):
        onboarding.save_answer(self.store, 'language', 'pt-BR')
        onboarding.save_answer(self.store, 'import_choice', 'start')
        question = onboarding.next_question(self.store)
        self.assertEqual(question.get('fields'), ['partner.name', 'partner.website'])
        self.assertIn('site', question['question'])
        onboarding.save_answer(self.store, 'partner.name', 'Parceiro')
        onboarding.save_answer(self.store, 'partner.website', 'https://partner.example')
        self.assertEqual(self.store.get('profile', 'current').data['partner']['website'], 'https://partner.example')
        self.assertEqual(onboarding.next_question(self.store)['field'], 'partner.products')

    def test_followup_question_explains_actions_without_mode_jargon_in_three_languages(self):
        for language, words in [('pt-BR', ('respostas', 'aprovação')), ('es', ('respuestas', 'aprobación')),
                                ('en', ('replies', 'approval'))]:
            self.store.put('profile', 'current', {'language': language}, self.store.get('profile', 'current').revision if self.store.get('profile', 'current') else None)
            answered = {row[0]: True for row in onboarding.QUESTIONS if row[0] != 'schedule_preferences.mode'}
            old = self.store.get('profile', 'onboarding')
            self.store.put('profile', 'onboarding', {'answers': answered}, old.revision if old else None)
            question = onboarding.next_question(self.store)['question']
            for word in words:
                self.assertIn(word, question)
            self.assertNotIn('manual,', question)


if __name__ == '__main__':
    unittest.main()
