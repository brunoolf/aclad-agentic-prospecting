"""Trusted local locator: new chats recover a selected private installation."""
from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
from uuid import uuid4
from .models import GateError, Scope, Payload
from .store import Store

@contextmanager
def _registry(directory: Path, create: bool = False):
    directory = Path(directory).expanduser().resolve()
    path = directory / 'registry.sqlite'
    if not create and not path.is_file():
        raise GateError('instance_setup_required')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    os.chmod(path,0o600)
    try:
        if create:
            connection.execute('CREATE TABLE IF NOT EXISTS instances (instance_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, partner_id TEXT NOT NULL, seller_id TEXT NOT NULL, state_dir TEXT NOT NULL)')
            connection.commit()
        yield connection
    except sqlite3.Error:
        raise GateError('instance_registry_unavailable') from None
    finally:
        connection.close()

def initialize_instance(registry_dir: Path, name: str) -> Payload:
    if not isinstance(name,str) or not name.strip() or len(name)>200:
        raise GateError('instance_name_required')
    directory = Path(registry_dir).expanduser().resolve()
    with _registry(directory,create=True) as registry:
        registry.execute('BEGIN IMMEDIATE')
        if registry.execute('SELECT 1 FROM instances WHERE name=?',(name,)).fetchone():
            raise GateError('instance_already_exists')
        id = uuid4().hex
        # Opaque installation identity stays stable when names/CRM assignments change.
        scope = Scope('partner-'+id,'seller-'+id,id)
        state_dir = directory / 'instances' / id
        store = Store(state_dir,scope)
        store.close()
        registry.execute('INSERT INTO instances VALUES(?,?,?,?,?)',
                         (id,name,scope.partner_id,scope.seller_id,str(state_dir)))
        registry.commit()
    return locate_instance(directory,id)

def list_instances(registry_dir: Path) -> list[Payload]:
    with _registry(registry_dir) as registry:
        return [dict(row) for row in registry.execute('SELECT * FROM instances ORDER BY name')]

def locate_instance(registry_dir: Path, instance_id: str | None = None) -> Payload:
    rows = list_instances(registry_dir)
    if instance_id:
        rows = [row for row in rows if row['instance_id'] == instance_id]
    if len(rows)!=1:
        raise GateError('instance_selection_required' if rows else 'instance_setup_required')
    selected = rows[0]
    state_dir = Path(selected['state_dir']).resolve()
    base = Path(registry_dir).expanduser().resolve() / 'instances'
    if not state_dir.is_relative_to(base) or not (state_dir/'state.sqlite').is_file():
        raise GateError('state_unavailable')
    return selected
