"""Bind exact native arguments to the proposal before approval, never afterwards."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from .approvals import _proposal, proposal_digest
from .models import Event, GateError, Payload, Proposal, canonical, now_utc, payload
from .store import Store

_MISSING = object()
_DRAFT_FIELDS = {'message.subject', 'message.body', 'message.to', 'message.cc', 'message.bcc'}
_TARGETS = {
    'message.subject': {'subject'},
    'message.body': {'body', 'text_content', 'content', 'text', 'body_plain', 'bodytext'},
    'message.to': {'to', 'torecipients'},
    'message.cc': {'cc', 'ccrecipients'},
    'message.bcc': {'bcc', 'bccrecipients'},
}


def _path(value: object, path: str) -> object:
    for part in path.split('.'):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
            value = value[int(part)]
        else:
            return _MISSING
    return value


def _paths(value: object, prefix: str = '') -> list[str]:
    if isinstance(value, dict) and value:
        return [item for key, child in value.items()
                for item in _paths(child, f'{prefix}.{key}'.strip('.'))]
    # Lists are indivisible mapped values. A recipient subtree is validated as
    # a complete recipient list rather than approving individual list indices.
    return [prefix]


def _recipients(value: object) -> list[str]:
    if isinstance(value, str):
        values = [item.strip() for item in value.replace(';', ',').split(',') if item.strip()]
    elif isinstance(value, list):
        values = []
        for item in value:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict) and set(item) <= {'email', 'name'} and 'email' in item:
                values.append(item['email'])
            elif isinstance(item, dict) and set(item) <= {'emailAddress'} and isinstance(item.get('emailAddress'), dict):
                address = item['emailAddress']
                if set(address) - {'address', 'name'} or 'address' not in address:
                    raise GateError('native_recipient_mismatch')
                values.append(address['address'])
            else:
                raise GateError('native_recipient_mismatch')
    else:
        raise GateError('native_recipient_mismatch')
    if any(not isinstance(item, str) or not item.strip() or '<' in item or '>' in item
           or '\r' in item or '\n' in item for item in values):
        raise GateError('native_recipient_mismatch')
    return sorted(item.strip().casefold() for item in values)


def _safe_literal(path: str, value: object, operation: str) -> bool:
    key = path.split('.')[-1].casefold()
    if key in {'contenttype', 'body_content_type'}:
        return isinstance(value, str) and value.casefold() in {'text', 'text/plain'}
    if key == 'is_html':
        return value is False
    if key == 'attachments':
        return value == []
    if operation == 'email.send' and key == 'savetosentitems':
        return value is True
    return False


def _binding(store: Store, proposal: Proposal) -> Payload:
    rows = [row for row in store.list('connection')
            if row.data.get('capability', {}).get('operation') == proposal.operation
            and row.data.get('capability', {}).get('connection_id') == proposal.connection_id]
    if len(rows) != 1 or not rows[0].data.get('account_identity'):
        raise GateError('native_binding_unavailable')
    cap = rows[0].data.get('capability', {})
    if cap.get('visibility') != 'visible' or not isinstance(cap.get('tool_name'), str) or not cap['tool_name']:
        raise GateError('native_binding_unavailable')
    return cap


def _source_context(store: Store, proposal: Proposal) -> Payload:
    """Expose only identities already covered by this proposal's selected IDs."""
    context = dict(proposal.payload, item_ids=list(proposal.item_ids))
    items = {}
    for identifier in proposal.item_ids:
        rows = [row for kind in ('account', 'contact')
                if (row := store.get(kind, identifier)) is not None]
        if len(rows) != 1:
            continue
        row = rows[0]
        if row.data.get('selected') is not True:
            continue
        campaign_id = proposal.payload.get('campaign_id')
        if campaign_id:
            from .accounts import belongs
            if not belongs(row, campaign_id):
                continue
        items[identifier] = {key: deepcopy(row.data[key]) for key in
            ('external_ref', 'crm_external_ref', 'domain', 'tax_id') if key in row.data}
    context['items'] = items
    return context


def validate_native_request(store: Store, proposal: Proposal) -> None:
    """Validate a stored mapping against canonical content and the current tool."""
    request = proposal.payload.get('native_request')
    if request is None:
        return
    if not isinstance(request, dict) or set(request) != {'tool_name', 'input', 'field_mapping'}:
        raise GateError('invalid_native_request')
    native = payload(request['input'])
    mapping = payload(request['field_mapping'])
    if not mapping or any(not isinstance(target, str) or not target or not source
                          or any(not part for part in (source + '.' + target).split('.'))
                          or source.startswith('native_request') for source, target in mapping.items()):
        raise GateError('invalid_native_mapping')
    targets = list(mapping.values())
    if len(set(targets)) != len(targets) or any(
            a != b and (a.startswith(b + '.') or b.startswith(a + '.')) for a in targets for b in targets):
        raise GateError('invalid_native_mapping')
    binding = _binding(store, proposal)
    if binding['tool_name'] != request['tool_name']:
        raise GateError('native_binding_changed')
    if proposal.operation == 'email.create_draft':
        if not _DRAFT_FIELDS.issubset(mapping) or set(mapping) - _DRAFT_FIELDS - {'message.sender_ref.object_id'}:
            raise GateError('native_message_mapping_required')
        for source, choices in _TARGETS.items():
            if mapping[source].split('.')[-1].casefold() not in choices:
                raise GateError('native_message_mapping_required')
        if 'message.sender_ref.object_id' in mapping and mapping['message.sender_ref.object_id'].split('.')[-1].casefold() not in {'from', 'sender', 'from_address'}:
            raise GateError('native_message_mapping_required')
    elif proposal.operation == 'email.send':
        if set(mapping) != {'draft_ref.object_id'}:
            raise GateError('native_draft_reference_required')
        if mapping['draft_ref.object_id'].split('.')[-1].casefold() not in {'id', 'draft_id', 'message_id', 'draftid', 'messageid'}:
            raise GateError('native_draft_reference_required')
    elif proposal.operation == 'crm.write' and isinstance(proposal.payload.get('change'), dict):
        change = proposal.payload['change']
        required = ['owner_ref.object_id']
        required.extend('change.after.' + path for path in _paths(change.get('after', {})) if path)
        if change.get('external_ref'):
            required.append('change.external_ref.object_id')
        if proposal.payload.get('account_external_ref'):
            required.append('account_external_ref.object_id')
        if any(not any(path == source or path.startswith(source + '.') for source in mapping)
               for path in required):
            raise GateError('native_crm_mapping_required', 'Mapeie os campos revisados, responsável e vínculos do item de CRM.')
    context = _source_context(store, proposal)
    for source, target in mapping.items():
        original = _path(context, source)
        actual = _path(native, target)
        if original is _MISSING:
            raise GateError('native_source_unavailable')
        if source in {'message.to', 'message.cc', 'message.bcc'}:
            if actual is _MISSING and original == []:
                continue
            if actual is _MISSING or _recipients(original) != _recipients(actual):
                raise GateError('native_recipient_mismatch')
        elif actual is _MISSING or canonical(original) != canonical(actual):
            raise GateError('native_value_mismatch')
    for leaf in _paths(native):
        if any(leaf == target or leaf.startswith(target + '.') for target in targets):
            continue
        if not _safe_literal(leaf, _path(native, leaf), proposal.operation):
            raise GateError('unmapped_native_argument')


def bind_native_request(store: Store, proposal_id: str, revision: int,
                        native_input: Payload, field_mapping: Payload) -> Proposal:
    """Create a newly reviewable revision containing the full native request."""
    native, mapping = payload(native_input), payload(field_mapping)
    with store.transaction():
        record = store.get('proposal', proposal_id)
        proposal = _proposal(record)
        if type(revision) is not int or revision != proposal.revision:
            raise GateError('revision_conflict')
        if proposal.status not in {'proposed', 'approved'} or any(
                row.data.get('proposal_id') == proposal_id for row in store.list('action')):
            raise GateError('native_request_already_started')
        content = deepcopy(proposal.payload)
        content['native_request'] = {'tool_name': _binding(store, proposal)['tool_name'],
                                     'input': native, 'field_mapping': mapping}
        changed = Proposal(proposal.id, proposal.revision + 1, proposal.operation,
            proposal.connection_id, list(proposal.item_ids), content,
            proposal_digest(proposal.operation, proposal.connection_id, proposal.item_ids, content), 'proposed')
        validate_native_request(store, changed)
        if proposal.payload.get('native_request') == content['native_request']:
            return proposal
        data = dict(record.data, revision=changed.revision, payload=content,
                    digest=changed.digest, status='proposed')
        data.pop('approval', None)
        store.put('proposal', proposal_id, data, record.revision)
        store.record_event(Event(uuid4().hex, proposal_id, 'proposal.native_request_bound', now_utc(),
                                 {'revision': changed.revision, 'digest': changed.digest}))
        return changed
