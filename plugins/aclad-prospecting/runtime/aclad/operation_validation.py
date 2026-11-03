"""Explicit first-use validation; an authenticated sibling never silently grants permission."""
from dataclasses import asdict, replace
from .models import Capability, Event, GateError, Payload, now_utc
from .store import Store


def validation_context(store: Store, capability: Capability) -> Payload | None:
    if not store.get('profile', 'guided-onboarding') or capability.verification == 'verified':
        return None
    from .setup_flow import _available
    rows = store.list('connection')
    matching = [row for row in rows if row.data.get('capability') == asdict(capability)]
    if len(matching) != 1 or not _available(matching[0], rows):
        return None
    row = matching[0]
    return {'operation': capability.operation, 'tool_name': capability.tool_name,
            'connection_id': capability.connection_id, 'account_identity': row.data['account_identity'],
            'cost': capability.cost, 'requires_explicit_approval': True}


def validate_attempt(store: Store, capability: Capability, content: Payload, count: int) -> bool:
    expected = validation_context(store, capability)
    if expected is None or content.get('operation_validation') != expected:
        return False
    if capability.operation in {'accounts.search', 'people.search'}:
        limit = content.get('limits', {}).get('max_items')
        if type(limit) is not int or not 1 <= limit <= 10000 or limit < max(1, count):
            raise GateError('validation_limit_required', 'Revise uma quantidade máxima para esta primeira consulta.')
    return True


def confirm_operation(store: Store, action, status: str) -> None:
    proof = action.data.get('payload', {}).get('operation_validation')
    if status != 'succeeded' or not isinstance(proof, dict):
        return
    for row in store.list('connection'):
        cap = row.data.get('capability', {})
        if (cap.get('connection_id') != proof.get('connection_id')
                or cap.get('operation') != proof.get('operation')
                or cap.get('tool_name') != proof.get('tool_name')
                or row.data.get('account_identity') != proof.get('account_identity')):
            continue
        candidate = Capability(**cap)
        if validation_context(store, candidate) != proof:
            continue
        updated = replace(candidate, auth='authenticated', permission='allowed', verification='verified')
        store.put('connection', row.id, dict(row.data, capability=asdict(updated),
            operation_evidence={'action_id': action.id, 'verified_at': now_utc()}), row.revision)
        store.record_event(Event('operation-verified-' + action.id, row.id,
            'connection.operation_verified', now_utc(), {'action_id': action.id, 'operation': candidate.operation}))


def validate_campaign_operation(store: Store, proposal) -> None:
    """The generic bridge cannot bypass the guided campaign's fixed target."""
    if not store.get('profile', 'guided-onboarding') or proposal.operation in {'crm.read','email.read','calendar.read'}:
        return
    content = proposal.payload
    campaign = store.get('campaign', content.get('campaign_id', ''))
    if campaign is None:
        raise GateError('campaign_required')
    snapshot = campaign.data.get('icp_snapshot')
    if not isinstance(snapshot, dict) or not snapshot.get('digest'):
        raise GateError('icp_required')
    if proposal.operation == 'accounts.search':
        filters = {key: snapshot.get(key, []) for key in ('criteria', 'exclusions', 'partner_exclusions')}
        if (content.get('icp_id') != campaign.data.get('icp_id')
                or content.get('icp_revision') != campaign.data.get('icp_revision')
                or content.get('filters') != filters):
            raise GateError('campaign_target_mismatch', 'Use os critérios e a versão de ICP vinculados à campanha.')
        maximum = content.get('limits', {}).get('max_items')
        if type(maximum) is not int or not 1 <= maximum <= 10000:
            raise GateError('validation_limit_required' if content.get('operation_validation') else 'search_limit_required')
    elif proposal.operation == 'people.search':
        roles=[]
        for identifier in proposal.item_ids:
            row=store.get('roles', campaign.id + ':' + identifier)
            if row is None or row.data.get('status') != 'confirmed':
                raise GateError('roles_required')
            roles.extend(row.data.get('roles', []))
        if content.get('roles') != roles:
            raise GateError('roles_changed')
    elif proposal.operation in {'email.create_draft', 'email.send'}:
        from .messages import _check_context
        _check_context(store, campaign.id, content.get('message', {}), proposal.operation,
                       content.get('message_id'))
