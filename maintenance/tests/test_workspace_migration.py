"""Legacy migration publishes a verified copy and freezes the historical source."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3
import unittest

from aclad.instances import initialize_instance
from aclad.models import Event, GateError, Scope
from aclad.store import Store
from aclad.workspace import locate_workspace
from aclad.workspace_migration import migrate_instance, preview_migration


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Path(self.tmp.name) / 'registry'
        self.root = Path(self.tmp.name) / 'Destino com espaços'
        self.source = initialize_instance(self.registry, 'Histórico')
        self.scope = Scope(*(self.source[k] for k in ('partner_id', 'seller_id', 'instance_id')))
        self.store = Store(Path(self.source['state_dir']), self.scope)
        self.addCleanup(self.store.close)
        self.store.put('profile', 'current', {'partner': {'name': 'Privado'}}, None)
        self.store.record_event(Event('e1', 'current', 'saved', '2026-10-23T12:00:00Z', {}))

    def preview(self):
        return preview_migration(self.registry, self.source['instance_id'], self.root)

    def migrate(self, preview=None):
        preview = preview or self.preview()
        return migrate_instance(self.registry, self.source['instance_id'], self.root, preview['digest'])

    def test_active_work_refuses_migration(self):
        for kind, data in [('action', {'status': 'in_flight'}), ('action', {'status': 'unknown'}),
                           ('run', {'status': 'running'}), ('schedule', {'status': 'active'})]:
            with self.subTest(kind=kind, data=data):
                current = self.store.get(kind, 'busy')
                self.store.put(kind, 'busy', data, current.revision if current else None)
                with self.assertRaises(GateError) as error:
                    self.preview()
                self.assertEqual(error.exception.code, 'migration_active_work')
                current = self.store.get(kind, 'busy')
                self.store.put(kind, 'busy', {'status': 'complete'}, current.revision)
        self.assertFalse((self.root / '.aclad/state.sqlite').exists())

    def test_preview_backup_counts_and_single_writer(self):
        preview = self.preview()
        self.assertEqual(preview['counts'], {'records': 1, 'events': 1})
        migrated = self.migrate(preview)
        self.assertEqual(migrated['instance_id'], self.source['instance_id'])
        self.assertEqual(locate_workspace(self.root)['state_dir'], migrated['state_dir'])
        destination = Store(Path(migrated['state_dir']), self.scope)
        try:
            self.assertEqual(destination.get('profile', 'current').data['partner']['name'], 'Privado')
            self.assertEqual(destination.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
            destination.put('decision', 'after', {'decision': 'OK'}, None)
        finally:
            destination.close()
        self.assertEqual(len(list((self.root / '.aclad/backups').glob('*.sqlite'))), 1)
        with self.assertRaises(GateError) as error:
            self.store.put('decision', 'forbidden', {}, None)
        self.assertEqual(error.exception.code, 'instance_relocated')
        self.assertEqual(self.migrate(preview), migrated)

    def test_changed_preview_is_rejected_before_freeze(self):
        preview = self.preview()
        self.store.put('decision', 'new', {'decision': 'new'}, None)
        with self.assertRaises(GateError) as error:
            self.migrate(preview)
        self.assertEqual(error.exception.code, 'migration_preview_stale')
        self.store.put('decision', 'still-writable', {}, None)
        self.assertFalse((self.root / '.aclad/state.sqlite').exists())

    def test_crash_during_copy_or_activation_recovers(self):
        preview = self.preview()
        with patch('aclad.workspace_migration._copy_database', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.migrate(preview)
        with self.assertRaises(GateError) as error:
            self.store.put('decision', 'blocked', {}, None)
        self.assertEqual(error.exception.code, 'instance_migration_pending')
        with patch('aclad.workspace_migration._mark_relocated', side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                self.migrate(preview)
        self.assertIsNotNone(locate_workspace(self.root))
        active = Store(self.root / '.aclad', self.scope)
        try:
            active.put('decision', 'after-activation', {'decision': 'Continued'}, None)
        finally:
            active.close()
        with self.assertRaises(GateError):
            self.store.put('decision', 'still-blocked', {}, None)
        migrated = self.migrate(preview)
        self.assertEqual(locate_workspace(self.root)['instance_id'], migrated['instance_id'])

    def test_destination_conflict_and_symlink_rejected(self):
        self.root.mkdir()
        (self.root / '.aclad').symlink_to(self.registry / 'instances', target_is_directory=True)
        with self.assertRaises(GateError):
            self.preview()
