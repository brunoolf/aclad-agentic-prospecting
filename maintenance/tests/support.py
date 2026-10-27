from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from aclad.models import Scope, ToolResult
from aclad.store import Store
SCOPE = Scope('partner-a', 'seller-a', 'instance-a')
NOW = '2026-10-22T12:00:00Z'

class StateTest(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state', SCOPE)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)

class FakeBridge:
    def __init__(self):
        self.calls = []
        self.results = {}
    def call(self, intent):
        self.calls.append(intent)
        if intent.action_id not in self.results:
            raise AssertionError('No external result fixture for action')
        result = self.results[intent.action_id]
        if isinstance(result, Exception):
            raise result
        return result
