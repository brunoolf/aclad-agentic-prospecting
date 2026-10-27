"""Private configuration and reviewable, non-executable profile packages."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import uuid4

from .models import Event, GateError, Payload, Record
from .store import Store
from .portfolio import OFFERING_SHAPE, validate_offerings

# Every dictionary has an explicit shape; free-text is always inert data.
STR = 'string'
STRINGS = [STR]
PARTNER = {key: STRINGS for key in ('regions', 'products', 'services', 'industries',
    'differentiators', 'authorized_references', 'commercial_rules')}
PARTNER.update({'name': STR, 'country': STR, 'website': STR, 'offerings': [OFFERING_SHAPE]})
CRITERIA = {key: STRINGS for key in ('countries', 'states', 'industries', 'subindustries',
    'size_bands', 'products', 'services', 'regions')}
CRITERIA.update({key: STR for key in ('revenue_min', 'revenue_max', 'currency', 'revenue_year', 'notes')})
CRITERIA.update({'employee_min': 'integer', 'employee_max': 'integer'})
TEMPLATE = {key: STR for key in ('name', 'subject', 'body', 'language', 'purpose')}
RULE = {'text': STR, 'applicability': STR}
PERSONAL = {'language': STR, 'territory': STRINGS, 'size_bands': STRINGS, 'writing_style': STR}
SELLER = {**PERSONAL, 'name': STR, 'crm_user_id': STR, 'signature': STR,
          'portfolio': STR, 'writing_examples': [{'id': STR, 'text': STR}],
          'selected_example_ids': STRINGS}
MAPPING = {key: STR for key in ('provider', 'customer_field', 'customer_value',
    'owner_field', 'won_field', 'won_value', 'prospect_field', 'prospect_value',
    'account_id_field', 'annual_revenue_field', 'currency_field', 'revenue_year_field')}
SCHEDULE = {'mode': STR, 'days': ['integer'], 'times': STRINGS, 'timezone': STR, 'paused': 'boolean'}
SECTIONS = {'partner': PARTNER, 'icp.criteria': CRITERIA, 'icp.exclusions': STRINGS,
            'rules.confirmed': [RULE], 'templates': [TEMPLATE],
            'tool_suggestions': STRINGS, 'personal': PERSONAL}
PROFILE = {'language': STR, 'partner': PARTNER, 'seller': SELLER,
           'tool_suggestions': STRINGS, 'crm_mapping': MAPPING,
           'schedule_preferences': SCHEDULE, 'templates': [TEMPLATE],
           'icp': {'criteria': CRITERIA, 'exclusions': STRINGS},
           'rules': {'confirmed': [RULE]},
           'imported_review_pending': {key: value for key, value in SECTIONS.items()
                                       if key.startswith(('icp.', 'rules.'))}}
MAX_BYTES = 1024 * 1024


def _json(value: object) -> object:
    try:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode('utf-8')) > MAX_BYTES:
            raise GateError('profile_too_large', 'Profile exceeds 1 MiB.')
        return json.loads(serialized)
    except (TypeError, ValueError, RecursionError) as exc:
        raise GateError('invalid_profile', 'Profile must contain finite JSON data.') from exc


def _validate(value: object, shape: object, path: str = '') -> None:
    if isinstance(shape, dict):
        if not isinstance(value, dict) or set(value) - set(shape):
            raise GateError('invalid_profile', f'Unknown field or invalid object at {path or "profile"}.')
        for key, child in value.items():
            _validate(child, shape[key], f'{path}.{key}'.strip('.'))
    elif isinstance(shape, list):
        if not isinstance(value, list):
            raise GateError('invalid_profile', f'Expected list at {path}.')
        for child in value:
            _validate(child, shape[0], path)
    else:
        expected = {'string': str, 'integer': int, 'boolean': bool}[shape]
        if type(value) is not expected:
            raise GateError('invalid_profile', f'Invalid value at {path}.')


def _filter(value: object, shape: object) -> object:
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return {}
        return {key: _filter(child, shape[key]) for key, child in value.items() if key in shape}
    if isinstance(shape, list):
        return [_filter(child, shape[0]) for child in value] if isinstance(value, list) else []
    return deepcopy(value)


def validate_profile(payload: Payload) -> Payload:
    clean = _json(payload)
    _validate(clean, PROFILE)
    if 'offerings' in clean.get('partner', {}):
        clean['partner']['offerings'] = validate_offerings(clean['partner']['offerings'])
    return clean


def _current(store: Store) -> Payload:
    record = store.get('profile', 'current')
    return deepcopy(record.data) if record else {}


def _lookup(data: Payload, path: str) -> object:
    value: object = data
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _assign(data: Payload, path: str, value: object) -> None:
    parts = path.split('.')
    target = data
    for key in parts[:-1]:
        if not isinstance(target.get(key), dict):
            target[key] = {}
        target = target[key]
    target[parts[-1]] = deepcopy(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_profile(store: Store, payload: Payload, event_kind: str = 'profile.updated') -> Record:
    clean = validate_profile(payload)
    with store.transaction():
        old = store.get('profile', 'current')
        record = store.put('profile', 'current', clean, old.revision if old else None)
        store.record_event(Event(str(uuid4()), record.id, event_kind, _now(),
                                 {'revision': record.revision}))
        from .recovery import checkpoint
        checkpoint(store)
    return record


def export_profile(store: Store, sections: list[str]) -> Payload:
    if not isinstance(sections, list) or any(section not in SECTIONS for section in sections):
        raise GateError('invalid_profile_section', 'Select supported profile sections.')
    current = _current(store)
    exported = {}
    for section in sections:
        source = current.get('seller', {}) if section == 'personal' else _lookup(current, section)
        if source is not None:
            exported[section] = _filter(source, SECTIONS[section])
    package = {'format': 'aclad-profile', 'version': 1, 'created_at': _now(), 'sections': exported}
    _package(package)
    return package


def _package(package: Payload) -> Payload:
    clean = _json(package)
    if not isinstance(clean, dict) or set(clean) != {'format', 'version', 'created_at', 'sections'}:
        raise GateError('invalid_profile_package', 'Expected a versioned profile package.')
    if type(clean['version']) is not int or clean['version'] != 1:
        raise GateError('unsupported_profile_version', 'Unsupported profile version.')
    if clean['format'] != 'aclad-profile' or not isinstance(clean['created_at'], str):
        raise GateError('invalid_profile_package', 'Invalid profile format or creation date.')
    try:
        timestamp = datetime.fromisoformat(clean['created_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('timezone required')
    except ValueError as exc:
        raise GateError('invalid_profile_package', 'Creation date needs an ISO timestamp with timezone.') from exc
    _validate(clean['sections'], SECTIONS, 'sections')
    if 'offerings' in clean['sections'].get('partner', {}):
        validate_offerings(clean['sections']['partner']['offerings'])
    return clean


def _leaves(value: object, path: str):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(child, f'{path}.{key}')
    else:
        yield path, value


def _import_target(current: Payload, section: str, path: str) -> object:
    if section.startswith(('icp.', 'rules.')):
        pending = current.get('imported_review_pending', {})
        value = pending.get(section) if isinstance(pending, dict) else None
        suffix = path[len(section):].lstrip('.')
        return _lookup(value, suffix) if suffix and isinstance(value, dict) else value
    return _lookup(current, 'seller' + path[len('personal'):] if section == 'personal' else path)


def preview_import(store: Store, package: Payload) -> list[Payload]:
    clean = _package(package)
    current = _current(store)
    return [{'path': path, 'old': _import_target(current, section, path), 'new': deepcopy(value)}
            for section, content in clean['sections'].items()
            for path, value in _leaves(content, section)]


def apply_import(store: Store, package: Payload, accepted_paths: list[str]) -> Record:
    with store.transaction():
        clean = _package(package)
        changes = {change['path']: change for change in preview_import(store, clean)}
        if not isinstance(accepted_paths, list) or any(path not in changes for path in accepted_paths):
            raise GateError('invalid_import_selection', 'Select exact paths from the import preview.')
        current = _current(store)
        for path in accepted_paths:
            value = deepcopy(changes[path]['new'])
            if path == 'partner.offerings':
                for offer in value:
                    offer['status'] = 'pending_review'
                    offer.pop('approved_by', None)
            section = next(s for s in clean['sections'] if path == s or path.startswith(s + '.'))
            if section.startswith(('icp.', 'rules.')):
                pending = current.setdefault('imported_review_pending', {})
                suffix = path[len(section):].lstrip('.')
                if suffix:
                    _assign(pending.setdefault(section, {}), suffix, value)
                else:
                    pending[section] = deepcopy(value)
            else:
                _assign(current, 'seller' + path[len('personal'):] if section == 'personal' else path, value)
        return save_profile(store, current, 'profile.imported')

def migrate_legacy_profile(store: Store, legacy: Payload) -> Record:
    """Explicit migration only; old authorizations and operational data never transfer."""
    with store.transaction():
        source = _json(legacy)
        if not isinstance(source, dict):
            raise GateError('invalid_profile', 'Legacy profile must be an object.')
        current = _current(store)
        for key in ('language', 'partner'):
            if key in source:
                incoming = _filter(source[key], PROFILE[key])
                if key == 'partner':
                    for offer in incoming.get('offerings', []):
                        offer['status'] = 'pending_review'
                        offer.pop('approved_by', None)
                    # Only incoming fields replace local context. An unrelated
                    # legacy section cannot revoke a locally reviewed portfolio.
                    incoming = {**current.get('partner', {}), **incoming}
                current[key] = incoming
        tools = []
        crm = source.get('crm', {})
        if isinstance(crm, dict) and isinstance(crm.get('tool'), str):
            tools.append(crm['tool'])
        for key in ('dataSources', 'outreachChannels'):
            tools.extend(x for x in source.get(key, []) if isinstance(x, str))
        current['tool_suggestions'] = list(dict.fromkeys(tools))
        old_icp = source.get('idealCustomer')
        if isinstance(old_icp, dict):
            criteria = {}
            for old, new in (('verticals', 'industries'), ('geography', 'regions')):
                if old in old_icp:
                    criteria[new] = old_icp[old]
            current.setdefault('imported_review_pending', {})['icp.criteria'] = criteria
            if 'disqualifiers' in old_icp:
                current['imported_review_pending']['icp.exclusions'] = old_icp['disqualifiers']
        return save_profile(store, current, 'profile.legacy_migrated')
