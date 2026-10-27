"""Explicit recovery is safe even when the host never runs session hooks."""
from __future__ import annotations

from uuid import uuid4

from .models import Event, Record, Snapshot, now_utc, utc
from .store import Store


def context_snapshot(store: Store) -> Snapshot:
    """Keep the canonical corpus durable without dumping it into every new chat."""
    snapshot = store.snapshot()
    records = []
    for record in snapshot.records:
        data = record.data
        if record.kind == 'analysis' and data.get('type') == 'research_page':
            data = {key: data[key] for key in ('type', 'subject_id', 'research_id', 'url', 'title',
                'status', 'sha256', 'collected_at', 'published_at', 'categories', 'trust') if key in data}
            data['content_access'] = 'research-context'
        elif record.kind == 'analysis' and data.get('type') == 'research_host_evidence':
            data = {key: data[key] for key in ('type', 'research_id', 'subject_id', 'source_kind',
                'evidence_id', 'trust', 'recorded_at') if key in data} | {
                'item_count': len(record.data.get('items', [])),
                'content_access': 'research-context',
            }
        elif record.kind == 'analysis' and data.get('type') == 'research_run':
            data = {key: data[key] for key in ('type', 'subject_id', 'purpose', 'website', 'status',
                'created_at', 'updated_at') if key in data} | {
                'queued_count': len(record.data.get('queue', [])),
                'collected_count': len(record.data.get('page_ids', [])),
                'content_access': 'research-context',
            }
        records.append(Record(record.id, record.kind, record.revision, data))
    by_key = {(record.kind, record.id): record for record in records}
    pending = [by_key[(record.kind, record.id)] for record in snapshot.pending]
    return Snapshot(snapshot.event_sequence, records, pending)


def bootstrap(store: Store, now: str | None = None) -> Snapshot:
    """Expose interrupted effects for reconciliation without invoking a provider."""
    instant = now or now_utc()
    utc(instant)
    with store.transaction():
        for action in store.list('action'):
            if action.data.get('status') != 'in_flight':
                continue
            lease_owner = 'recovery-' + uuid4().hex
            if not store.acquire_lease('action:' + action.id, lease_owner, instant, 300):
                continue
            store.put('action', action.id,
                      dict(action.data, status='unknown', recovery_required=True), action.revision)
            store.record_event(Event('recovery-' + action.id, action.id, 'reconciliation_required',
                                     instant, {'reason': 'interrupted_in_flight'}))
            store.release_lease('action:' + action.id, lease_owner)
        snapshot = context_snapshot(store)
    from .local_views import refresh_local_views
    refresh_local_views(store)
    return snapshot


def checkpoint(store: Store) -> Snapshot:
    """Return a coherent durable projection; records/events are already committed.

    No transcript or recursive snapshot is copied into a second state store.
    """
    from .local_views import refresh_local_views
    refresh_local_views(store)
    return context_snapshot(store)
