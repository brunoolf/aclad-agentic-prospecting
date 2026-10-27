import tempfile
import unittest
from pathlib import Path
from aclad.models import Event, Scope, GateError
from aclad.store import Store

SCOPE = Scope('partner-a', 'seller-a', 'instance-a')
NOW = '2026-10-22T12:00:00Z'

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / 'state'
        self.store = Store(self.directory, SCOPE)
    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
    def test_revision_conflict_preserves_original(self):
        record = self.store.put('account', 'a', {'name': 'Original'}, None)
        self.assertEqual(record.revision, 1)
        for expected in (None, 0, 2):
            with self.assertRaises(GateError):
                self.store.put('account', 'a', {'name': 'Wrong'}, expected)
        self.assertEqual(self.store.get('account', 'a').data['name'], 'Original')
        self.assertEqual(self.store.put('account', 'a', {'name': 'New'}, 1).revision, 2)
    def test_duplicate_event_keeps_sequence(self):
        event = Event('evt-1', 'a', 'selected', NOW, {})
        sequence = self.store.record_event(event)
        self.assertEqual(self.store.record_event(event), sequence)
        self.assertEqual(self.store.snapshot().event_sequence, sequence)
        with self.assertRaises(GateError):
            self.store.record_event(Event('evt-1', 'other', 'selected', NOW, {}))
    def test_other_identity_cannot_open_private_store(self):
        with self.assertRaises(GateError):
            Store(self.directory, Scope('partner-a', 'seller-b', 'instance-a'))
    def test_lease_has_single_owner_and_expires(self):
        second = Store(self.directory, SCOPE)
        self.addCleanup(second.close)
        self.assertTrue(self.store.acquire_lease('review', 'one', NOW, 60))
        self.assertFalse(second.acquire_lease('review', 'two', NOW, 60))
        self.assertFalse(second.release_lease('review', 'two'))
        self.assertTrue(second.acquire_lease('review', 'two', '2026-10-22T12:01:00Z', 60))
        self.assertFalse(self.store.release_lease('review', 'one'))
    def test_backup_restore_preserves_archived_and_pending_records(self):
        self.store.put('account', 'a', {'status': 'archived'}, None)
        self.store.put('action', 'work', {'status': 'unknown'}, None)
        self.store.record_event(Event('e', 'a', 'selected', NOW, {}))
        backup = Path(self.tmp.name) / 'backup.sqlite'
        self.store.backup(backup)
        restored = Store.restore(backup, Path(self.tmp.name) / 'restored', SCOPE)
        self.addCleanup(restored.close)
        self.assertEqual(restored.get('account', 'a').data['status'], 'archived')
        self.assertEqual([r.id for r in restored.snapshot().pending], ['work'])
        self.assertEqual(restored.snapshot().event_sequence, 1)
    def test_invalid_restore_does_not_overwrite_existing_state(self):
        invalid = Path(self.tmp.name) / 'bad.sqlite'
        invalid.write_text('invalid')
        self.store.put('account', 'a', {'status': 'selected'}, None)
        with self.assertRaises(GateError):
            Store.restore(invalid, self.directory, SCOPE)
        self.assertIsNotNone(self.store.get('account', 'a'))
    def test_records_reject_secrets_and_detach_mutable_input(self):
        with self.assertRaises(GateError):
            self.store.put('profile', 'p', {'access_token': 'never-store'}, None)
        data = {'criteria': ['Brazil']}
        self.store.put('icp', 'i', data, None)
        data['criteria'].append('Other')
        self.assertEqual(self.store.get('icp', 'i').data['criteria'], ['Brazil'])
    def test_transaction_rolls_back_records_and_events(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.put('account', 'a', {}, None)
                self.store.record_event(Event('e', 'a', 'selected', NOW, {}))
                raise RuntimeError('interrupted')
        self.assertIsNone(self.store.get('account', 'a'))
        self.assertEqual(self.store.snapshot().event_sequence, 0)
