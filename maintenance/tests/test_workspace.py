import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from aclad.models import GateError, Scope
from aclad.store import Store
try:
    from aclad import workspace
except ImportError:
    workspace = None

class WorkspaceTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'Minha Prospecção'
        self.assertIsNotNone(workspace, 'workspace initialization API is missing')

    def init(self):
        return workspace.initialize_workspace(self.root, 'Vendas')

    def test_spaces_two_roots_and_repeat(self):
        home = Path(self.tmp.name) / 'home'; home.mkdir()
        with patch.dict('os.environ', {'HOME': str(home)}):
            first = self.init()
            store = Store(Path(first['state_dir']), Scope(first['partner_id'], first['seller_id'], first['instance_id']))
            store.put('decision','kept',{'choice':'preserved'},None); store.close()
            again = self.init()
            other = workspace.initialize_workspace(Path(self.tmp.name)/'Outra pasta', 'Vendas')
        self.assertEqual(first,again)
        self.assertNotEqual(first['instance_id'],other['instance_id'])
        self.assertFalse((self.root/'.git').exists())
        self.assertEqual(list(home.iterdir()),[])
        for name in ('AGENTS.md','CLAUDE.md','contexto/empresa.md','contexto/vendedor.md','.aclad/state.sqlite','planos','campanhas','relatorios','.aclad/backups'):
            self.assertTrue((self.root/name).exists(),name)
        self.assertEqual(workspace.locate_workspace(self.root/'campanhas'),first)

    def test_initialization_creates_numeric_results_and_private_learning(self):
        self.init()
        self.assertTrue((self.root/'contexto/resultados.md').is_file())
        self.assertTrue((self.root/'contexto/aprendizados.md').is_file())
        self.assertIn('| E-mails enviados | 0 |',(self.root/'contexto/resultados.md').read_text())

    def test_invalid_marker_or_missing_database_never_reinitializes(self):
        self.init(); (self.root/'.aclad/state.sqlite').unlink()
        for function in (self.init,lambda:workspace.locate_workspace(self.root)):
            with self.assertRaises(GateError) as error: function()
            self.assertEqual(error.exception.code,'state_unavailable')
        self.assertFalse((self.root/'.aclad/state.sqlite').exists())

    def test_broken_marker_and_unknown_protocol(self):
        self.init(); marker=self.root/'.aclad/workspace.json'
        data=json.loads(marker.read_text()); data['protocol_version']=2
        marker.write_text(json.dumps(data))
        with self.assertRaises(GateError): self.init()
        marker.write_text('{broken')
        with self.assertRaises(GateError): workspace.locate_workspace(self.root)

    def test_symlink_escape(self):
        self.root.mkdir(); outside=Path(self.tmp.name)/'outside';outside.mkdir()
        (self.root/'.aclad').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(GateError): self.init()
        self.assertEqual(list(outside.iterdir()),[])

    def test_existing_files_and_interrupted_initialization(self):
        self.root.mkdir(); original='My project guidance\n'
        (self.root/'AGENTS.md').write_text(original)
        from aclad import workspace_files
        real=workspace_files.write_managed
        def fail(path,*args,**kwargs):
            if Path(path).name=='CLAUDE.md': raise OSError('disk full')
            return real(path,*args,**kwargs)
        with patch.object(workspace_files,'write_managed',side_effect=fail):
            with self.assertRaises(OSError): self.init()
        initial=json.loads((self.root/'.aclad/workspace.json').read_text())
        result=self.init(); self.init()
        self.assertEqual(initial['instance_id'],result['instance_id'])
        text=(self.root/'AGENTS.md').read_text()
        self.assertTrue(text.startswith(original))
        self.assertEqual(text.count('<!-- ACLAD_WORKSPACE_START -->'),1)

    def test_malformed_managed_block_preserves_content(self):
        self.root.mkdir(); path=self.root/'AGENTS.md'
        original='User content\n<!-- ACLAD_WORKSPACE_START -->\nunfinished'
        path.write_text(original)
        with self.assertRaises(GateError) as error:self.init()
        self.assertEqual(error.exception.code,'workspace_conflict')
        self.assertEqual(path.read_text(),original)

    def test_copy_requires_explicit_migration(self):
        info=self.init(); other=Path(self.tmp.name)/'copy'
        shutil.copytree(self.root,other)
        with self.assertRaises(GateError): workspace.locate_workspace(other)
        with self.assertRaises(GateError):
            Store(other/'.aclad',Scope(info['partner_id'],info['seller_id'],info['instance_id']))
