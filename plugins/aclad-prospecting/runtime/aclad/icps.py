"""Reviewed ICP versions and immutable campaign bindings."""
from copy import deepcopy
import hashlib
import unicodedata
from uuid import uuid4

from .icp_analysis import DIMENSIONS, money
from .models import Event, GateError, Payload, Record, canonical, now_utc, payload
from .store import Store


def _predicates(values: object) -> list[Payload]:
    if not isinstance(values, list):
        raise GateError('invalid_icp_predicate')
    result = []
    for raw in values:
        predicate = payload(raw)
        if (set(predicate) != {'field', 'operator', 'value', 'basis'}
                or predicate['field'] not in DIMENSIONS
                or predicate['operator'] not in ('in', 'not_in', 'gte', 'lte', 'between')
                or predicate['basis'] not in ('evidence', 'hypothesis')):
            raise GateError('invalid_icp_predicate', 'Use a known dimension, operator and explicit evidence/hypothesis basis.')
        field, operator, value = predicate['field'], predicate['operator'], predicate['value']
        if field == 'annual_revenue':
            if operator not in {'gte', 'lte', 'between'}:
                raise GateError('invalid_icp_predicate')
            predicate['value'] = money(value)
            if (operator == 'between') != ('lower' in predicate['value']):
                raise GateError('invalid_icp_predicate', 'Use an amount for a bound or a lower/upper range for between.')
        elif operator in {'gte', 'lte', 'between'}:
            if operator == 'between' or field != 'employees' or type(value) is not int or value < 0:
                raise GateError('invalid_icp_predicate')
        elif (not isinstance(value, list) or not value
                or (field == 'employees' and any(type(v) is not int or v < 0 for v in value))
                or (field != 'employees' and any(not isinstance(v, str) or not v.strip() for v in value))):
            raise GateError('invalid_icp_predicate')
        result.append(predicate)
    return result


def _sources(store: Store, source_ids: object) -> dict[str, int]:
    if (not isinstance(source_ids, list)
            or any(not isinstance(id, str) or not id for id in source_ids)
            or len(source_ids) != len(set(source_ids))):
        raise GateError('invalid_icp_source')
    versions = {}
    for id in source_ids:
        source = store.get('analysis', id)
        if not source:
            raise GateError('icp_source_not_found', 'Historical criteria require saved private analysis references.')
        versions[id] = source.revision
    return versions


# A bounded local vocabulary for the pilot's Brazilian territory. This is not
# a global geocoder: other country codes retain literal legacy comparison.
_BR_COUNTRIES = {'br', 'brasil', 'brazil'}
_BR_UFS = {
    'ac': 'acre', 'al': 'alagoas', 'am': 'amazonas', 'ap': 'amapa',
    'ba': 'bahia', 'ce': 'ceara', 'df': 'distrito federal', 'es': 'espirito santo',
    'go': 'goias', 'ma': 'maranhao', 'mg': 'minas gerais', 'ms': 'mato grosso do sul',
    'mt': 'mato grosso', 'pa': 'para', 'pb': 'paraiba', 'pe': 'pernambuco',
    'pi': 'piaui', 'pr': 'parana', 'rj': 'rio de janeiro', 'rn': 'rio grande do norte',
    'ro': 'rondonia', 'rr': 'roraima', 'rs': 'rio grande do sul', 'sc': 'santa catarina',
    'se': 'sergipe', 'sp': 'sao paulo', 'to': 'tocantins',
}
# These UF abbreviations are also country/territory codes. A bare MG, for
# example, cannot establish Brazil without a country/full-name/UF anchor.
_AMBIGUOUS_UFS = set('al am ba es ma mg ms mt pa pe pr ro rs sc se to'.split())
_BR_STATE_NAMES = {name: code for code, name in _BR_UFS.items()}


def _geo_token(value: str) -> str:
    return ' '.join(''.join(char for char in unicodedata.normalize('NFKD', value)
                           if not unicodedata.combining(char)).casefold().split())


def _territory_match(territory: list[str], field: str, values: list[str]) -> str:
    configured = {_geo_token(value) for value in territory}
    proposed = {_geo_token(value) for value in values}
    brazil = bool(configured & (_BR_COUNTRIES | set(_BR_STATE_NAMES)
                               | (set(_BR_UFS) - _AMBIGUOUS_UFS)))
    if field == 'country':
        # Opaque legacy country codes compare literally, never infer their
        # states. Ambiguous UF/country codes require explicit geographic context.
        countries = {value for value in configured
                     if len(value) == 2 and value.isascii() and value.isalpha()
                     and value not in _BR_UFS}
        if brazil:
            countries.add('br')
        target = {'br' if value in _BR_COUNTRIES else value for value in proposed}
        if not countries:
            return 'unknown'
        return 'match' if target <= countries else 'different'
    if not brazil:
        return 'unknown'
    state_codes = {code: code for code in _BR_UFS} | _BR_STATE_NAMES
    if any(value not in state_codes for value in proposed):
        return 'unknown'
    if any(value not in state_codes and value not in _BR_COUNTRIES for value in configured):
        return 'unknown'
    states = {state_codes[value] for value in configured if value in state_codes}
    target = {state_codes[value] for value in proposed}
    # An explicit Brazil-only territory encompasses its known states; a seller
    # state recut is narrower and must contain every proposed state.
    return 'match' if not states or target <= states else 'different'


def _state_recut(criteria: list[Payload], exclusions: list[Payload]) -> list[str] | None:
    """Conjoin positive sets and subtract negatives without changing saved rules."""
    included, excluded = None, set()
    for predicates, is_exclusion in ((criteria, False), (exclusions, True)):
        for predicate in predicates:
            if predicate['field'] != 'state':
                continue
            # Match the runtime gate's literal predicate semantics here.
            # Normalizing aliases before subtraction could hide a state the
            # actual gate still accepts (RJ is not the token Rio de Janeiro).
            values = set(predicate['value'])
            if (predicate['operator'] == 'in') != is_exclusion:
                included = values if included is None else included & values
            else:
                excluded.update(values)
    return None if included is None else sorted(included - excluded)


def _context(store: Store, criteria: list[Payload], icp_exclusions: list[Payload]) -> tuple[list[str], list[Payload]]:
    current = store.get('profile', 'current')
    profile = current.data if current else {}
    exclusions = profile.get('icp', {}).get('exclusions', [])
    if not isinstance(exclusions, list) or any(not isinstance(e, str) for e in exclusions):
        raise GateError('invalid_commercial_exclusions')
    divergences = []
    territory = profile.get('seller', {}).get('territory', [])
    industries = profile.get('partner', {}).get('industries', [])
    for predicate in criteria:
        if predicate['operator'] != 'in' or predicate['field'] == 'state':
            continue
        field = predicate['field']
        reference = territory if field in {'country', 'state'} else industries if field == 'industry' else []
        comparison = (_territory_match(reference, field, predicate['value'])
                      if reference and field in {'country', 'state'} else
                      'different' if reference and not set(reference).intersection(predicate['value']) else 'match')
        if comparison != 'match':
            divergences.append({'field': field, 'configured': deepcopy(reference),
                                'proposed': deepcopy(predicate['value']),
                                'reason': ('Configured territory is ambiguous or unknown at this geographic level; review its scope.'
                                           if comparison == 'unknown' else
                                           'Proposed targeting differs from the configured seller/partner scope.')})
    state_target = _state_recut(criteria, icp_exclusions)
    state_aliases = set(_BR_UFS) | set(_BR_STATE_NAMES)
    configured_states = any(_geo_token(value) in state_aliases for value in territory)
    if territory and (state_target is not None or configured_states):
        comparison = _territory_match(territory, 'state', state_target) if state_target else 'unknown'
        if comparison != 'match':
            divergences.append({'field': 'state', 'configured': deepcopy(territory),
                'proposed': deepcopy(state_target) if state_target is not None else [],
                'reason': ('State targeting is absent, ambiguous, empty or exclusion-only; review the configured state scope.'
                           if comparison == 'unknown' else
                           'Proposed targeting differs from the configured seller/partner scope.')})
    return deepcopy(exclusions), divergences


def _content(data: Payload) -> Payload:
    return {key: deepcopy(data[key]) for key in
            ('criteria', 'exclusions', 'source_ids', 'source_versions', 'strategic',
             'partner_exclusions', 'divergences')}


def propose_icp(store: Store, criteria: list[Payload], exclusions: list[Payload],
                source_ids: list[str], strategic: bool) -> Record:
    """Create a reviewable proposal; no campaign or budget changes here."""
    criteria, exclusions = _predicates(criteria), _predicates(exclusions)
    if not criteria or type(strategic) is not bool:
        raise GateError('invalid_icp', 'An ICP needs criteria and an explicit strategic flag.')
    with store.transaction():
        source_versions = _sources(store, source_ids)
        if not source_versions and (not strategic or any(
                p['basis'] == 'evidence' for p in criteria + exclusions)):
            raise GateError('icp_evidence_required', 'Without historical evidence, mark strategic criteria as hypotheses.')
        partner_exclusions, divergences = _context(store, criteria, exclusions)
        now, id = now_utc(), 'icp-' + uuid4().hex
        data = {'criteria': criteria, 'exclusions': exclusions, 'source_ids': list(source_ids),
                'source_versions': source_versions, 'strategic': strategic,
                'partner_exclusions': partner_exclusions, 'divergences': divergences,
                'status': 'proposed', 'created_at': now, 'approved_versions': {}}
        record = store.put('icp', id, data, None)
        store.record_event(Event('evt-' + uuid4().hex, id, 'icp_proposed', now,
                                 {'revision': record.revision, 'strategic': strategic,
                                  'source_ids': list(source_ids), 'divergence_count': len(divergences)}))
        return record


def approve_icp(store: Store, id: str, revision: int, approved_by: str) -> Record:
    """Approve the exact current proposal, retaining prior approved snapshots."""
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise GateError('icp_approver_required')
    with store.transaction():
        current = store.get('icp', id)
        if not current:
            raise GateError('icp_not_found')
        if type(revision) is not int or current.revision != revision:
            raise GateError('revision_conflict')
        if current.data.get('status') != 'proposed':
            raise GateError('icp_not_proposed')
        data = deepcopy(current.data)
        _predicates(data['criteria'])
        _predicates(data['exclusions'])
        if (not data['criteria'] or type(data['strategic']) is not bool
                or (not data['source_ids'] and (not data['strategic'] or any(
                    p['basis'] == 'evidence' for p in data['criteria'] + data['exclusions'])))):
            raise GateError('icp_evidence_required')
        if _sources(store, data['source_ids']) != data['source_versions']:
            raise GateError('icp_source_changed', 'Revisit the profile after its supporting analysis changes.')
        # Current commercial restrictions cannot be dropped by a personal recut.
        partner_exclusions, divergences = _context(store, data['criteria'], data['exclusions'])
        if partner_exclusions != data['partner_exclusions'] or divergences != data['divergences']:
            raise GateError('icp_context_changed', 'Rebuild the proposal after a configuration change.')
        now, approved_revision = now_utc(), revision + 1
        snapshot = _content(data)
        snapshot.update(approved_by=approved_by, approved_at=now, revision=approved_revision)
        digest = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
        snapshot['digest'] = digest
        versions = dict(data.get('approved_versions', {}))
        versions[str(approved_revision)] = snapshot
        data.update(status='active', approved_by=approved_by, approved_at=now,
                    approved_versions=versions, approved_revision=approved_revision)
        record = store.put('icp', id, data, revision)
        store.record_event(Event('evt-' + uuid4().hex, id, 'icp_approved', now,
                                 {'revision': record.revision, 'reviewed_revision': revision,
                                  'approved_by': approved_by, 'digest': digest}))
        return record


def bind_icp(store: Store, campaign_id: str, icp_id: str, revision: int) -> Record:
    """Bind an approved snapshot once; a new target needs a new campaign."""
    with store.transaction():
        campaign, profile = store.get('campaign', campaign_id), store.get('icp', icp_id)
        if not campaign:
            raise GateError('campaign_not_found')
        if not profile or type(revision) is not int:
            raise GateError('icp_not_approved')
        snapshot = profile.data.get('approved_versions', {}).get(str(revision))
        if not snapshot:
            raise GateError('icp_not_approved', 'Select an approved ICP revision.')
        content = {key: value for key, value in snapshot.items() if key != 'digest'}
        if hashlib.sha256(canonical(content).encode()).hexdigest() != snapshot['digest']:
            raise GateError('icp_snapshot_changed')
        data = dict(campaign.data)
        if 'icp_id' in data:
            if data['icp_id'] == icp_id and data.get('icp_revision') == revision:
                return campaign
            raise GateError('campaign_target_immutable', 'Create a new campaign for a different ICP version.')
        data.update(icp_id=icp_id, icp_revision=revision, icp_snapshot=deepcopy(snapshot))
        record = store.put('campaign', campaign_id, data, campaign.revision)
        store.record_event(Event('evt-' + uuid4().hex, campaign_id, 'icp_bound', now_utc(),
                                 {'revision': record.revision, 'icp_id': icp_id,
                                  'icp_revision': revision, 'digest': snapshot['digest']}))
        return record
