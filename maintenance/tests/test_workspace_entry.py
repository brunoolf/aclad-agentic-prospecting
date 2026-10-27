import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from aclad.hooks import handle_hook
from aclad.workspace import initialize_workspace
from aclad.instances import initialize_instance

class WorkspaceEntryTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()/'seller space'
        self.env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[2]/'plugins/aclad-prospecting/runtime')}
        self.registry=Path(self.tmp.name)/'registry'

    def call(self,command,data=None,explicit=False,cwd=None):
        args=[sys.executable,'-m','aclad','--registry-dir',str(self.registry)]
        if explicit:args+=['--workspace',str(self.root)]
        return subprocess.run(args+[command],input=json.dumps(data or {}),text=True,capture_output=True,env=self.env,cwd=cwd or self.tmp.name)

    def test_cwd_nested_resume_without_hooks(self):
        result=self.call('workspace-init',{'name':'Seller'},True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        identity=json.loads(result.stdout)['instance_id']
        saved=self.call('setup-answer',{'field':'language','value':'pt-BR'},cwd=self.root/'campanhas')
        self.assertEqual(saved.returncode,0,saved.stdout)
        resumed=self.call('resume',cwd=self.root/'campanhas')
        self.assertEqual(resumed.returncode,0,resumed.stdout)
        self.assertTrue(any(r['kind']=='profile' for r in json.loads(resumed.stdout)['records']))
        self.assertEqual(json.loads(self.call('workspace-locate',cwd=self.root).stdout)['instance_id'],identity)
        self.assertFalse(self.registry.exists())

    def test_broken_local_marker_never_uses_legacy_default(self):
        initialize_instance(self.registry,'Legacy'); initialize_workspace(self.root,'Seller')
        (self.root/'.aclad/state.sqlite').unlink()
        result=self.call('resume',cwd=self.root)
        self.assertEqual(result.returncode,2,result.stdout)
        self.assertEqual(json.loads(result.stdout)['error']['code'],'state_unavailable')
        self.assertFalse((self.root/'.aclad/state.sqlite').exists())

    def test_native_hook_scope_and_absent_plugin_guidance(self):
        initialize_workspace(self.root,'Seller')
        def event(cwd):return {'session_id':'s','cwd':str(cwd),'hook_event_name':'SessionStart'}
        with patch.dict(os.environ,{},clear=True):
            outside=handle_hook('codex','SessionStart',event(self.tmp.name))
            inside=handle_hook('codex','SessionStart',event(self.root/'campanhas'))
        self.assertEqual(outside,{})
        self.assertIn('recovered private state',inside['hookSpecificOutput']['additionalContext'])
        self.assertIn('ausente/desabilitado',(self.root/'AGENTS.md').read_text())
