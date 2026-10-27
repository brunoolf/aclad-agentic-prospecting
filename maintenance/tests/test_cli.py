import json
import os
import subprocess
import sys
import tempfile
import unittest

class CliTests(unittest.TestCase):
    def call(self, directory, command, payload):
        return subprocess.run([sys.executable, '-m', 'aclad', '--state-dir', directory,
            '--partner-id', 'p', '--seller-id', 's', '--instance-id', 'i', command],
            input=payload, capture_output=True, text=True)
    def test_status_and_checkpoint_are_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.call(directory, 'status', '{}')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['pending'], [])
            self.assertEqual(self.call(directory, 'checkpoint', '{}').returncode, 0)
    def test_invalid_input_returns_sanitized_domain_error(self):
        with tempfile.TemporaryDirectory() as directory:
            for payload in ('{not-json', '{"access_token":"secret-value"}', '[]'):
                result = self.call(directory, 'status', payload)
                self.assertEqual(result.returncode, 2)
                self.assertIn('error', json.loads(result.stdout))
                self.assertNotIn('secret-value', result.stdout + result.stderr)
