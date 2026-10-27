"""Transactional schema initialization; future versions must migrate explicitly."""
import sqlite3
from .models import GateError

SCHEMA = (
    'CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
    '''CREATE TABLE IF NOT EXISTS records (
       kind TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
       data TEXT NOT NULL, PRIMARY KEY(kind,id))''',
    '''CREATE TABLE IF NOT EXISTS events (
       sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
       record_id TEXT NOT NULL, kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
       data TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS leases (
       key TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at TEXT NOT NULL)''',
)

def migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version not in (0, 1):
        raise GateError('unsupported_schema_version')
    for statement in SCHEMA:
        connection.execute(statement)
    connection.execute('PRAGMA user_version=1')
