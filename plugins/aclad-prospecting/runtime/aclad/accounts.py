"""Account identity, portfolio eligibility and explicit campaign selection."""
from dataclasses import asdict
from uuid import uuid4
from .models import Event, ExternalRef, GateError, Payload, Record, now_utc, payload
from .store import Store
from .icp_analysis import dimension_value, revenue_match

def _normal(value: object) -> str:
    return str(value or '').strip().casefold()

def match_account(candidate: Payload, existing: list[Payload]) -> Payload:
    candidate = payload(candidate)
    for field in ('external_ref', 'tax_id', 'domain', 'legal_name', 'name', 'trade_name'):
        value = candidate.get(field)
        if not value:
            continue
        found = [r for r in existing if r.get(field) and
                 (r[field] == value if field == 'external_ref' else _normal(r[field]) == _normal(value))]
        if found:
            exact = len(found) == 1 and field in {'external_ref','tax_id','domain'}
            if field == 'domain' and (candidate.get('shared_domain') or any(r.get('shared_domain') for r in found)):
                exact = False
            return {'status':'exact' if exact else 'uncertain', 'matched_by':field,
                    'match':found[0] if len(found) == 1 else None, 'candidates':found}
    return {'status':'none','matched_by':None,'match':None,'candidates':[]}

def eligibility(account: Payload, seller_ref: ExternalRef, rules: Payload) -> Payload:
    account = payload(account)
    reasons = []
    status = 'eligible'
    if account.get('do_not_contact') or account.get('contact_blocked'):
        status, reasons = 'blocked', ['do_not_contact']
    elif account.get('crm_status') not in {'verified','confirmed'}:
        status, reasons = 'needs_review', ['crm_not_verified']
    elif account.get('open_opportunity'):
        status, reasons = 'needs_review', ['active_opportunity']
    elif account.get('owner_ref') and account['owner_ref'] != asdict(seller_ref):
        status, reasons = 'needs_review', ['other_owner']
    elif account.get('match_status') == 'uncertain':
        status, reasons = 'needs_review', ['uncertain_identity']
    elif account.get('recent_activity') and not account.get('nurturing'):
        status, reasons = 'needs_review', ['active_work']
    elif rules.get('excluded'):
        status, reasons = 'blocked', ['partner_exclusion']
    if status == 'eligible' and isinstance(rules.get('icp_snapshot'), dict):
        match = icp_match(account, rules['icp_snapshot'])
        if match != 'match':
            status, reasons = ('blocked', ['account_outside_icp']) if match == 'no_match' else ('needs_review', ['icp_eligibility_unknown'])
    return {'status':status,'reasons':reasons,'owner_changed':False,'account_ref':account.get('external_ref')}

def icp_match(account: Payload, snapshot: Payload) -> str:
    """Apply the same reviewed predicates at the final selection boundary."""
    def match(predicate: Payload) -> str:
        field, operator, expected = predicate['field'], predicate['operator'], predicate['value']
        try:
            observed = dimension_value(field, account.get(field))
        except GateError:
            return 'unknown'
        if field == 'annual_revenue':
            return revenue_match(observed, predicate)
        if observed is None:
            return 'unknown'
        if operator in {'gte', 'lte'}:
            if type(observed) is not int:
                return 'unknown'
            accepted = observed >= expected if operator == 'gte' else observed <= expected
        else:
            values = observed if isinstance(observed, list) else [observed]
            accepted = bool(set(values).intersection(expected))
            if operator == 'not_in':
                accepted = not accepted
        return 'match' if accepted else 'no_match'
    results = [match(predicate) for predicate in snapshot.get('criteria', [])]
    exclusions = [match(predicate) for predicate in snapshot.get('exclusions', [])]
    if 'no_match' in results or 'match' in exclusions:
        return 'no_match'
    if 'unknown' in results + exclusions:
        return 'unknown'
    return 'match'


def belongs(record: Record, campaign_id: str) -> bool:
    return record.data.get('campaign_id') == campaign_id or campaign_id in record.data.get('campaign_ids', [])

def invalidate_removed(store: Store, removed: set[str]) -> None:
    for proposal in store.list('proposal'):
        if removed.intersection(proposal.data.get('item_ids', [])) and proposal.data.get('status') in {'proposed','approved','pending'}:
            store.put('proposal', proposal.id, dict(proposal.data,status='invalidated'), proposal.revision)

def select_accounts(store: Store, campaign_id: str, account_ids: list[str]) -> list[Record]:
    if len(set(account_ids)) != len(account_ids):
        raise GateError('duplicate_selection')
    with store.transaction():
        campaign = store.get('campaign', campaign_id)
        if not campaign:
            raise GateError('campaign_required')
        records = []
        for id in account_ids:
            record = store.get('account', id)
            state = record.data.get('eligibility') if record else None
            if isinstance(state, dict):
                state = state.get('status')
            if not record or not belongs(record, campaign_id):
                raise GateError('selection_outside_campaign')
            if state != 'eligible':
                raise GateError('account_not_eligible')
            snapshot = campaign.data.get('icp_snapshot')
            if isinstance(snapshot, dict) and isinstance(snapshot.get('criteria'), list):
                match = icp_match(record.data, snapshot)
                if match != 'match':
                    raise GateError('account_outside_icp' if match == 'no_match' else 'icp_eligibility_unknown',
                                    'Review the observed account values against the approved campaign criteria.')
            records.append(record)
        removed = set()
        for current in store.list('account'):
            if belongs(current, campaign_id) and current.data.get('selected') and current.id not in account_ids:
                store.put('account', current.id, dict(current.data,selected=False), current.revision)
                removed.add(current.id)
        dependent = set()
        for contact in store.list('contact'):
            if contact.data.get('account_id') in removed:
                dependent.add(contact.id)
                if contact.data.get('selected'):
                    store.put('contact', contact.id, dict(contact.data, selected=False), contact.revision)
        removed.update(dependent)
        invalidate_removed(store, removed)
        selected = [store.put('account',r.id,dict(r.data,selected=True),r.revision) for r in records]
        store.record_event(Event(uuid4().hex, campaign_id, 'accounts_selected', now_utc(), {'item_ids':account_ids}))
    return selected
