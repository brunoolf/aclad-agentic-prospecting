"""Selection precedes paid enrichment. Search and reveal remain separate."""
from dataclasses import asdict
from uuid import uuid4
from .accounts import belongs, eligibility, invalidate_removed
from .icp_analysis import DIMENSIONS, dimension_value
from .approvals import create_proposal
from .models import Capability, Event, ExternalRef, GateError, Payload, Proposal, Record, now_utc, payload
from .policy import validate_cost
from .store import Store
from .portfolio import portfolio_context, validate_campaign_portfolio


def open_campaign(store: Store, campaign_id: str, objective: str) -> Record:
    if not isinstance(objective,str) or not objective.strip():
        raise GateError('objective_required')
    with store.transaction():
        existing = store.get('campaign',campaign_id)
        if existing:
            if existing.data.get('objective') != objective:
                raise GateError('campaign_conflict')
            return existing
        context = portfolio_context(store)
        data = {'objective': objective, 'status': 'draft'}
        if context['configured']:
            data.update(portfolio_policy_version=1, portfolio_snapshot=context)
        row = store.put('campaign', campaign_id, data, None)
        store.record_event(Event(uuid4().hex,campaign_id,'campaign_created',now_utc(),{}))
        return row


def _observed_dimensions(observation: Payload) -> Payload:
    """Preserve supported source facts; malformed dimensions stay explicitly unknown."""
    result = {}
    for field in DIMENSIONS:
        if field not in observation:
            continue
        try:
            result[field] = dimension_value(field, observation[field])
        except GateError:
            result[field] = None
    return result


def record_candidates(store: Store, campaign_id: str, kind: str, candidates: list[Payload], evidence_id: str) -> list[Record]:
    if kind not in {'account','contact'} or not isinstance(candidates,list):
        raise GateError('invalid_candidates')
    with store.transaction():
        evidence = store.get('action',evidence_id)
        if (not evidence or evidence.data.get('status') != 'succeeded'
                or evidence.data.get('operation') not in {'accounts.search','people.search','crm.read'}
                or not store.get('campaign',campaign_id)):
            raise GateError('candidate_evidence_required')
        actual = evidence.data.get('result',{}).get('candidates',[])
        rows = []
        ids = set()
        for raw in candidates:
            candidate = payload(raw)
            if candidate not in actual:
                raise GateError('candidate_evidence_mismatch')
            id = candidate.get('id')
            ref = candidate.get('external_ref')
            if not isinstance(id,str) or not id or id in ids or not isinstance(ref,dict) or not candidate.get('source_at'):
                raise GateError('invalid_candidate')
            ids.add(id)
            try:
                external = ExternalRef(**ref)
            except TypeError:
                raise GateError('invalid_candidate') from None
            if external.connection_id != evidence.data.get('connection_id'):
                raise GateError('connection_mismatch')
            old = store.get(kind,id)
            if old and not belongs(old,campaign_id):
                raise GateError('candidate_in_other_campaign')
            if old and old.data.get('external_ref') not in (None, ref):
                raise GateError('candidate_identity_conflict')
            if old and kind == 'contact' and old.data.get('account_id') != candidate.get('account_id'):
                raise GateError('candidate_identity_conflict')
            if kind == 'contact':
                account = store.get('account',candidate.get('account_id',''))
                if not account or not belongs(account,campaign_id) or account.data.get('selected') is not True:
                    raise GateError('selection_required')
            allowed = {'name', 'legal_name', 'trade_name', 'domain', 'tax_id', 'industry',
                'employees', 'size', 'country', 'state', 'city', 'annual_revenue', 'revenue',
                'title', 'seniority', 'department', 'account_id', 'external_ref', 'source_at'} | set(DIMENSIONS)
            observed = {key: value for key, value in candidate.items() if key in allowed}
            data = dict(old.data) if old else {}
            # Search observations cannot overwrite enriched fields or business state.
            protected = set(data.get('provenance', {}))
            normalized = dict(observed, **_observed_dimensions(observed)) if kind == 'account' else observed
            data.update({key: value for key, value in normalized.items() if key not in protected})
            if not old and candidate.get('email'):
                data['email'] = candidate['email']  # incidental provider data, never a hidden reveal
            data.update(campaign_id=campaign_id, selected=bool(old and old.data.get('selected')),
                evidence_id=evidence_id, candidate_observation={'fields': observed, 'evidence_id': evidence_id})
            if kind == 'account':
                data['eligibility'] = old.data.get('eligibility','needs_review') if old else 'needs_review'
            rows.append(store.put(kind,id,data,old.revision if old else None))
        store.record_event(Event(uuid4().hex,campaign_id,'candidates_recorded',now_utc(),{'kind':kind,'evidence_id':evidence_id,'count':len(rows),'item_ids':[row.id for row in rows]}))
        return rows


def check_account(store: Store, campaign_id: str, account_id: str, observation: Payload,
                  evidence_id: str, seller_ref: ExternalRef, rules: Payload) -> Record:
    with store.transaction():
        account = store.get('account',account_id)
        evidence = store.get('action',evidence_id)
        if not account or not belongs(account,campaign_id):
            raise GateError('account_not_found')
        if (not evidence or evidence.data.get('operation') != 'crm.read'
            or evidence.data.get('status') != 'succeeded'
            or evidence.data.get('connection_id') != seller_ref.connection_id
            or evidence.data.get('result',{}).get('complete') is not True
            or observation not in evidence.data.get('result',{}).get('observations',[])
            or observation.get('account_id') != account_id):
            raise GateError('crm_evidence_required')
        allowed = {'owner_ref','open_opportunity','do_not_contact','contact_blocked',
                   'recent_activity','nurturing','match_status','crm_external_ref','last_activity'}
        data = dict(account.data, **{k:v for k,v in observation.items() if k in allowed},crm_status='confirmed' if account.data.get('crm_status') == 'confirmed' else 'verified')
        data.update(_observed_dimensions(observation))
        campaign = store.get('campaign', campaign_id)
        checked_rules = dict(rules)
        if campaign and isinstance(campaign.data.get('icp_snapshot'), dict):
            checked_rules['icp_snapshot'] = campaign.data['icp_snapshot']
        data['eligibility'] = eligibility(data, seller_ref, checked_rules)['status']
        data['crm_check_evidence_id'] = evidence_id
        row = store.put('account',account_id,data,account.revision)
        store.record_event(Event(uuid4().hex,account_id,'crm_eligibility_checked',now_utc(),{'status':data['eligibility'],'evidence_id':evidence_id}))
        return row


def confirm_roles(store: Store, campaign_id: str, account_id: str, roles: list[Payload]) -> Record:
    if not isinstance(roles,list) or not roles:
        raise GateError('roles_required')
    roles = [payload(role) for role in roles]
    if any(not isinstance(role.get('title'),str) or not role['title'].strip() or
           type(role.get('max_contacts',1)) is not int or role.get('max_contacts',1)<1 for role in roles):
        raise GateError('invalid_roles')
    with store.transaction():
        account = store.get('account',account_id)
        if not account or not belongs(account,campaign_id) or account.data.get('selected') is not True:
            raise GateError('selection_required')
        id = campaign_id + ':' + account_id
        previous = store.get('roles',id)
        row = store.put('roles',id,{'campaign_id':campaign_id,'account_id':account_id,'roles':roles,'status':'confirmed'},previous.revision if previous else None)
        store.record_event(Event(uuid4().hex,id,'roles_confirmed',now_utc(),{'revision':row.revision}))
        return row


def select_contacts(store: Store, campaign_id: str, contact_ids: list[str]) -> list[Record]:
    if len(contact_ids) != len(set(contact_ids)):
        raise GateError('duplicate_selection')
    with store.transaction():
        rows = []
        for id in contact_ids:
            contact = store.get('contact',id)
            account = store.get('account',contact.data.get('account_id','')) if contact else None
            if not contact or not belongs(contact,campaign_id) or not account or not belongs(account,campaign_id) or account.data.get('selected') is not True:
                raise GateError('selection_required')
            rows.append(contact)
        removed = set()
        for old in store.list('contact'):
            if belongs(old,campaign_id) and old.data.get('selected') and old.id not in contact_ids:
                store.put('contact',old.id,dict(old.data,selected=False),old.revision)
                removed.add(old.id)
        invalidate_removed(store,removed)
        result = [store.put('contact',row.id,dict(row.data,selected=True),row.revision) for row in rows]
        store.record_event(Event(uuid4().hex,campaign_id,'contacts_selected',now_utc(),{'item_ids':contact_ids}))
        return result


def prepare_prospecting(store: Store, campaign_id: str, operation: str, item_ids: list[str],
                        capability: Capability, limits: Payload) -> Proposal:
    if operation not in {'accounts.search','companies.enrich','people.search','people.reveal_email'}:
        raise GateError('unsupported_operation')
    if operation != capability.operation:
        raise GateError('search_reveal_coupled' if operation == 'people.search' else 'operation_mismatch')
    limits = payload(limits)
    validate_cost(capability,{'limits':limits},len(item_ids))
    with store.transaction():
        campaign = store.get('campaign',campaign_id)
        if not campaign:
            raise GateError('campaign_required')
        context = validate_campaign_portfolio(store, campaign_id)
        content = {'campaign_id':campaign_id,'limits':limits}
        if context['configured']:
            content['portfolio'] = context
        if operation == 'accounts.search':
            if not campaign.data.get('icp_id') or not campaign.data.get('icp_revision'):
                raise GateError('icp_required')
            content.update(icp_id=campaign.data['icp_id'],icp_revision=campaign.data['icp_revision'])
            snapshot = campaign.data.get('icp_snapshot')
            if isinstance(snapshot, dict) and isinstance(snapshot.get('criteria'), list):
                content['filters'] = {key: snapshot.get(key, []) for key in ('criteria', 'exclusions', 'partner_exclusions')}
        else:
            for id in item_ids:
                kind = 'contact' if operation == 'people.reveal_email' else 'account'
                row = store.get(kind,id)
                if not row or not belongs(row,campaign_id) or row.data.get('selected') is not True:
                    raise GateError('selection_required')
                if operation == 'people.reveal_email' and row.data.get('email'):
                    raise GateError('email_already_available')
                if operation == 'people.search':
                    roles = store.get('roles',campaign_id + ':' + id)
                    if not roles or roles.data.get('status') != 'confirmed':
                        raise GateError('roles_required')
                    content.setdefault('roles',[]).extend(roles.data['roles'])
        return create_proposal(store,operation,capability.connection_id,item_ids,content)


def apply_enrichment(store: Store, action_id: str, results: list[Payload]) -> list[Record]:
    """Apply only fields actually returned for the approved selected entities."""
    with store.transaction():
        action = store.get('action',action_id)
        if not action or action.data.get('status') != 'succeeded':
            raise GateError('enrichment_evidence_required')
        operation = action.data.get('operation')
        if operation not in {'companies.enrich','people.reveal_email'}:
            raise GateError('enrichment_evidence_required')
        kind = 'account' if operation == 'companies.enrich' else 'contact'
        content = action.data.get('payload',{})
        selected_ids = content.get('item_ids',action.data.get('item_ids',[]))
        actual = action.data.get('result',{}).get('items',[])
        campaign_id = content.get('campaign_id')
        allowed = {'name','domain','tax_id','country','state','industry','subindustry','employees','annual_revenue','solutions','facts'} if kind == 'account' else {'email','email_status'}
        rows = []
        for raw in results:
            item = payload(raw)
            if item not in actual or item.get('id') not in selected_ids:
                raise GateError('enrichment_evidence_mismatch')
            row = store.get(kind,item['id'])
            if not row or row.data.get('selected') is not True or not belongs(row,campaign_id):
                raise GateError('selection_required')
            fields = item.get('fields')
            provenance = item.get('provenance')
            if not isinstance(fields,dict) or not set(fields).issubset(allowed) or not isinstance(provenance,dict) or not all(provenance.get(k) for k in ('source','collected_at','basis')):
                raise GateError('provenance_required')
            from .models import utc
            utc(provenance['collected_at'])
            sources = dict(row.data.get('provenance',{}))
            for field in fields:
                sources[field] = dict(provenance,action_id=action_id)
            updated = store.put(kind,row.id,dict(row.data,**fields,provenance=sources),row.revision)
            store.record_event(Event(uuid4().hex,row.id,'enrichment_applied',now_utc(),{'action_id':action_id,'fields':list(fields)}))
            rows.append(updated)
        return rows
