"""Retrieve reviewed sales rules by audience and applicability."""
from .models import GateError, Payload, payload, utc

def validate_source(source: Payload) -> Payload:
    source = payload(source)
    required = {'id','source_file','source_page','source_date','reviewed_at','stage',
                'industry','persona','audience','status','rule','valid_until'}
    if not required.issubset(source):
        raise GateError('source_metadata_required')
    if source['audience'] not in {'authoring','partner'} or source['status'] not in {'unreviewed','approved','expired'}:
        raise GateError('invalid_source_status')
    if source['status'] == 'approved':
        if not source['source_file'] or type(source['source_page']) is not int or source['source_page'] < 1 or not source['rule']:
            raise GateError('source_metadata_required')
        utc(source['reviewed_at'])
    if source['valid_until'] is not None:
        utc(source['valid_until'])
    return source

def select_playbooks(catalog: list[Payload], stage: str, industry: str | None,
                     persona: str | None, audience: str, now: str) -> list[Payload]:
    instant = utc(now)
    result = []
    for raw in catalog:
        rule = validate_source(raw)
        if rule['status'] != 'approved' or rule['audience'] != audience:
            continue
        if rule['stage'] != stage or rule['industry'] not in (None, industry) or rule['persona'] not in (None, persona):
            continue
        if rule['valid_until'] and utc(rule['valid_until']) <= instant:
            continue
        result.append(rule)
    return result
