"""Named ICPs and durable, private campaign views remain projections of SQLite."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aclad.icps import approve_icp, bind_icp, propose_icp
from aclad.models import GateError, Scope
from aclad.store import Store
from aclad.workspace import initialize_workspace
try:
    from aclad import workflow_views
except ImportError:
    workflow_views = None


class WorkflowViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = (Path(self.tmp.name) / 'Prospecção privada').resolve()
        info = initialize_workspace(self.root, 'Minha prospecção')
        self.scope = Scope(info['partner_id'], info['seller_id'], info['instance_id'])
        self.store = Store(Path(info['state_dir']), self.scope)
        self.addCleanup(self.store.close)
        self.criteria = [{'field': 'industry', 'operator': 'in',
                          'value': ['Financial services'], 'basis': 'hypothesis'}]

    def named(self, name='Financeiro — Grande São Paulo', **kwargs):
        return propose_icp(self.store, self.criteria, [], [], True, name=name, **kwargs)

    def active(self, name='Financeiro — Grande São Paulo'):
        proposed = self.named(name)
        return approve_icp(self.store, proposed.id, proposed.revision, 'Vendedora')

    def test_multiple_named_icps_preserve_identity_and_approval_snapshot(self):
        first = self.active()
        second = self.named('Indústria — Brasil', description='Campanha separada')
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.data['name'], 'Financeiro — Grande São Paulo')
        self.assertEqual(first.data['approved_versions'][str(first.revision)]['name'], first.data['name'])
        self.assertEqual(second.data['description'], 'Campanha separada')

    def test_invalid_names_and_descriptions_never_persist(self):
        for name in ('', '  ', '\n', 'x' * 201, 42):
            with self.subTest(name=name), self.assertRaises(GateError):
                self.named(name)
        with self.assertRaises(GateError):
            self.named(description=['bad'])
        self.assertFalse(self.store.list('icp'))

    def test_legacy_proposal_gets_a_readable_default_name(self):
        row = propose_icp(self.store, self.criteria, [], [], True)
        self.assertIn('Financial services', row.data['name'])

    def test_corrupt_metadata_cannot_enter_an_approved_snapshot(self):
        row = self.named()
        changed = self.store.put('icp', row.id, dict(row.data, name='  '), row.revision)
        with self.assertRaises(GateError):
            approve_icp(self.store, changed.id, changed.revision, 'Vendedora')

    def test_legacy_unnamed_approved_snapshot_remains_bindable(self):
        row = propose_icp(self.store, self.criteria, [], [], True)
        legacy = {key: value for key, value in row.data.items() if key not in {'name', 'description'}}
        row = self.store.put('icp', row.id, legacy, row.revision)
        active = approve_icp(self.store, row.id, row.revision, 'Vendedora')
        self.store.put('campaign', 'legacy', {'objective': 'Retomar'}, None)
        bound = bind_icp(self.store, 'legacy', active.id, active.revision)
        self.assertNotIn('name', bound.data['icp_snapshot'])

    def test_catalog_lists_approved_and_proposed_without_writing_state(self):
        self.assertIsNotNone(workflow_views, 'private workflow projection API is missing')
        first, second = self.active(), self.named('Outro ICP')
        before = self.store.snapshot()
        catalog = workflow_views.icp_catalog(self.store)
        self.assertEqual({r['id'] for r in catalog['icps']}, {first.id, second.id})
        self.assertEqual(catalog['approved_count'], 1)
        self.assertEqual(self.store.snapshot(), before)

    def test_campaign_keeps_bound_name_and_criteria_when_icp_is_revised(self):
        self.assertIsNotNone(workflow_views, 'private workflow projection API is missing')
        active = self.active()
        self.store.put('campaign', 'financial', {'objective': 'Gerar reuniões'}, None)
        bound = bind_icp(self.store, 'financial', active.id, active.revision)
        data = deepcopy(active.data)
        data.update(status='proposed', name='Nome alterado', criteria=[dict(self.criteria[0], value=['Industry'])])
        changed = self.store.put('icp', active.id, data, active.revision)
        approve_icp(self.store, changed.id, changed.revision, 'Vendedora')
        view = workflow_views.campaign_context(self.store, 'financial')
        self.assertEqual(view['icp']['name'], 'Financeiro — Grande São Paulo')
        self.assertEqual(view['icp']['revision'], bound.data['icp_revision'])
        self.assertEqual(view['icp']['criteria'][0]['value'], ['Financial services'])

    def test_documents_are_created_and_repaired_from_canonical_state(self):
        self.assertIsNotNone(workflow_views, 'private workflow projection API is missing')
        active = self.active()
        self.store.put('campaign', 'financial', {'objective': 'Gerar reuniões'}, None)
        bind_icp(self.store, 'financial', active.id, active.revision)
        catalog = workflow_views.icp_catalog(self.store)
        icp_doc = self.root / catalog['icps'][0]['document_path']
        self.assertIn('Financeiro', icp_doc.read_text())
        campaign = workflow_views.campaign_context(self.store, 'financial')
        campaign_doc = self.root / campaign['document_path']
        self.assertIn('Gerar reuniões', campaign_doc.read_text())
        icp_doc.write_text('damaged')
        campaign_doc.unlink()
        before = self.store.snapshot()
        workflow_views.refresh_workflow_views(self.store)
        self.assertIn('Financeiro', icp_doc.read_text())
        self.assertIn('Gerar reuniões', campaign_doc.read_text())
        self.assertEqual(before, self.store.snapshot())

    def test_arbitrary_record_ids_and_names_cannot_escape_or_inject_markdown(self):
        self.assertIsNotNone(workflow_views, 'private workflow projection API is missing')
        identifier = '../../outside<script>'
        self.store.put('campaign', identifier, {'objective': '```\n<script>alert(1)</script>\n# fake'}, None)
        view = workflow_views.campaign_context(self.store, identifier)
        path = (self.root / view['document_path']).resolve()
        self.assertTrue(path.is_relative_to(self.root))
        self.assertEqual(path.parent, self.root / 'campanhas')
        document = path.read_text()
        self.assertNotIn('<script>', document)
        self.assertNotIn('\n# fake', document)
        self.assertFalse((Path(self.tmp.name) / 'outside<script>.md').exists())

    def test_campaign_context_has_per_account_progress_and_uncertain_action_blockers(self):
        self.assertIsNotNone(workflow_views, 'private workflow projection API is missing')
        active = self.active()
        self.store.put('campaign', 'financial', {'objective': 'Gerar reuniões'}, None)
        bind_icp(self.store, 'financial', active.id, active.revision)
        self.store.put('account', 'company-one', {'campaign_id': 'financial', 'name': 'Empresa Um', 'selected': True}, None)
        self.store.put('account', 'company-two', {'campaign_id': 'financial', 'name': 'Empresa Dois', 'selected': False}, None)
        self.store.put('contact', 'person-one', {'campaign_id': 'financial', 'account_id': 'company-one', 'selected': True}, None)
        self.store.put('message', 'message-one', {'campaign_id': 'financial', 'message': {'account_id': 'company-one', 'contact_id': 'person-one'}, 'status': 'drafted'}, None)
        self.store.put('action', 'uncertain', {'operation': 'email.send', 'status': 'unknown', 'payload': {'campaign_id': 'financial', 'message_id': 'message-one'}}, None)
        view = workflow_views.campaign_context(self.store, 'financial')
        self.assertEqual(view['counts']['selected_accounts'], 1)
        self.assertEqual(view['counts']['drafted_messages'], 1)
        self.assertIn('reconciliation_required', view['blockers'])
        accounts = {row['id']: row for row in view['accounts']}
        self.assertEqual(accounts['company-one']['stage'], 'draft_review')
        self.assertEqual(accounts['company-two']['stage'], 'account_selection')

    def test_workflow_docs_never_change_numeric_only_results_or_leak_to_other_workspace(self):
        self.assertIsNotNone(workflow_views, 'private workflow projection API is missing')
        self.active('SEGREDO DO VENDEDOR')
        other = Path(self.tmp.name) / 'Outra prospecção'
        initialize_workspace(other, 'Outra pessoa')
        self.assertNotIn('SEGREDO', (self.root / 'contexto/resultados.md').read_text())
        self.assertNotIn('SEGREDO', (other / 'contexto/icps/index.md').read_text())

    def test_projection_rejects_symlink_and_cleans_only_its_own_deleted_records(self):
        self.assertIsNotNone(workflow_views, 'private workflow projection API is missing')
        active = self.active()
        path = self.root / workflow_views.icp_catalog(self.store)['icps'][0]['document_path']
        note = path.parent / 'minhas-notas.md'
        note.write_text('keep')
        self.store.db.execute('DELETE FROM records WHERE kind=? AND id=?', ('icp', active.id))
        workflow_views.refresh_workflow_views(self.store)
        self.assertFalse(path.exists())
        self.assertEqual(note.read_text(), 'keep')
        outside = Path(self.tmp.name) / 'outside.md'
        outside.write_text('private')
        path.symlink_to(outside)
        with self.assertRaises(GateError):
            workflow_views.refresh_workflow_views(self.store)
        self.assertEqual(outside.read_text(), 'private')
