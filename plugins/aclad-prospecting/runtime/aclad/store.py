"""Private transactional state. A directory belongs to exactly one Scope."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote

from .migrations import migrate
from .models import Event, GateError, Payload, Record, Scope, Snapshot, canonical, payload, utc

KINDS = {'profile', 'campaign', 'account', 'contact', 'icp', 'proposal', 'approval',
         'action', 'rule', 'run', 'cursor', 'schedule', 'notification', 'analysis',
         'checkpoint', 'connection', 'roles', 'message', 'outreach_plan', 'decision', 'meeting'}

class Store:
    def __init__(self, state_dir: Path, scope: Scope):
        from .workspace import workspace_binding
        self.workspace_root = workspace_binding(Path(state_dir), scope)
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.scope = scope
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.state_dir / 'state.sqlite'
        self._depth = 0
        self._changed = False
        self._projecting = False
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            with self.transaction():
                migrate(self.db)
                identity = canonical(asdict(scope))
                row = self.db.execute("SELECT value FROM metadata WHERE key='scope'").fetchone()
                if row and row[0] != identity:
                    raise GateError('identity_mismatch')
                self.db.execute("INSERT OR IGNORE INTO metadata VALUES('scope',?)", (identity,))
                binding = self.db.execute("SELECT value FROM metadata WHERE key='workspace_root'").fetchone()
                if binding and (self.workspace_root is None or binding[0] != str(self.workspace_root)):
                    raise GateError('state_unavailable')
                if self.workspace_root:
                    self.db.execute("INSERT OR IGNORE INTO metadata VALUES('workspace_root',?)", (str(self.workspace_root),))
            os.chmod(self.path, 0o600)
        except Exception:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        depth = self._depth
        changed_before = self._changed
        publish = False
        name = f'state_{depth}'
        self.db.execute('BEGIN IMMEDIATE' if depth == 0 else f'SAVEPOINT {name}')
        self._depth += 1
        try:
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone():
                controls = dict(self.db.execute("SELECT key,value FROM metadata WHERE key IN ('migration_lock','workspace_relocated')"))
                if controls.get('workspace_relocated'):
                    raise GateError('instance_relocated')
                if controls.get('migration_lock'):
                    raise GateError('instance_migration_pending')
            yield self
        except BaseException:
            self.db.execute('ROLLBACK' if depth == 0 else f'ROLLBACK TO {name}')
            if depth:
                self.db.execute(f'RELEASE {name}')
            self._changed = changed_before
            raise
        else:
            if depth == 0 and self._changed and self.workspace_root:
                self.db.execute("INSERT INTO metadata VALUES('results_generation','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
                publish = not self._projecting
            self.db.execute('COMMIT' if depth == 0 else f'RELEASE {name}')
            if depth == 0:
                self._changed = False
        finally:
            self._depth -= 1
        if publish:
            from .local_views import refresh_local_views
            refresh_local_views(self)

    def put(self, kind: str, id: str, data: Payload, expected_revision: int | None) -> Record:
        if kind not in KINDS or not isinstance(id, str) or not id:
            raise GateError('invalid_record')
        encoded = canonical(payload(data))
        with self.transaction():
            current = self.get(kind, id)
            if (current and expected_revision != current.revision) or (not current and expected_revision is not None):
                raise GateError('revision_conflict')
            revision = current.revision + 1 if current else 1
            self.db.execute('INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET revision=excluded.revision,data=excluded.data',
                            (kind, id, revision, encoded))
            self._changed = True
        return Record(id, kind, revision, json.loads(encoded))

    def get(self, kind: str, id: str) -> Record | None:
        row = self.db.execute('SELECT * FROM records WHERE kind=? AND id=?', (kind, id)).fetchone()
        return self._record(row) if row else None

    def list(self, kind: str) -> list[Record]:
        return [self._record(row) for row in self.db.execute('SELECT * FROM records WHERE kind=? ORDER BY id', (kind,))]

    @staticmethod
    def _record(row) -> Record:
        return Record(row['id'], row['kind'], row['revision'], json.loads(row['data']))

    def record_event(self, event: Event) -> int:
        utc(event.occurred_at)
        encoded = canonical(event.data)
        with self.transaction():
            old = self.db.execute('SELECT * FROM events WHERE id=?', (event.id,)).fetchone()
            values = (event.record_id, event.kind, event.occurred_at, encoded)
            if old:
                if tuple(old[k] for k in ('record_id', 'kind', 'occurred_at', 'data')) != values:
                    raise GateError('event_conflict')
                return old['sequence']
            cursor = self.db.execute('INSERT INTO events(id,record_id,kind,occurred_at,data) VALUES(?,?,?,?,?)', (event.id, *values))
            self._changed = True
            return cursor.lastrowid

    def events_since(self, sequence: int = 0) -> list[Payload]:
        if type(sequence) is not int or sequence < 0:
            raise GateError('invalid_event_sequence')
        return [dict(row, data=json.loads(row['data'])) for row in self.db.execute(
            'SELECT * FROM events WHERE sequence>? ORDER BY sequence', (sequence,))]

    def snapshot(self) -> Snapshot:
        with self.transaction():
            records = [self._record(r) for r in self.db.execute('SELECT * FROM records ORDER BY kind,id')]
            sequence = self.db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
        pending = [r for r in records if r.data.get('status') in {'prepared','in_flight','unknown','pending','proposed','needs_review'}]
        return Snapshot(sequence, records, pending)

    def acquire_lease(self, key: str, owner: str, now: str, ttl_seconds: int) -> bool:
        if not key or not owner or type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise GateError('invalid_lease')
        instant = utc(now)
        with self.transaction():
            old = self.db.execute('SELECT owner,expires_at FROM leases WHERE key=?', (key,)).fetchone()
            if old and old['owner'] != owner and utc(old['expires_at']) > instant:
                return False
            expires = (instant + timedelta(seconds=ttl_seconds)).isoformat()
            self.db.execute('INSERT INTO leases VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at', (key, owner, expires))
        return True

    def release_lease(self, key: str, owner: str) -> bool:
        with self.transaction():
            return self.db.execute('DELETE FROM leases WHERE key=? AND owner=?', (key, owner)).rowcount == 1

    def backup(self, destination: Path) -> None:
        destination = Path(destination)
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            target = sqlite3.connect(destination)
            try:
                self.db.backup(target)
            finally:
                target.close()
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    @classmethod
    def restore(cls, source: Path, state_dir: Path, scope: Scope) -> Store:
        target_dir = Path(state_dir)
        target_path = target_dir / 'state.sqlite'
        if target_path.exists():
            raise GateError('restore_destination_exists')
        temp_path = None
        try:
            connection = sqlite3.connect(f'file:{quote(str(Path(source).resolve()))}?mode=ro', uri=True)
            try:
                if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise GateError('invalid_backup')
                if connection.execute('PRAGMA user_version').fetchone()[0] != 1:
                    raise GateError('invalid_backup')
                row = connection.execute("SELECT value FROM metadata WHERE key='scope'").fetchone()
                if not row or row[0] != canonical(asdict(scope)):
                    raise GateError('identity_mismatch')
                target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                temp_path = target_dir / f'.restore-{uuid4().hex}.sqlite'
                target = sqlite3.connect(temp_path)
                try:
                    connection.backup(target)
                finally:
                    target.close()
                os.chmod(temp_path, 0o600)
                os.link(temp_path, target_path)
            finally:
                connection.close()
        except (sqlite3.Error, OSError):
            raise GateError('invalid_backup') from None
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)
        return cls(target_dir, scope)

    def close(self) -> None:
        self.db.close()
