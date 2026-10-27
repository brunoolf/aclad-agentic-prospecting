"""Trusted project-local identity; invalid local state never selects another seller."""
from pathlib import Path
from contextlib import closing
from dataclasses import asdict
import json
import os
import sqlite3
from urllib.parse import quote
from uuid import uuid4
from .models import GateError, Payload, Scope, canonical
from . import workspace_files

_KEYS = {'protocol_version', 'phase', 'state_path', 'partner_id', 'seller_id', 'instance_id'}


def _read_marker(root: Path, allow_initializing: bool = False) -> Payload:
    marker = root / '.aclad' / 'workspace.json'
    try:
        workspace_files.check_path(marker)
        data = json.loads(marker.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or set(data) != _KEYS
                or type(data['protocol_version']) is not int or data['protocol_version'] != 1
                or data['state_path'] != 'state.sqlite'
                or data['phase'] not in ({'initializing', 'ready'} if allow_initializing else {'ready'})):
            raise ValueError()
        Scope(data['partner_id'], data['seller_id'], data['instance_id'])
        return data
    except (OSError, ValueError, KeyError, TypeError, GateError):
        raise GateError('state_unavailable') from None


def _info(root: Path, marker: Payload) -> Payload:
    return {'root': str(root), 'state_dir': str(root / '.aclad'),
            **{key: marker[key] for key in ('partner_id', 'seller_id', 'instance_id', 'protocol_version')}}


def _validate_database(root: Path, marker: Payload) -> None:
    path = root / '.aclad' / 'state.sqlite'
    workspace_files.check_path(path)
    if not path.is_file():
        raise GateError('state_unavailable')
    try:
        with closing(sqlite3.connect(f'file:{quote(str(path))}?mode=ro', uri=True)) as db:
            metadata = dict(db.execute('SELECT key,value FROM metadata'))
            expected = canonical({key: marker[key] for key in ('partner_id', 'seller_id', 'instance_id')})
            if metadata.get('scope') != expected or metadata.get('workspace_root') != str(root):
                raise GateError('state_unavailable')
            if metadata.get('workspace_relocated') or metadata.get('migration_lock'):
                raise GateError('state_unavailable')
    except sqlite3.Error:
        raise GateError('state_unavailable') from None


def locate_workspace(start: Path) -> Payload | None:
    path = Path(start).expanduser().resolve()
    workspace_files.check_path(path)
    if path.is_file():
        path = path.parent
    for root in (path, *path.parents):
        marker = root / '.aclad' / 'workspace.json'
        if marker.exists() or marker.is_symlink():
            data = _read_marker(root)
            _validate_database(root, data)
            return _info(root, data)
        # A local ACLAD boundary without its identity marker is damaged state,
        # never permission to inherit a different seller from an ancestor.
        if (root / '.aclad').exists() or (root / '.aclad').is_symlink():
            raise GateError('state_unavailable')
    return None


def workspace_binding(state_dir: Path, scope: Scope) -> Path | None:
    raw = Path(state_dir).expanduser().absolute()
    path = raw.parent.resolve() / raw.name
    marker = path / 'workspace.json'
    if not marker.exists() and not marker.is_symlink():
        return None
    if path.name != '.aclad':
        raise GateError('state_unavailable')
    root = path.parent
    data = _read_marker(root, allow_initializing=True)
    if any(data[key] != value for key, value in asdict(scope).items()):
        raise GateError('identity_mismatch')
    if data['phase'] == 'ready':
        _validate_database(root, data)
    return root


def _write_files(root: Path) -> None:
    templates = Path(__file__).resolve().parents[2] / 'templates' / 'workspace'
    for name in ('planos', 'campanhas', 'relatorios', 'contexto', '.aclad/backups'):
        target = root / name
        workspace_files.check_path(target)
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for source, destination in (('AGENTS.md','AGENTS.md'), ('CLAUDE.md','CLAUDE.md'),
                                ('empresa.md','contexto/empresa.md'), ('vendedor.md','contexto/vendedor.md')):
        workspace_files.write_managed(root / destination, (templates / source).read_text(), 'ACLAD_WORKSPACE')


def initialize_workspace(root: Path, name: str) -> Payload:
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise GateError('instance_name_required')
    root = Path(root).expanduser().resolve()
    workspace_files.check_path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir = root / '.aclad'
    workspace_files.check_path(state_dir)
    state_dir.mkdir(exist_ok=True, mode=0o700)
    marker_path = state_dir / 'workspace.json'
    if marker_path.exists():
        marker = _read_marker(root, allow_initializing=True)
        if marker['phase'] == 'ready':
            _validate_database(root, marker)
    else:
        if (state_dir / 'state.sqlite').exists():
            raise GateError('state_unavailable')
        identifier = uuid4().hex
        marker = {'protocol_version': 1, 'phase': 'initializing', 'state_path': 'state.sqlite',
                  'partner_id': 'partner-' + identifier, 'seller_id': 'seller-' + identifier,
                  'instance_id': identifier}
        descriptor = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(canonical(marker)); handle.flush(); os.fsync(handle.fileno())
    from .store import Store
    store = Store(state_dir, Scope(marker['partner_id'], marker['seller_id'], marker['instance_id']))
    store.close()
    _write_files(root)
    marker['phase'] = 'ready'
    workspace_files.atomic_write(marker_path, canonical(marker) + '\n')
    from .local_views import refresh_local_views
    store = Store(state_dir, Scope(marker['partner_id'], marker['seller_id'], marker['instance_id']))
    try:
        refresh_local_views(store)
    finally:
        store.close()
    return _info(root, marker)
