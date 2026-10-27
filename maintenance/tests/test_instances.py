import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from aclad.instances import initialize_instance, locate_instance, list_instances
from aclad.models import GateError

class InstanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Path(self.tmp.name) / 'private'
    def test_new_session_locates_existing_private_state(self):
        first = initialize_instance(self.registry,'Partner A')
        self.assertEqual(locate_instance(self.registry),first)
        self.assertTrue((Path(first['state_dir'])/'state.sqlite').is_file())
    def test_multiple_instances_require_explicit_selection(self):
        first = initialize_instance(self.registry,'Partner A')
        initialize_instance(self.registry,'Partner B')
        with self.assertRaises(GateError) as caught:
            locate_instance(self.registry)
        self.assertEqual(caught.exception.code,'instance_selection_required')
        self.assertEqual(locate_instance(self.registry,first['instance_id']),first)
    def test_missing_state_is_not_recreated_silently(self):
        first = initialize_instance(self.registry,'Partner A')
        (Path(first['state_dir'])/'state.sqlite').unlink()
        with self.assertRaises(GateError):
            locate_instance(self.registry)
        self.assertFalse((Path(first['state_dir'])/'state.sqlite').exists())
    def test_cli_can_resume_without_remembering_scope_arguments(self):
        initialize_instance(self.registry,'Partner A')
        result = subprocess.run([sys.executable,'-m','aclad','--registry-dir',str(self.registry),'status'],input='{}',capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['pending'],[])
