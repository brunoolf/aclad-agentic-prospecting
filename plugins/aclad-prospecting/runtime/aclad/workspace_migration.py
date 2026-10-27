"""Explicit resumable transfer of a legacy instance, with one writable home."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote

from .instances import list_instances
from .models import GateError, Payload, canonical
from .workspace import initialize_workspace, locate_workspace
from .workspace_files import atomic_write, check_path


@contextmanager
def _source(registry_dir: Path, instance_id: str):
    rows = [row for row in list_instances(registry_dir) if row['instance_id'] == instance_id]
    if len(rows) != 1:
        raise GateError('instance_selection_required')
    info = rows[0]
    directory = Path(info['state_dir']).resolve()
    base = Path(registry_dir).expanduser().resolve() / 'instances'
    if not directory.is_relative_to(base) or not (directory / 'state.sqlite').is_file():
        raise GateError('state_unavailable')
    db = sqlite3.connect(f'file:{quote(str(directory / "state.sqlite"))}?mode=rw',
                         uri=True, isolation_level=None, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        expected = canonical({key: info[key] for key in ('partner_id', 'seller_id', 'instance_id')})
        row = db.execute("SELECT value FROM metadata WHERE key='scope'").fetchone()
        if not row or row[0] != expected or db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise GateError('state_unavailable')
        yield info, db
    finally:
        db.close()


def _metadata(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return row[0] if row else None


def _snapshot(db: sqlite3.Connection, info: Payload, root: Path) -> Payload:
    records = [dict(row) for row in db.execute('SELECT * FROM records ORDER BY kind,id')]
    events = [dict(row) for row in db.execute('SELECT * FROM events ORDER BY sequence')]
    for record in records:
        value = json.loads(record['data'])
        busy = ((record['kind'] == 'action' and value.get('status') in {'in_flight', 'unknown'})
                or (record['kind'] == 'run' and value.get('status') == 'running')
                or (record['kind'] == 'schedule' and (value.get('status') == 'active'
                    or value.get('schedule', {}).get('active') is True)))
        if busy:
            raise GateError('migration_active_work')
    identity = {key: info[key] for key in ('partner_id', 'seller_id', 'instance_id')}
    digest = sha256(canonical({'source': info['state_dir'], 'root': str(root),
                              'identity': identity, 'records': records, 'events': events}).encode()).hexdigest()
    return {'source': info['state_dir'], 'root': str(root), **identity,
            'counts': {'records': len(records), 'events': len(events)}, 'digest': digest}


def _root(root: Path) -> Path:
    # Resolve system aliases (macOS /var) before enforcing managed-path guards.
    raw = Path(root).expanduser().absolute()
    if raw.is_symlink():
        raise GateError('workspace_path_unavailable')
    resolved = raw.resolve()
    for relative in ('.aclad', '.aclad/workspace.json', '.aclad/state.sqlite',
                     '.aclad/migration.json', '.aclad/backups'):
        check_path(resolved / relative)
    return resolved


def _destination(root: Path, journal: Payload | None) -> None:
    directory = root / '.aclad'
    if not directory.exists():
        return
    if not directory.is_dir():
        raise GateError('workspace_conflict')
    owned = journal is not None and journal.get('root') == str(root)
    if not owned and any(directory.iterdir()):
        raise GateError('workspace_conflict')
    if owned:
        for filename in ('migration.json', 'workspace.json'):
            path = directory / filename
            if path.exists():
                try:
                    value = json.loads(path.read_text(encoding='utf-8'))
                except (ValueError, OSError):
                    raise GateError('workspace_conflict') from None
                if filename == 'migration.json' and value != journal:
                    raise GateError('workspace_conflict')
                if filename == 'workspace.json' and any(value.get(key) != journal[key]
                    for key in ('partner_id', 'seller_id', 'instance_id')):
                    raise GateError('workspace_conflict')


def preview_migration(registry_dir: Path, instance_id: str, root: Path) -> Payload:
    root = _root(root)
    with _source(registry_dir, instance_id) as (info, db):
        if root == Path(info['state_dir']).parent or root.is_relative_to(Path(info['state_dir'])):
            raise GateError('workspace_conflict')
        lock = _metadata(db, 'migration_lock')
        journal = json.loads(lock) if lock else None
        if journal and journal.get('root') != str(root):
            raise GateError('instance_migration_pending')
        relocated = _metadata(db, 'workspace_relocated')
        if relocated and relocated != str(root):
            raise GateError('instance_relocated')
        _destination(root, journal)
        db.execute('BEGIN')
        try:
            return _snapshot(db, info, root)
        finally:
            db.execute('ROLLBACK')


def _copy_database(source: sqlite3.Connection, destination: Path) -> None:
    check_path(destination)
    descriptor, temporary = tempfile.mkstemp(prefix='.migration-copy-', suffix='.sqlite', dir=destination.parent)
    os.close(descriptor)
    temp = Path(temporary)
    try:
        target = sqlite3.connect(temp)
        try:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise GateError('invalid_backup')
        finally:
            target.close()
        with temp.open('rb') as handle:
            os.fsync(handle.fileno())
        # Exclusive atomic publication. A hard exit can leave only an unpublished
        # temporary, never an incomplete final backup or state database.
        os.link(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def _validate_copy(path: Path, preview: Payload) -> None:
    check_path(path)
    db = sqlite3.connect(f'file:{quote(str(path))}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        scope = {key: preview[key] for key in ('partner_id', 'seller_id', 'instance_id')}
        if (db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok'
                or db.execute('PRAGMA user_version').fetchone()[0] != 1
                or _metadata(db, 'scope') != canonical(scope)):
            raise GateError('invalid_backup')
        counts = {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                  for table in ('records', 'events')}
        if counts != preview['counts']:
            raise GateError('invalid_backup')
        info = {**scope, 'state_dir': preview['source']}
        if _snapshot(db, info, Path(preview['root']))['digest'] != preview['digest']:
            raise GateError('invalid_backup')
    finally:
        db.close()


def _mark_relocated(db: sqlite3.Connection, root: Path) -> None:
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute("INSERT OR REPLACE INTO metadata VALUES('workspace_relocated',?)", (str(root),))
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise


def migrate_instance(registry_dir: Path, instance_id: str, root: Path,
                     preview_digest: str) -> Payload:
    root = _root(root)
    with _source(registry_dir, instance_id) as (info, db):
        db.execute('BEGIN IMMEDIATE')
        try:
            lock = _metadata(db, 'migration_lock')
            journal = json.loads(lock) if lock else None
            if journal and (journal.get('root') != str(root) or journal.get('digest') != preview_digest):
                raise GateError('instance_migration_pending')
            relocated = _metadata(db, 'workspace_relocated')
            if relocated:
                if relocated != str(root) or not journal or journal['digest'] != preview_digest:
                    raise GateError('instance_relocated')
                result = locate_workspace(root)
                if result is None:
                    raise GateError('state_unavailable')
                db.execute('COMMIT')
                return result
            preview = _snapshot(db, info, root)
            if preview['digest'] != preview_digest:
                raise GateError('migration_preview_stale')
            _destination(root, journal)
            journal = preview
            if lock and (root / '.aclad/workspace.json').is_file():
                marker = json.loads((root / '.aclad/workspace.json').read_text(encoding='utf-8'))
                if marker.get('phase') == 'ready':
                    result = locate_workspace(root)
                    if result is None or result['instance_id'] != instance_id:
                        raise GateError('state_unavailable')
                    db.execute('COMMIT')
                    _mark_relocated(db, root)
                    return result
            # All Store writers check this durable freeze before any mutation.
            db.execute("INSERT OR REPLACE INTO metadata VALUES('migration_lock',?)", (canonical(journal),))
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
        directory = root / '.aclad'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(directory / 'migration.json', canonical(journal) + '\n')
        marker_path = directory / 'workspace.json'
        if not marker_path.exists():
            marker = {'protocol_version': 1, 'phase': 'initializing', 'state_path': 'state.sqlite',
                      **{key: preview[key] for key in ('partner_id', 'seller_id', 'instance_id')}}
            atomic_write(marker_path, canonical(marker) + '\n')
        backup_dir = directory / 'backups'
        backup_dir.mkdir(exist_ok=True, mode=0o700)
        backup = backup_dir / f'legacy-{preview_digest}.sqlite'
        if not backup.exists():
            _copy_database(db, backup)
        _validate_copy(backup, preview)
        destination = directory / 'state.sqlite'
        if not destination.exists():
            source = sqlite3.connect(f'file:{quote(str(backup))}?mode=ro', uri=True)
            try:
                _copy_database(source, destination)
            finally:
                source.close()
        _validate_copy(destination, preview)
        target = sqlite3.connect(destination)
        try:
            target.execute('DELETE FROM metadata WHERE key IN (?,?)', ('migration_lock', 'workspace_relocated'))
            target.execute("INSERT OR REPLACE INTO metadata VALUES('workspace_root',?)", (str(root),))
            target.commit()
        finally:
            target.close()
        result = initialize_workspace(root, str(info['name']))
        _mark_relocated(db, root)
        return result
