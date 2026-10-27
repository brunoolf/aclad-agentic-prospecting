"""Confirmed calendar observations. No text classifier can establish a booking."""
from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

from .accounts import belongs
from .models import Event, GateError, Payload, Record, canonical, now_utc, payload, utc
from .store import Store
from .result_metrics import confirmed_sent_message

_REF_FIELDS = {'provider', 'tenant_id', 'connection_id', 'object_id'}
_FIELDS = {'ref', 'source_revision', 'status', 'starts_at', 'ends_at', 'account_id', 'contact_ids'}


def reference(value: object) -> Payload:
    if (not isinstance(value, dict) or set(value) != _REF_FIELDS
            or any(not isinstance(v, str) or not v for v in value.values())):
        raise GateError('invalid_external_ref')
    return value


def record_meetings(store: Store, campaign_id: str, evidence_id: str,
                    observations: list[Payload]) -> list[Record]:
    """Accept only exact saved calendar objects linked through tracked participants."""
    if not isinstance(observations, list) or not observations:
        raise GateError('meeting_evidence_required')
    with store.transaction():
        action = store.get('action', evidence_id)
        if (not store.get('campaign', campaign_id) or not action
                or action.data.get('operation') != 'calendar.read'
                or action.data.get('status') != 'succeeded'
                or action.data.get('result', {}).get('complete') is not True):
            raise GateError('meeting_evidence_required')
        connections = [r for r in store.list('connection')
            if r.data.get('capability', {}).get('operation') == 'calendar.read'
            and r.data.get('capability', {}).get('connection_id') == action.data.get('connection_id')]
        if len(connections) != 1:
            raise GateError('capability_unverified')
        binding = connections[0].data
        cap = binding['capability']
        if (not binding.get('account_identity') or cap.get('visibility') != 'visible'
                or cap.get('auth') != 'authenticated' or cap.get('permission') != 'allowed'
                or cap.get('verification') != 'verified'
                or action.data.get('tool_name', cap.get('tool_name')) != cap.get('tool_name')):
            raise GateError('capability_unverified')
        result_items = action.data['result'].get('items', [])
        if not isinstance(result_items, list):
            raise GateError('meeting_evidence_required')
        evidence_refs = [reference(ref) for ref in action.data.get('external_refs', [])]
        rows = []
        seen = set()
        for raw in observations:
            observation = payload(raw)
            if set(observation) != _FIELDS:
                raise GateError('invalid_meeting_observation')
            ref = reference(observation['ref'])
            revision = observation['source_revision']
            if (type(revision) not in (str, int) or not str(revision)
                    or observation['status'] not in {'confirmed', 'cancelled'}
                    or utc(observation['starts_at']) >= utc(observation['ends_at'])):
                raise GateError('invalid_meeting_observation')
            identity = tuple(ref[k] for k in ('provider', 'tenant_id', 'connection_id'))
            if (ref['connection_id'] != action.data['connection_id']
                    or binding.get('provider', ref['provider']) != ref['provider']
                    or not any(tuple(r[k] for k in ('provider', 'tenant_id', 'connection_id')) == identity for r in evidence_refs)):
                raise GateError('connection_mismatch')
            item = {key: observation[key] for key in ('ref', 'source_revision', 'status', 'starts_at', 'ends_at')}
            matches = [row for row in result_items if isinstance(row, dict)
                       and all(row.get(key) == value for key, value in item.items())]
            if len(matches) != 1:
                raise GateError('meeting_evidence_mismatch')
            participants = matches[0].get('participant_refs')
            contacts = observation['contact_ids']
            account = store.get('account', observation['account_id']) if isinstance(observation['account_id'], str) else None
            if (not account or not belongs(account, campaign_id) or not isinstance(participants, list)
                    or not isinstance(contacts, list) or not contacts or any(not isinstance(c, str) for c in contacts)
                    or len(set(contacts)) != len(contacts)):
                raise GateError('untracked_meeting')
            for participant in participants:
                reference(participant)
            for identifier in contacts:
                contact = store.get('contact', identifier)
                if (not contact or contact.data.get('account_id') != account.id
                        or not any(contact.data.get(key) in participants for key in ('external_ref', 'calendar_ref'))
                        or not any(m.data.get('campaign_id') == campaign_id
                            and confirmed_sent_message(store, m)
                            and m.data.get('conversation_ref')
                            and m.data.get('current_message', m.data.get('message', {})).get('contact_id') == identifier
                            and m.data.get('current_message', m.data.get('message', {})).get('account_id') == account.id
                            for m in store.list('message'))):
                    raise GateError('untracked_meeting')
            key = 'meeting-' + sha256(canonical(ref).encode()).hexdigest()
            if key in seen:
                raise GateError('duplicate_meeting')
            seen.add(key)
            old = store.get('meeting', key)
            if old:
                if old.data.get('account_id') != account.id:
                    raise GateError('meeting_identity_conflict')
                old_revision = str(old.data['source_revision'])
                new_revision = str(revision)
                if old_revision == new_revision:
                    if any(old.data.get(k) != observation[k] for k in _FIELDS - {'contact_ids'}):
                        raise GateError('meeting_revision_conflict')
                    if campaign_id in old.data.get('campaign_ids', [old.data.get('campaign_id')]):
                        rows.append(old)
                        continue
                elif (not old_revision.isdecimal() or not new_revision.isdecimal()
                        or int(new_revision) <= int(old_revision)):
                    raise GateError('meeting_revision_order_required')
            campaigns = sorted(set((old.data.get('campaign_ids', []) if old else []) + [campaign_id]))
            data = dict(observation, campaign_id=campaign_id, campaign_ids=campaigns,
                        evidence_id=evidence_id, ever_confirmed=observation['status'] == 'confirmed'
                        or bool(old and old.data.get('ever_confirmed')))
            row = store.put('meeting', key, data, old.revision if old else None)
            store.record_event(Event(uuid4().hex, key, 'meeting.observed', now_utc(),
                {'evidence_id': evidence_id, 'campaign_id': campaign_id, 'status': data['status']}))
            rows.append(row)
        return rows
