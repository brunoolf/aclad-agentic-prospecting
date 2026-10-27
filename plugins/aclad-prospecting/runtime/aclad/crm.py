"""Reviewed CRM batches with independently reconciliable item intents."""
from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4
from .accounts import belongs
from .approvals import create_proposal, approve, prepare_action, proposal_digest, record_result
from .models import Capability, Event, ExternalRef, GateError, Payload, Record, ToolResult, canonical, now_utc, payload
from .store import Store


def _owner_known(store: Store, owner: ExternalRef) -> bool:
    target = asdict(owner)
    if not all(isinstance(v,str) and v.strip() for v in target.values()):
        return False
    for row in store.list('account'):
        if row.data.get('crm_status') in {'verified','confirmed'} and row.data.get('owner_ref') == target:
            return True
    for action in store.list('action'):
        if action.data.get('operation') == 'crm.read' and action.data.get('status') == 'succeeded' and action.data.get('connection_id') == owner.connection_id:
            result = action.data.get('result',{})
            if result.get('complete') is True and target in result.get('users',[]):
                return True
    return False


def propose_crm(store: Store, campaign_id: str, changes: list[Payload], owner_ref: ExternalRef):
    if not _owner_known(store,owner_ref):
        raise GateError('owner_unresolved')
    if not isinstance(changes,list) or not changes or not store.get('campaign',campaign_id):
        raise GateError('changes_required')
    normalized = []
    ids = []
    for raw in changes:
        change = payload(raw)
        entity = change.get('entity')
        kind = 'contact' if entity == 'contact' else 'account'
        row = store.get(kind,change.get('local_id',''))
        if entity not in {'account','contact','activity'} or not row or not belongs(row,campaign_id) or row.data.get('selected') is not True:
            raise GateError('selection_required')
        if not isinstance(change.get('before'),dict) or not isinstance(change.get('after'),dict):
            raise GateError('field_diff_required')
        if row.data.get('do_not_contact') or row.data.get('contact_blocked'):
            raise GateError('contact_blocked')
        external = change.get('external_ref')
        if external:
            try:
                ref = ExternalRef(**external)
            except TypeError:
                raise GateError('invalid_external_ref') from None
            if (ref.provider,ref.tenant_id,ref.connection_id) != (owner_ref.provider,owner_ref.tenant_id,owner_ref.connection_id):
                raise GateError('connection_mismatch')
            if row.data.get('crm_external_ref') and row.data['crm_external_ref'] != external:
                raise GateError('crm_identity_mismatch')
            if not change.get('external_revision'):
                raise GateError('external_revision_required')
        elif row.data.get('crm_external_ref') and entity != 'activity':
            raise GateError('existing_record_requires_update')
        if change['after'].get('owner_ref',asdict(owner_ref)) != asdict(owner_ref):
            raise GateError('owner_mismatch')
        change['change_id'] = sha256(canonical(change).encode()).hexdigest()
        if change['change_id'] in {c['change_id'] for c in normalized}:
            raise GateError('duplicate_change')
        normalized.append(change)
        if row.id not in ids:
            ids.append(row.id)
    return create_proposal(store,'crm.write',owner_ref.connection_id,ids,
        {'campaign_id':campaign_id,'changes':normalized,'owner_ref':asdict(owner_ref),'external_revision':'batch'})


def prepare_crm_item(store: Store, proposal_id: str, change_id: str,
                     capability: Capability, preflight: Payload, now: str):
    with store.transaction():
        parent = store.get('proposal',proposal_id)
        if not parent or parent.data.get('operation') != 'crm.write' or parent.data.get('status') != 'approved':
            raise GateError('approval_required')
        data = parent.data
        digest = proposal_digest(data['operation'],data['connection_id'],data['item_ids'],data['payload'])
        approval = data.get('approval',{})
        if digest != data.get('digest') or approval.get('digest') != digest or approval.get('revision') != data['revision']:
            raise GateError('approval_mismatch')
        change = next((v for v in data['payload']['changes'] if v['change_id'] == change_id),None)
        if not change:
            raise GateError('change_not_approved')
        children = dict(data.get('children',{}))
        child_id = children.get(change_id)
        if not child_id:
            content = {'campaign_id':data['payload']['campaign_id'],'owner_ref':data['payload']['owner_ref'],
                       'change':change,'parent_proposal_id':proposal_id,
                       'external_revision':change.get('external_revision','new')}
            content['operation_id'] = 'crm-effect-' + sha256(canonical({
                'connection_id': data['connection_id'], 'entity': change['entity'],
                'local_id': change['local_id'], 'external_ref': change.get('external_ref'),
                'activity': change['change_id'] if change['entity'] == 'activity' else None}).encode()).hexdigest()
            if change['entity'] == 'contact':
                contact = store.get('contact',change['local_id'])
                account_id = change.get('links',{}).get('account_id',contact.data.get('account_id'))
                account = store.get('account',account_id or '')
                if not account or account.data.get('crm_status') != 'confirmed' or not account.data.get('crm_external_ref'):
                    raise GateError('account_sync_required')
                content['account_external_ref'] = account.data['crm_external_ref']
            child = create_proposal(store,'crm.write',data['connection_id'],[change['local_id']],content)
            approve(store,child.id,child.revision,child.digest,approval['approved_by'],approval['approved_at'])
            child_id = child.id
            children[change_id] = child_id
            store.put('proposal',parent.id,dict(data,children=children),parent.revision)
        return prepare_action(store,child_id,capability,preflight,now)


def record_crm_item(store: Store, result: ToolResult) -> Record:
    with store.transaction():
        original = store.get('action',result.action_id)
        if not original or original.data.get('operation') != 'crm.write' or 'change' not in original.data.get('payload',{}):
            raise GateError('crm_action_required')
        content = original.data['payload']
        owner = content['owner_ref']
        for ref in result.external_refs:
            if (ref.provider,ref.tenant_id,ref.connection_id) != (owner['provider'],owner['tenant_id'],owner['connection_id']):
                raise GateError('connection_mismatch')
            if content['change'].get('external_ref') and asdict(ref) != content['change']['external_ref']:
                raise GateError('crm_identity_mismatch')
        action = record_result(store,result)
        if action.data['status'] == 'succeeded':
            change = content['change']
            kind = 'contact' if change['entity'] == 'contact' else 'account'
            row = store.get(kind,change['local_id'])
            if not row:
                raise GateError('local_record_missing')
            refs = action.data['external_refs']
            if len(refs) != 1:
                raise GateError('ambiguous_crm_result')
            if change['entity'] == 'activity':
                activities = list(row.data.get('crm_activity_refs',[]))
                if refs[0] not in activities:
                    activities.append(refs[0])
                updated = dict(row.data,crm_activity_refs=activities)
            else:
                if row.data.get('crm_external_ref') and row.data['crm_external_ref'] != refs[0]:
                    raise GateError('crm_identity_mismatch')
                updated = dict(row.data,crm_status='confirmed',crm_external_ref=refs[0],owner_ref=owner)
            if updated != row.data:
                store.put(kind,row.id,updated,row.revision)
        parent_id = content.get('parent_proposal_id')
        parent = store.get('proposal',parent_id) if parent_id else None
        if parent:
            outcomes = dict(parent.data.get('item_outcomes',{}))
            outcomes[content['change']['change_id']] = {'action_id':action.id,'status':action.data['status']}
            if outcomes != parent.data.get('item_outcomes'):
                store.put('proposal',parent.id,dict(parent.data,item_outcomes=outcomes),parent.revision)
        return action


def reconcile_crm(store: Store, action_id: str, observations: list[Payload]) -> Record:
    with store.transaction():
        return _reconcile_crm(store, action_id, observations)


def _reconcile_crm(store: Store, action_id: str, observations: list[Payload]) -> Record:
    action = store.get('action',action_id)
    if not action or action.data.get('operation') != 'crm.write':
        raise GateError('crm_action_required')
    if action.data.get('status') == 'succeeded':
        return action
    change = action.data.get('payload',{}).get('change')
    if not change:
        raise GateError('crm_action_required')
    observations = [payload(item) for item in observations]
    content = action.data['payload']
    matches = [o for o in observations if o.get('complete') is True and o.get('local_id') == change['local_id']]
    if len(matches) != 1:
        return action
    observed = matches[0]
    if not isinstance(observed.get('evidence'), str) or not observed['evidence']:
        return action
    correlated = observed.get('operation_id') == content.get('operation_id') and bool(content.get('operation_id'))
    if correlated and observed.get('definitive_no_effect') is True and observed.get('status') == 'not_applied':
        return record_crm_item(store, ToolResult(action_id, 'failed', [],
            {'reconciled': True, 'definitive_no_effect': True, 'observation': observed}))
    fields = observed.get('fields')
    if not isinstance(fields, dict) or any(key not in fields or fields[key] != value for key, value in change['after'].items()):
        return action
    if observed.get('owner_ref') != content['owner_ref'] or observed.get('links') != change.get('links', {}):
        return action
    if change.get('external_ref'):
        if (observed.get('external_ref') != change['external_ref']
                or not observed.get('external_revision')
                or observed['external_revision'] == change.get('external_revision')):
            return action
    elif not correlated:
        return action
    try:
        ref = ExternalRef(**observed['external_ref'])
    except (TypeError, KeyError):
        raise GateError('invalid_external_ref') from None
    return record_crm_item(store,ToolResult(action_id,'succeeded',[ref],{'reconciled':True,'observation':observed}))
