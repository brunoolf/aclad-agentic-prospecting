"""Evidence-based tool inventory. Native calls stay with the host, never Python."""
from __future__ import annotations
from dataclasses import asdict, replace
from hashlib import sha256
from uuid import uuid4
from .models import Capability, Event, ExternalRef, GateError, Payload, Record, ToolResult, canonical, now_utc, payload
from .store import Store

OPERATION_ALIASES = {
    'crm.find_accounts': 'crm.read', 'crm.find_contacts': 'crm.read',
    'crm.write_account': 'crm.write', 'crm.write_contact': 'crm.write',
    'accounts.enrich': 'companies.enrich', 'contacts.search': 'people.search',
    'contacts.reveal': 'people.reveal_email', 'email.draft': 'email.create_draft',
}


def canonical_operation(operation: str) -> str:
    return OPERATION_ALIASES.get(operation, operation)


PROVIDER_OPERATIONS = {
    'netsuite': ['crm.read', 'crm.write'],
    'hubspot': ['crm.read', 'crm.write'],
    'pipedrive': ['crm.read', 'crm.write'],
    'monday': ['crm.read', 'crm.write'],
    'apollo': ['accounts.search', 'companies.enrich', 'people.search', 'people.reveal_email'],
    'lusha': ['accounts.search', 'companies.enrich', 'people.search', 'people.reveal_email'],
    'zoominfo': ['accounts.search', 'companies.enrich', 'people.search', 'people.reveal_email'],
    'snov.io': ['companies.enrich', 'people.search', 'people.reveal_email'],
    'smtp': ['email.send'],
    'outlook': ['email.read', 'email.create_draft', 'email.send', 'calendar.read'],
    'gmail': ['email.read', 'email.create_draft', 'email.send'],
    'google-calendar': ['calendar.read'], 'outlook-calendar': ['calendar.read'],
}
READ_PROBES = {'crm.read', 'email.read', 'calendar.read', 'connection.identity'}


def _record_id(native_id: str, operation: str) -> str:
    return 'inventory-' + sha256(f'{native_id}\0{operation}'.encode()).hexdigest()[:24]


def _save(store: Store, record_id: str, data: Payload) -> None:
    previous = store.get('connection', record_id)
    store.put('connection', record_id, data, previous.revision if previous else None)


def discover(store: Store, visible_tools: list[Payload], visibility_complete: bool) -> list[Capability]:
    if not isinstance(visible_tools, list) or type(visibility_complete) is not bool:
        raise GateError('invalid_inventory')
    validated = [payload(tool) for tool in visible_tools]
    for tool in validated:
        if any(not isinstance(tool.get(key), str) or not tool[key].strip()
               for key in ('tool_name', 'operation', 'connection_id')):
            raise GateError('invalid_binding', 'Tool name, operation and connection reference are required.')
        tool['operation'] = canonical_operation(tool['operation'])
        if tool.get('cost', 'unknown') not in {'free', 'paid', 'unknown'}:
            raise GateError('invalid_binding')
        if (tool.get('account_identity') is not None
                and (not isinstance(tool['account_identity'], str) or not tool['account_identity'])):
            raise GateError('invalid_binding')
        if not isinstance(tool.get('provider', ''), str):
            raise GateError('invalid_binding')
        if 'supports_sent' in tool and type(tool['supports_sent']) is not bool:
            raise GateError('invalid_binding')
    result = []
    seen = set()
    with store.transaction():
        # A native account has one generation, shared by its read/write operations.
        # Persist it independently so partial inventories and later-added operations
        # cannot mint incompatible identities after a reconnect.
        generations = {}
        for native in {tool['connection_id'] for tool in validated}:
            group = [tool for tool in validated if tool['connection_id'] == native]
            identities = {(tool.get('account_identity'), tool.get('provider', '')) for tool in group}
            if len(identities) != 1:
                raise GateError('conflicting_connection_identity')
            identity, provider = next(iter(identities))
            if identity is not None and (not isinstance(identity, str) or not identity):
                raise GateError('invalid_binding')
            key = 'connection-generation-' + sha256(native.encode()).hexdigest()[:24]
            generation = store.get('profile', key)
            siblings = [row for row in store.list('connection') if row.data.get('native_connection_id') == native]
            previous = generation.data if generation else (siblings[0].data if siblings else {})
            previous_id = previous.get('connection_id', previous.get('capability', {}).get('connection_id', native))
            changed = bool(previous and (previous.get('account_identity') != identity or previous.get('provider', '') != provider))
            changed = changed or any(
                row.data.get('capability', {}).get('tool_name') != tool['tool_name']
                for tool in group for row in siblings
                if row.data.get('capability', {}).get('operation') == tool['operation'])
            logical = native + '@' + uuid4().hex[:12] if changed else previous_id
            generations[native] = logical
            store.put('profile', key, {'native_connection_id': native, 'connection_id': logical,
                'account_identity': identity, 'provider': provider}, generation.revision if generation else None)
        for tool in validated:
            native = tool['connection_id']
            operation = tool['operation']
            identity = tool.get('account_identity')
            if identity is not None and (not isinstance(identity, str) or not identity):
                raise GateError('invalid_binding')
            key = _record_id(native, operation)
            old = store.get('connection', key)
            prior = old.data if old else {}
            previous_cap = prior.get('capability', {})
            changed = bool(old and (previous_cap.get('connection_id') != generations[native] or
                                    prior.get('account_identity') != identity or
                                    prior.get('provider') != tool.get('provider') or
                                    previous_cap.get('tool_name') != tool['tool_name']))
            connection_id = generations[native]
            if changed:
                store.record_event(Event(str(uuid4()), key, 'connection.identity_changed', now_utc(),
                    {'old_connection_id': previous_cap.get('connection_id'),
                     'new_connection_id': connection_id}))
            reusable = bool(old and not changed and identity)
            cap = Capability(operation, tool['tool_name'], connection_id, 'visible',
                previous_cap.get('auth', 'unknown') if reusable else 'unknown',
                previous_cap.get('permission', 'unknown') if reusable else 'unknown',
                previous_cap.get('verification', 'declared') if reusable else 'declared',
                tool.get('cost', 'unknown'))
            data = {'capability': asdict(cap), 'native_connection_id': native,
                'account_identity': identity, 'provider': tool.get('provider', ''),
                'supports_sent': tool.get('supports_sent', False),
                'visibility_complete': visibility_complete, 'observed_at': now_utc()}
            _save(store, key, data)
            result.append(cap)
            seen.add((native, operation))
        profile = store.get('profile', 'current')
        suggestions = profile.data.get('tool_suggestions', []) if profile else []
        expected = {(record.data.get('native_connection_id'),
                     record.data.get('capability', {}).get('operation'))
                    for record in store.snapshot().records if record.kind == 'connection'}
        for provider in suggestions:
            expected.update((provider, operation) for operation in PROVIDER_OPERATIONS.get(provider, []))
        visible_operations = {(tool.get('provider'), tool['operation']) for tool in validated}
        for native, operation in sorted(expected):
            if not isinstance(native, str) or not isinstance(operation, str):
                continue
            if (native, operation) in seen or (native, operation) in visible_operations:
                continue
            old = store.get('connection', _record_id(native, operation))
            prior = old.data if old else {}
            previous_cap = prior.get('capability', {})
            cap = Capability(operation, previous_cap.get('tool_name', ''),
                previous_cap.get('connection_id', native), 'not_visible' if visibility_complete else 'unknown',
                'unknown', 'unknown', 'declared', previous_cap.get('cost', 'unknown'))
            _save(store, _record_id(native, operation), {**prior, 'capability': asdict(cap),
                'provider': prior.get('provider', native), 'native_connection_id': native,
                'visibility_complete': visibility_complete, 'observed_at': now_utc()})
            result.append(cap)
    return result


def prepare_probe(capability: Capability) -> Payload:
    """A read-only free probe intent, not a provider invocation."""
    if capability.visibility != 'visible' or canonical_operation(capability.operation) not in READ_PROBES:
        raise GateError('unsafe_probe', 'Use a visible, read-only identity or read operation.')
    if capability.cost != 'free':
        raise GateError('probe_requires_cost_approval', 'Paid or unknown-cost reads require the normal action gate.')
    return {'operation': capability.operation, 'tool_name': capability.tool_name,
            'connection_id': capability.connection_id, 'read_only': True, 'cost': 'free'}


def prepare_bound_probe(store: Store, capability: Capability) -> Payload:
    """Prepare a CLI probe using the current inventory, never caller cost claims."""
    bindings = [row.data.get('capability', {}) for row in store.list('connection')
                if row.data.get('capability', {}).get('connection_id') == capability.connection_id
                and row.data.get('capability', {}).get('operation') == capability.operation]
    if len(bindings) != 1 or bindings[0] != asdict(capability):
        raise GateError('capability_unverified', 'Use the exact current discovered binding before probing.')
    return prepare_probe(Capability(**bindings[0]))


def record_probe(store: Store, capability: Capability, response: Payload) -> Capability:
    mismatch = False
    with store.transaction():
        response = payload(response)
        records = [record for record in store.snapshot().records if record.kind == 'connection'
                   and record.data.get('capability', {}).get('connection_id') == capability.connection_id
                   and record.data.get('capability', {}).get('operation') == capability.operation]
        if len(records) != 1 or response.get('connection_id') != capability.connection_id:
            raise GateError('connection_mismatch', 'Probe does not match the active connection.')
        current = records[0]
        if current.data['capability']['tool_name'] != capability.tool_name:
            raise GateError('connection_mismatch')
        capability = Capability(**current.data['capability'])
        identity = current.data.get('account_identity')
        mismatch = 'account_identity' in response and response['account_identity'] != identity
        if mismatch:
            # A response about this current binding invalidates its old proof.
            # Raise only after commit, otherwise the error rolls back the reset.
            for sibling in store.list('connection'):
                if sibling.data.get('capability', {}).get('connection_id') != capability.connection_id:
                    continue
                reset = replace(Capability(**sibling.data['capability']),
                                auth='unknown', permission='unknown', verification='declared')
                _save(store, sibling.id, {**sibling.data, 'capability': asdict(reset),
                    'probe': {'status_code': response.get('status_code'),
                              'evidence': response.get('evidence'),
                              'account_identity': response.get('account_identity'),
                              'diagnostic': 'connection_mismatch', 'at': now_utc()}})
                store.record_event(Event(str(uuid4()), sibling.id, 'connection.probe_invalidated', now_utc(),
                    {'operation': reset.operation, 'diagnostic': 'connection_mismatch'}))
        else:
            status = response.get('status_code')
            if type(status) is not int:
                raise GateError('invalid_probe_result')
            updated = replace(capability, auth='unknown', permission='unknown', verification='declared')
            if status == 401:
                updated = replace(updated, auth='failed', verification='failed')
                # Authentication belongs to the connected account, unlike a
                # 403 permission denial which can be specific to one operation.
                # Never let a sibling retain proof for the revoked generation.
                for sibling in store.list('connection'):
                    if (sibling.id == current.id
                            or sibling.data.get('capability', {}).get('connection_id') != capability.connection_id
                            or any(sibling.data.get(key) != current.data.get(key)
                                   for key in ('native_connection_id', 'account_identity', 'provider'))):
                        continue
                    reset = replace(Capability(**sibling.data['capability']),
                                    auth='failed', permission='unknown', verification='failed')
                    _save(store, sibling.id, {**sibling.data, 'capability': asdict(reset),
                        'probe': {'status_code': status, 'evidence': response.get('evidence'),
                                  'account_identity': identity,
                                  'diagnostic': 'authentication_failed', 'at': now_utc()}})
                    store.record_event(Event(str(uuid4()), sibling.id, 'connection.probe_invalidated', now_utc(),
                        {'operation': reset.operation, 'diagnostic': 'authentication_failed'}))
            elif status == 403:
                updated = replace(updated, permission='denied', verification='failed')
            elif (200 <= status < 300 and isinstance(identity, str) and identity.strip()
                  and response.get('account_identity') == identity
                  and isinstance(response.get('evidence'), str) and response['evidence'].strip()):
                updated = replace(updated, auth='authenticated', permission='allowed', verification='verified')
            elif status >= 400:
                updated = replace(updated, verification='failed')
            _save(store, current.id, {**current.data, 'capability': asdict(updated),
                'probe': {'status_code': status, 'evidence': response.get('evidence'),
                          'account_identity': response.get('account_identity'), 'at': now_utc()}})
            store.record_event(Event(str(uuid4()), current.id, 'connection.probed', now_utc(),
                                     {'operation': updated.operation, 'verification': updated.verification}))
    if mismatch:
        raise GateError('connection_mismatch', 'Probe identity differs from the discovered account; verify access again.')
    return updated


def _step_id(provider: str) -> str:
    return 'connection-step-' + sha256(provider.casefold().strip().encode()).hexdigest()[:24]


def update_connection_step(store: Store, provider: str, status: str, next_step: str,
                           evidence: str = '') -> Record:
    """Persist a concrete pending task; only observed capabilities establish readiness."""
    if (not isinstance(provider, str) or not provider.strip()
            or status not in {'pending', 'research', 'installed', 'enabled', 'needs_install', 'needs_enable', 'needs_login',
                              'needs_probe', 'partially_verified', 'blocked'}
            or not isinstance(next_step, str) or not next_step.strip()
            or not isinstance(evidence, str)):
        raise GateError('invalid_connection_step')
    with store.transaction():
        old = store.get('profile', _step_id(provider))
        data = dict(old.data if old else {}, provider=provider.strip(), status=status,
                    next_step=next_step.strip(), evidence=evidence, updated_at=now_utc(), manual_step=True)
        if status in {'installed', 'enabled'}:
            if not evidence.strip():
                raise GateError('connection_installation_evidence_required')
            data['installed'] = True
            if status == 'enabled':
                data['enabled'] = True
        result = store.put('profile', _step_id(provider), data, old.revision if old else None)
        store.record_event(Event(str(uuid4()), result.id, 'connection.step_updated', now_utc(),
                                 {'provider': provider.strip(), 'status': status}))
        return result


def connection_checklist(store: Store, providers: list[str], catalog: list[Payload]) -> list[Payload]:
    """A durable desired-tool checklist, including suppliers not yet in the catalog."""
    if (not isinstance(providers, list)
            or any(not isinstance(p, str) or not p.strip() for p in providers)
            or not isinstance(catalog, list)):
        raise GateError('invalid_connection_checklist')
    catalog = [payload(row) for row in catalog]
    results = []
    with store.transaction():
        for provider in dict.fromkeys(p.strip().casefold() for p in providers):
            entry = next((row for row in catalog if row.get('provider', '').casefold() == provider), None)
            records = [row for row in store.list('connection') if row.data.get('provider', '').casefold() == provider]
            operations = [dict(row.data['capability'], account_identity=row.data.get('account_identity'),
                               supports_sent=row.data.get('supports_sent', False)) for row in records]
            signature = sha256(canonical({'operations': operations, 'catalog': entry}).encode()).hexdigest()
            old = store.get('profile', _step_id(provider))
            same = bool(old and old.data.get('inventory_signature', signature) == signature)
            visible = [op for op in operations if op['visibility'] == 'visible']
            verified = [op for op in visible if op['verification'] == 'verified'
                        and op['auth'] == 'authenticated' and op['permission'] == 'allowed'
                        and op['account_identity']]
            requested = entry.get('operations', []) if entry else []
            verified_groups = [{op['operation'] for op in verified if op['connection_id'] == connection_id}
                               for connection_id in sorted({op['connection_id'] for op in verified})]
            best_group = max(verified_groups, key=lambda group: len(set(requested) & group), default=set())
            pending_operations = sorted(set(requested) - best_group)
            complete = bool(requested and not pending_operations)
            if complete:
                status, step = 'ready', 'Capacidades verificadas; seguir as aprovações próprias de cada ação.'
            elif not entry:
                status, step = 'research', 'Confirmar o produto e pesquisar sua documentação oficial e o catálogo de conexões deste aplicativo.'
            elif entry.get('requires_product_confirmation'):
                status, step = 'research', 'Confirmar qual produto Cortex você usa e pesquisar a documentação oficial antes de atribuir capacidades.'
            elif not visible:
                status, step = 'needs_install', 'Abrir as conexões do aplicativo, localizar e habilitar o fornecedor; se estiver bloqueado, pedir ajuda ao administrador e redescobrir as ferramentas.'
            elif any(op['auth'] == 'failed' for op in visible):
                status, step = 'needs_login', 'Reconectar pelo login nativo do aplicativo e verificar novamente a identidade e a leitura permitida.'
            elif verified:
                labels = {'email.send': 'envio de e-mail', 'email.create_draft': 'criação de rascunhos',
                          'email.read': 'leitura de e-mail', 'calendar.read': 'consulta de calendário',
                          'crm.read': 'consulta ao CRM', 'crm.write': 'gravação no CRM'}
                missing = ', '.join(labels.get(op, op) for op in pending_operations)
                status, step = 'partially_verified', 'Verificar as operações pendentes e seus custos antes de continuar: ' + missing + '.'
            else:
                status, step = 'needs_probe', 'Confirmar conta e usuário conectados e testar uma leitura mínima gratuita; operações pagas exigem aprovação.'
            preserve_manual = bool(same and not complete and old.data.get('manual_step')
                                   and old.data.get('status') != 'ready')
            if preserve_manual:
                status, step = old.data['status'], old.data['next_step']
            data = {'provider': provider, 'known': entry is not None,
                    'support_level': entry.get('support_level', 'documentation_only') if entry else 'unknown',
                    'host_paths': entry.get('host_paths', {}) if entry else {},
                    'installation_kind': entry.get('installation_kind', 'unknown') if entry else 'unknown',
                    'installed': old.data.get('installed') if old else None,
                    'enabled': old.data.get('enabled') if old else None,
                    'tools_discovered': bool(visible), 'authenticated': bool(verified),
                    'identities': sorted({op['account_identity'] for op in visible if op['account_identity']}),
                    'operations': operations, 'requested_operations': requested,
                    'pending_operations': pending_operations, 'status': status, 'manual_step': preserve_manual,
                    'next_step': step, 'inventory_signature': signature,
                    'evidence': old.data.get('evidence', '') if same else '',
                    'requires_secrets_in_chat': False}
            for key in ('official_url', 'checked_at', 'documentation_status'):
                if entry and key in entry:
                    data[key] = entry[key]
            store.put('profile', _step_id(provider), data, old.revision if old else None)
            results.append(data)
    return results

def connection_guidance(capability: Capability, catalog: list[Payload]) -> Payload:
    rows = [row for row in catalog if capability.operation in row.get('operations', [])
            and (capability.connection_id == row.get('provider') or
                 capability.connection_id.startswith(str(row.get('provider', '')) + '-'))]
    guidance = {'operation': capability.operation, 'visibility': capability.visibility,
        'auth': capability.auth, 'permission': capability.permission, 'verification': capability.verification,
        'next_step': 'Use o login nativo da plataforma, habilite o conector nesta conversa e redescubra as ferramentas. '
                     'Se a organização bloquear a instalação, peça ao administrador para habilitá-la.',
        'requires_secrets_in_chat': False}
    verified_rows = [row for row in rows if isinstance(row.get('official_url'), str)
                     and row['official_url'].startswith('https://') and row.get('checked_at')]
    if verified_rows:
        guidance['official_url'] = verified_rows[0]['official_url']
        guidance['checked_at'] = verified_rows[0]['checked_at']
    return guidance


def _path(raw: Payload, path: object) -> object:
    if not isinstance(path, str):
        return None
    value = raw
    for part in path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def normalize_result(binding: Payload, raw: Payload, action_id: str) -> ToolResult:
    binding, raw = payload(binding), payload(raw)
    required = ('tool_name', 'operation', 'connection_id', 'provider', 'tenant_id')
    if any(not isinstance(binding.get(key), str) or not binding[key] for key in required):
        raise GateError('invalid_binding')
    if raw.get('connection_id') != binding['connection_id'] or raw.get('tenant_id') != binding['tenant_id']:
        raise GateError('connection_mismatch', 'Native result belongs to another or unverified identity.')
    mapping = binding.get('result', {})
    if not isinstance(mapping, dict) or set(mapping) - {'status', 'object_id', 'data'}:
        raise GateError('invalid_binding')
    status = _path(raw, mapping.get('status'))
    if status not in {'succeeded', 'failed', 'unknown'}:
        status = 'unknown'
    object_id = _path(raw, mapping.get('object_id'))
    refs = []
    if isinstance(object_id, str) and object_id:
        refs = [ExternalRef(binding['provider'], binding['tenant_id'], binding['connection_id'], object_id)]
    if status == 'succeeded' and not refs:
        status = 'unknown'
    data_map = mapping.get('data', {})
    if not isinstance(data_map, dict):
        raise GateError('invalid_binding')
    data = {key: _path(raw, path) for key, path in data_map.items()}
    return ToolResult(action_id, status, refs, payload(data))
