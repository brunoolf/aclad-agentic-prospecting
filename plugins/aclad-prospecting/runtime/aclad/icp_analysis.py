"""Deterministic account populations and transparent data quality, without scoring."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal, localcontext
import re

from .models import ExternalRef, GateError, Payload, canonical, payload, utc


DIMENSIONS = ('country', 'state', 'industry', 'subindustry', 'employees',
              'annual_revenue', 'solutions')
_REF_KEYS = {'provider', 'tenant_id', 'connection_id', 'object_id'}


def external_ref(value: object) -> dict[str, str]:
    if isinstance(value, ExternalRef):
        value = asdict(value)
    if (not isinstance(value, dict) or set(value) != _REF_KEYS
            or any(not isinstance(v, str) or not v.strip() for v in value.values())):
        raise GateError('invalid_external_ref', 'Use a complete provider/tenant/connection/object reference.')
    return dict(value)


def money(value: object) -> Payload:
    """Exact amount or bounded range, with optional source-supplied reference year."""
    if not isinstance(value, dict):
        raise GateError('invalid_money')
    keys = set(value)
    optional = {'year', 'source', 'collected_at', 'estimated'}
    required = {'amount', 'currency'} if 'amount' in value else {'lower', 'upper', 'currency'}
    if not required.issubset(keys) or keys - required - optional:
        raise GateError('invalid_money', 'Use an amount or lower/upper range and an explicit currency.')
    currency = value['currency']
    if not isinstance(currency, str) or re.fullmatch(r'[A-Z]{3}', currency) is None:
        raise GateError('invalid_money', 'Confirm the ISO currency; no implicit conversion is performed.')
    amounts = ('amount',) if 'amount' in value else ('lower', 'upper')
    for key in amounts:
        amount = value[key]
        if (not isinstance(amount, str) or len(amount) > 60
                or re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', amount) is None):
            raise GateError('invalid_money', 'Use exact nonnegative decimal strings.')
    if len(amounts) == 2 and Decimal(value['lower']) > Decimal(value['upper']):
        raise GateError('invalid_money', 'The lower amount must not exceed the upper amount.')
    if 'year' in value and (type(value['year']) is not int or not 1900 <= value['year'] <= 9999):
        raise GateError('invalid_money')
    if 'estimated' in value and type(value['estimated']) is not bool:
        raise GateError('invalid_money')
    if 'source' in value and (not isinstance(value['source'], str) or not value['source'].strip()):
        raise GateError('invalid_money')
    if 'collected_at' in value:
        utc(value['collected_at'])
    return deepcopy(value)


def revenue_match(observed: object, predicate: Payload) -> str:
    """A partial overlap, missing comparable currency/year or malformed fact is unknown."""
    expected = money(predicate.get('value'))
    operator = predicate.get('operator')
    if operator not in {'gte', 'lte', 'between'}:
        raise GateError('invalid_icp_predicate')
    if operator == 'between' and 'lower' not in expected:
        raise GateError('invalid_icp_predicate')
    if operator in {'gte', 'lte'} and 'amount' not in expected:
        raise GateError('invalid_icp_predicate')
    try:
        actual = money(observed)
    except GateError:
        return 'unknown'
    if actual['currency'] != expected['currency']:
        return 'unknown'
    if 'year' in expected and actual.get('year') != expected['year']:
        return 'unknown'
    lower = Decimal(actual.get('amount', actual.get('lower')))
    upper = Decimal(actual.get('amount', actual.get('upper')))
    minimum = Decimal(expected['lower']) if operator == 'between' else Decimal(expected['amount']) if operator == 'gte' else Decimal('0')
    maximum = Decimal(expected['upper']) if operator == 'between' else Decimal(expected['amount']) if operator == 'lte' else Decimal('Infinity')
    if lower >= minimum and upper <= maximum:
        return 'match'
    if upper < minimum or lower > maximum:
        return 'no_match'
    return 'unknown'


def dimension_value(field: str, value: object) -> object:
    """One source-field contract shared by analysis, ingestion and selection."""
    if value is None:
        return None
    if field in {'is_customer', 'is_worked'}:
        if type(value) is not bool:
            raise GateError('invalid_boolean')
    elif field == 'owner_ref':
        return external_ref(value)
    elif field == 'annual_revenue':
        return money(value)
    elif field == 'employees':
        if type(value) is not int or value < 0:
            raise GateError('invalid_employees')
    elif field == 'solutions':
        if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
            raise GateError('invalid_solutions')
        return sorted(set(value)) or None
    elif field == 'source_at':
        utc(value)
    elif not isinstance(value, str) or not value.strip():
        raise GateError('invalid_dimension')
    return value


def _dimension(accounts: list[Payload], field: str) -> Payload:
    values = [a[field] for a in accounts if a.get(field) is not None]
    result = {'known_count': len(values), 'unknown_count': len(accounts) - len(values)}
    if field == 'annual_revenue':
        groups = {}
        for value in values:
            groups.setdefault((value['currency'], value.get('year')), []).append(value)
        rows = []
        for (currency, year), observations in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1] or 0)):
            amounts = [value['amount'] for value in observations if 'amount' in value]
            ranges = [value for value in observations if 'lower' in value]
            row = {'currency': currency, 'count': len(observations)}
            if year is not None:
                row['year'] = year
            counts = Counter(amounts)
            row['distribution'] = [{'amount': a, 'count': counts[a]} for a in sorted(counts, key=Decimal)]
            if ranges:
                row.update(range_count=len(ranges), ranges=deepcopy(ranges))
            else:
                with localcontext() as context:
                    context.prec = 100 + len(str(len(amounts)))
                    row['total'] = format(sum((Decimal(a) for a in amounts), Decimal('0')), 'f')
            rows.append(row)
        result['groups'] = rows
    else:
        counts = Counter(v for group in values for v in group) if field == 'solutions' else Counter(values)
        result['distribution'] = [{'value': value, 'count': counts[value]}
                                  for value in sorted(counts)]
    return result


def analyze_icps(accounts: list[Payload], seller_ref: ExternalRef,
                 coverage: Payload) -> dict[str, Payload]:
    """Analyze unique enterprises; never infer customer status, ownership or FX."""
    seller = external_ref(seller_ref)
    coverage = payload(coverage)
    if (set(coverage) != {'scope', 'complete', 'filters', 'as_of'}
            or coverage['scope'] not in ('whole_company', 'accessible_subset', 'sample')
            or type(coverage['complete']) is not bool
            or not isinstance(coverage['filters'], list)
            or any(not isinstance(f, str) for f in coverage['filters'])):
        raise GateError('invalid_coverage', 'State the actual CRM visibility, filters and extraction date.')
    utc(coverage['as_of'])
    if not isinstance(accounts, list):
        raise GateError('invalid_accounts')
    unique, conflicts, errors = {}, {}, []
    invalid_count = 0
    fields = ('owner_ref', 'is_customer', 'is_worked', 'source_at', *DIMENSIONS)
    for index, account in enumerate(accounts):
        try:
            raw = payload(account)
            key = canonical(external_ref(raw.get('ref')))
        except GateError as exc:
            errors.append({'record_index': index, 'field': 'ref', 'code': exc.code})
            invalid_count += 1
            continue
        normalized = {}
        for field in fields:
            try:
                normalized[field] = dimension_value(field, raw.get(field))
            except GateError as exc:
                normalized[field] = None
                errors.append({'record_index': index, 'field': field, 'code': exc.code})
        if key not in unique:
            unique[key], conflicts[key] = normalized, set()
            continue
        existing = unique[key]
        for field, value in normalized.items():
            if field in conflicts[key] or value is None:
                continue
            if existing[field] is None:
                existing[field] = value
            elif existing[field] != value:
                # Conflicting opportunity rows cannot establish an enterprise fact.
                existing[field] = None
                conflicts[key].add(field)
                errors.append({'record_index': index, 'field': field, 'code': 'conflicting_duplicate'})
    populations = {'partner_customers': [], 'seller_customers': [], 'seller_prospects': []}
    unclassified = dict.fromkeys(populations, 0)
    for account in unique.values():
        customer, owner, worked = account['is_customer'], account['owner_ref'], account['is_worked']
        if customer is True:
            populations['partner_customers'].append(account)
            if owner == seller:
                populations['seller_customers'].append(account)
            elif owner is None:
                unclassified['seller_customers'] += 1
        elif customer is None:
            unclassified['partner_customers'] += 1
            if owner in (seller, None):
                unclassified['seller_customers'] += 1
        if customer is False and worked is True and owner == seller:
            populations['seller_prospects'].append(account)
        elif customer in (None, False) and worked is not False and owner in (seller, None):
            unclassified['seller_prospects'] += 1
    limitations = []
    if coverage['scope'] != 'whole_company':
        limitations.append('Visibility describes a subset or sample, not all partner customers.')
    if not coverage['complete']:
        limitations.append('CRM extraction is incomplete for the declared scope.')
    if errors:
        limitations.append('Invalid or conflicting fields remain unknown; inspect record-level errors.')
    result = {}
    for name, members in populations.items():
        dimensions = {field: _dimension(members, field) for field in DIMENSIONS}
        gaps = any(d['unknown_count'] for d in dimensions.values())
        local_limits = list(limitations)
        if gaps:
            local_limits.append('Some dimensions have missing data; no confidence percentage is inferred.')
        if unclassified[name]:
            local_limits.append('Unresolved customer status or ownership prevents full classification.')
        result[name] = {'population_count': len(members), 'coverage': deepcopy(coverage),
                        'dimensions': dimensions, 'unclassified_count': unclassified[name],
                        'invalid_record_count': invalid_count, 'errors': deepcopy(errors),
                        'limitations': local_limits,
                        'interpretation': ('effort_not_success' if name == 'seller_prospects'
                                           else 'observed_customers_not_causality')}
    return result
