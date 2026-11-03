"""Ordered, resumable seller setup backed by current private-state evidence.

A completed answer is not a tested connection or a confirmed native schedule.
This module never invokes a provider and never treats web search as prospecting.
"""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import uuid4

from .models import Event, GateError, Payload, Record, canonical, now_utc
from .profiles import _current, _lookup
from .store import Store

BLOCKS = (
    ('workspace', 'Seu ambiente'), ('identity', 'Você e sua empresa'),
    ('connections', 'Suas conexões'), ('communication', 'Sua comunicação'),
    ('automation', 'Seu acompanhamento'), ('icps', 'Seus ICPs'),
    ('campaign', 'Sua primeira campanha'),
)
PROFILE_ID = 'guided-onboarding'
READ_OPERATIONS = {'crm.read', 'email.read', 'calendar.read', 'connection.identity'}


def start_setup(store: Store) -> Record:
    """Enable guided setup once without losing any prior configuration or review."""
    with store.transaction():
        existing = store.get('profile', PROFILE_ID)
        if existing:
            return existing
        record = store.put('profile', PROFILE_ID,
            {'version': 1, 'reviews': {}, 'answers': {}, 'started_at': now_utc()}, None)
        store.record_event(Event(uuid4().hex, record.id, 'setup.started', now_utc(), {'version': 1}))
        return record


def _filled(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(isinstance(v, str) and v.strip() for v in value)
    return value is not None


def _authenticated(row: Record) -> bool:
    cap = row.data.get('capability', {})
    return (cap.get('visibility') == 'visible' and cap.get('auth') == 'authenticated'
            and cap.get('permission') == 'allowed' and cap.get('verification') == 'verified'
            and _filled(row.data.get('account_identity')))


def _available(row: Record, rows: list[Record]) -> bool:
    """Authentication of one native account does not certify an untested write.

Visible sibling operations can be configured without executing sends, writes or
paid lookups. Explicit permission/auth failures always override sibling proof.
The action executor still checks the exact operation before performing it.
"""
    cap = row.data.get('capability', {})
    if (cap.get('visibility') != 'visible' or not _filled(row.data.get('account_identity'))
            or cap.get('permission') == 'denied' or cap.get('auth') == 'failed'
            or cap.get('verification') == 'failed'):
        return False
    return any(_authenticated(other)
        and other.data.get('capability', {}).get('connection_id') == cap.get('connection_id')
        and other.data.get('native_connection_id') == row.data.get('native_connection_id')
        and other.data.get('provider') == row.data.get('provider')
        and other.data.get('account_identity') == row.data.get('account_identity')
        for other in rows)


def connection_readiness(store: Store) -> Payload:
    rows = store.list('connection')
    by_operation = {}
    evidence, review_evidence = [], []
    for row in rows:
        cap = row.data.get('capability', {})
        operation = cap.get('operation')
        if not isinstance(operation, str):
            continue
        if _available(row, rows):
            by_operation.setdefault(operation, []).append(row)
        evidence.append({'provider': row.data.get('provider'),
            'native_connection_id': row.data.get('native_connection_id'),
            'account_identity': row.data.get('account_identity'), 'capability': cap})
        # A successful first operation adds positive proof without changing the
        # account or tools the seller reviewed. Preserve that review while still
        # reopening it for a denial, hidden tool, identity or generation change.
        review_evidence.append({'provider': row.data.get('provider'),
            'native_connection_id': row.data.get('native_connection_id'),
            'account_identity': row.data.get('account_identity'),
            'operation': operation, 'tool_name': cap.get('tool_name'),
            'connection_id': cap.get('connection_id'), 'cost': cap.get('cost'),
            'available': _available(row, rows),
            'negative_states': {key: cap.get(key) for key, negative in
                (('visibility', {'not_visible', 'unknown'}), ('auth', {'failed'}),
                 ('permission', {'denied'}), ('verification', {'failed'}))
                if cap.get(key) in negative}})
    selected_crm = _lookup(_current(store), 'crm_mapping.provider')
    crm = [row for row in by_operation.get('crm.read', []) if _authenticated(row)
        and (not _filled(selected_crm) or row.data.get('provider', '').strip().casefold()
             == selected_crm.strip().casefold())]
    evidence.append({'selected_crm_provider': selected_crm})
    review_evidence.append({'selected_crm_provider': selected_crm})
    prospecting = []
    for account in by_operation.get('accounts.search', []):
        connection = account.data['capability']['connection_id']
        if any(person.data['capability']['connection_id'] == connection
               for person in by_operation.get('people.search', [])):
            prospecting.append(account)
    communication = []
    for read in by_operation.get('email.read', []):
        if not _authenticated(read):
            continue
        connection = read.data['capability']['connection_id']
        if all(any(row.data['capability']['connection_id'] == connection
                   for row in by_operation.get(operation, []))
               for operation in ('email.create_draft', 'email.send')):
            communication.append(read)
    # A write-capable CRM must be the same account as one of the confirmed reads.
    write = any(w.data['capability']['connection_id'] == r.data['capability']['connection_id']
                for w in by_operation.get('crm.write', []) for r in crm)
    missing = [name for name, candidates in
               (('crm', crm), ('prospecting', prospecting), ('communication', communication)) if not candidates]
    return {'ready': not missing, 'missing': missing, 'crm_read_only': bool(crm) and not write,
            'crm_write_available': write,
            'operation_verification': 'Visible operations on an authenticated account; each action still needs its own permission and approval.',
            'providers': {name: sorted({row.data.get('provider', '') for row in items})
                for name, items in (('crm', crm), ('prospecting', prospecting), ('communication', communication))},
            'evidence': sorted(evidence, key=canonical),
            'review_evidence': sorted(review_evidence, key=canonical)}


def _automation(store: Store, profile: Payload) -> Payload:
    preference = profile.get('schedule_preferences', {})
    mode = preference.get('mode')
    missing = []
    if mode not in {'manual', 'scheduled', 'combined'}:
        missing.append('schedule_preferences.mode')
    if mode in {'scheduled', 'combined'}:
        from .scheduling import validate_schedule
        try:
            validate_schedule({'weekdays': preference.get('days'), 'times': preference.get('times'),
                'timezone': preference.get('timezone'), 'scope_ids': ['setup-validation'],
                'active': True, 'notification_policy': 'actionable_changes'})
        except GateError as error:
            for field in ('days', 'times', 'timezone'):
                if not preference.get(field):
                    missing.append('schedule_preferences.' + field)
            field = {'invalid_weekdays': 'days', 'invalid_schedule_times': 'times',
                     'timezone_unavailable': 'timezone', 'invalid_timezone': 'timezone'}.get(error.code)
            if field and 'schedule_preferences.' + field not in missing:
                missing.append('schedule_preferences.' + field)
            if not missing:
                missing.append('schedule_preferences.timezone')
    active = False
    guided = store.get('profile', PROFILE_ID)
    campaign_review = guided.data.get('reviews', {}).get('campaign', {}) if guided else {}
    required_campaigns = {row['id'] for row in campaign_review.get('evidence', [])}
    if mode in {'scheduled', 'combined'} and not missing and required_campaigns:
        from .scheduling import _target, validate_schedule
        for row in store.list('schedule'):
            data = row.data
            if (data.get('status') != 'active' or data.get('reconciliation_required')
                    or not _filled(data.get('native_id')) or not _filled(data.get('evidence'))
                    or not _filled(data.get('confirmed_at')) or not data.get('next_occurrences')
                    or _target(store, data.get('target')) is None):
                continue
            try:
                effective = validate_schedule(data.get('schedule', {}))
            except GateError:
                continue
            if (effective['active'] is True and required_campaigns.issubset(set(effective['scope_ids']))
                    and effective['weekdays'] == sorted(preference['days'])
                    and effective['times'] == sorted(preference['times'])
                    and effective['timezone'] == preference['timezone']):
                active = True
                break
    return {'mode': mode, 'configuration_ready': not missing, 'missing': missing,
            'active': active, 'activation_pending': mode in {'scheduled', 'combined'} and not active,
            'status': 'manual' if mode == 'manual' else 'active' if active else 'activation_pending',
            'preferences': preference}


def _requirements(store: Store) -> dict[str, Payload]:
    current = _current(store)
    guided = store.get('profile', PROFILE_ID)
    answers = guided.data.get('answers', {}) if guided else {}
    environment = store.get('profile', 'environment')
    env = environment.data if environment else {}
    workspace_ok = (store.workspace_root is not None and env.get('status') in {'ready', 'limited'}
        and not {'configure_durable_state', 'runtime_3_11_required'}.intersection(env.get('next_steps', [])))
    workspace = {'missing': [] if workspace_ok else ['workspace.access'],
        'evidence': {'workspace_path': str(store.workspace_root) if store.workspace_root else None,
                     'durable_runtime_verified': workspace_ok}}
    fields = ['language', 'partner.name', 'partner.website', 'seller.name',
              'seller.territory', 'seller.size_bands']
    missing = [field for field in fields if not _filled(_lookup(current, field))]
    website = _lookup(current, 'partner.website')
    if _filled(website):
        try:
            parsed = urlsplit(website)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
                raise ValueError()
        except (ValueError, TypeError):
            missing.append('partner.website')
    from .portfolio import portfolio_context
    portfolio = portfolio_context(store)
    if portfolio['status'] != 'reviewed':
        missing.append('partner.offerings')
    if answers.get('setup.prospecting_history') not in {'new', 'existing'}:
        missing.append('setup.prospecting_history')
    identity = {'missing': missing,
        'evidence': {'profile': {field: _lookup(current, field) for field in fields},
                     'portfolio_digest': portfolio['digest'],
                     'prospecting_history': answers.get('setup.prospecting_history')}}
    connections = connection_readiness(store)
    style = store.get('profile', 'writing-style')
    communication = {'missing': [] if _filled(_lookup(current, 'seller.writing_style'))
                     or style and style.data.get('status') == 'active' else ['seller.writing_style'],
        'evidence': {'writing_style': _lookup(current, 'seller.writing_style'),
                     'reviewed_patterns': style.data if style else None}}
    automation = _automation(store, current)
    icps = [row for row in store.list('icp') if row.data.get('status') == 'active'
        and _filled(row.data.get('name')) and row.data.get('approved_revision') is not None
        and str(row.data['approved_revision']) in row.data.get('approved_versions', {})]
    named = {row.id: row for row in icps}
    campaigns = [row for row in store.list('campaign')
        if _filled(row.data.get('objective')) and row.data.get('icp_id') in named
        and str(row.data.get('icp_revision')) in named[row.data['icp_id']].data.get('approved_versions', {})
        and isinstance(row.data.get('icp_snapshot'), dict)
        and row.data['icp_snapshot'].get('digest') == named[row.data['icp_id']].data[
            'approved_versions'][str(row.data['icp_revision'])].get('digest')]
    return {'workspace': workspace, 'identity': identity,
        'connections': {'missing': connections['missing'], 'evidence': connections['review_evidence'], 'detail': connections},
        'communication': communication,
        'automation': {'missing': automation['missing'], 'evidence': automation['preferences'], 'detail': automation},
        'icps': {'missing': [] if icps else ['icp.approved_named'],
                 'evidence': [{'id': row.id, 'name': row.data['name'],
                    'approved_revision': row.data['approved_revision']} for row in icps]},
        'campaign': {'missing': [] if campaigns else ['campaign.bound_icp'],
                    'evidence': [{'id': row.id, 'objective': row.data['objective'],
                        'icp_id': row.data['icp_id'], 'icp_revision': row.data['icp_revision']} for row in campaigns]}}


def _digest(value: Payload) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def setup_status(store: Store) -> Payload:
    """Compute progress from actual evidence; saved review flags alone grant nothing."""
    guided = store.get('profile', PROFILE_ID)
    requirements = _requirements(store)
    reviews = guided.data.get('reviews', {}) if guided else {}
    blocks, current = [], None
    for block_id, title in BLOCKS:
        requirement = requirements[block_id]
        review = reviews.get(block_id, {})
        evidence = requirement['evidence']
        if block_id == 'connections' and isinstance(review.get('evidence'), list):
            selected = {(item.get('native_connection_id'), item.get('operation'))
                        for item in review['evidence'] if 'operation' in item}
            evidence = [item for item in evidence if 'selected_crm_provider' in item
                        or (item.get('native_connection_id'), item.get('operation')) in selected]
        if block_id in {'icps', 'campaign'} and isinstance(review.get('evidence'), list):
            # The first reviewed set is durable; adding another approved profile
            # or campaign does not restart setup for every existing campaign.
            selected = {item['id'] for item in review['evidence']}
            evidence = [item for item in evidence if item['id'] in selected]
            if block_id == 'icps':
                # New approved versions do not revoke an older pinned version.
                for item in evidence:
                    prior = next(old for old in review['evidence'] if old['id'] == item['id'])
                    saved = store.get('icp', item['id'])
                    if str(prior['approved_revision']) in saved.data.get('approved_versions', {}):
                        item['approved_revision'] = prior['approved_revision']
        fingerprint = _digest(evidence)
        complete = not requirement['missing'] and review.get('evidence_digest') == fingerprint
        if not complete and current is None:
            current = block_id
        status = 'complete' if complete else 'blocked' if requirement['missing'] and block_id in {'workspace', 'connections'} else 'pending'
        blocks.append({'id': block_id, 'title': title, 'status': status,
            'missing': deepcopy(requirement['missing']), 'ready_to_review': not requirement['missing'],
            'reviewed': bool(complete), 'evidence_digest': fingerprint})
    automation = requirements['automation']['detail']
    if current is None and automation['activation_pending']:
        current = 'automation'
    return {'guided': guided is not None, 'version': 1, 'complete': current is None,
        'status': 'complete' if current is None else 'in_progress', 'current_block': current,
        'completed_blocks': sum(row['status'] == 'complete' for row in blocks),
        'total_blocks': len(BLOCKS), 'blocks': blocks,
        'connections': deepcopy(requirements['connections']['detail']),
        'automation': deepcopy(automation),
        'next_action': 'ready' if current is None else 'activate_schedule' if current == 'automation'
            and all(row['status'] == 'complete' for row in blocks) else 'complete_' + current,
        'workspace_path': str(store.workspace_root) if store.workspace_root else None}


def complete_block(store: Store, block_id: str, reviewed_by: str) -> Record:
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise GateError('setup_reviewer_required')
    if block_id not in dict(BLOCKS):
        raise GateError('unknown_setup_block')
    with store.transaction():
        record = store.get('profile', PROFILE_ID)
        if not record:
            raise GateError('setup_required')
        status = setup_status(store)
        block = next(row for row in status['blocks'] if row['id'] == block_id)
        if block['status'] == 'complete':
            return record
        if status['current_block'] != block_id:
            raise GateError('setup_block_out_of_order')
        if block['missing']:
            raise GateError('setup_block_incomplete', 'Conclua e confira este bloco antes de avançar: ' + ', '.join(block['missing']))
        data = deepcopy(record.data)
        data['reviews'][block_id] = {'reviewed_by': reviewed_by.strip(),
            'reviewed_at': now_utc(), 'evidence_digest': block['evidence_digest'],
            'evidence': deepcopy(_requirements(store)[block_id]['evidence'])}
        updated = store.put('profile', PROFILE_ID, data, record.revision)
        store.record_event(Event(uuid4().hex, updated.id, 'setup.block_reviewed', now_utc(), {'block_id': block_id}))
        return updated


def save_guided_answer(store: Store, field: str, value: object) -> Record:
    if field != 'setup.prospecting_history' or not isinstance(value, str) or value not in {'new', 'existing'}:
        raise GateError('invalid_setup_answer')
    with store.transaction():
        record = store.get('profile', PROFILE_ID)
        if not record:
            raise GateError('setup_required')
        data = deepcopy(record.data)
        data['answers'][field] = value
        result = store.put('profile', PROFILE_ID, data, record.revision)
        store.record_event(Event(uuid4().hex, result.id, 'setup.answer_saved', now_utc(), {'field': field}))
        return result


def require_operational_readiness(store: Store, operation: str) -> None:
    """Gate guided operational work while allowing the reads needed to configure."""
    if not store.get('profile', PROFILE_ID) or operation in READ_OPERATIONS:
        return
    if operation == 'crm.write' and not connection_readiness(store)['crm_write_available']:
        raise GateError('crm_write_unavailable', 'O CRM conectado permite consulta, mas não gravação. Habilite uma conexão com escrita antes desta operação.')
    status = setup_status(store)
    if not status['complete']:
        raise GateError('setup_incomplete', 'Conclua o bloco ' + str(status['current_block']) + ' antes de iniciar a operação.')


def next_guided_question(store: Store) -> Payload | None:
    status = setup_status(store)
    block_id = status['current_block']
    if block_id is None:
        return None
    block = next(row for row in status['blocks'] if row['id'] == block_id)
    missing = block['missing']
    current = _current(store)
    fields = [field for field in missing if '.' in field or field == 'language'][:3]
    question = {
        'workspace': 'Vamos escolher e conferir a pasta privada da sua prospecção antes de começar.',
        'identity': 'Vamos concluir quem você é e qual empresa representa antes de conectar suas ferramentas.',
        'connections': 'Vamos concluir suas conexões: CRM, ferramenta de prospecção e e-mail. Falta: ' + ', '.join(missing),
        'communication': 'Qual estilo prefere? Posso mostrar exemplos de tom, extensão e formalidade antes de você escolher.',
        'automation': 'Quer conferir respostas quando pedir, em dias e horários escolhidos, ou das duas formas? Mensagens continuam exigindo aprovação.',
        'icps': 'Vamos criar ou escolher seus perfis de cliente. Cada ICP terá nome, critérios e aprovação próprios.',
        'campaign': 'Vamos escolher o objetivo da primeira campanha e o ICP aprovado que ela vai usar.',
    }[block_id]
    options = []
    if fields and fields[0] == 'setup.prospecting_history':
        question = 'Você vai começar uma prospecção nova ou acompanhar abordagens que já enviou?'
        options = [{'label': 'Começar agora', 'value': 'new'}, {'label': 'Retomar histórico', 'value': 'existing'}]
    elif block_id == 'automation' and 'schedule_preferences.mode' in fields:
        options = [{'label': 'Quando eu pedir', 'value': 'manual'},
            {'label': 'Em dias e horários escolhidos', 'value': 'scheduled'}, {'label': 'Das duas formas', 'value': 'combined'}]
    elif block_id == 'communication':
        options = [{'label': 'Direto e cordial', 'value': 'direct'}, {'label': 'Consultivo', 'value': 'consultative'},
                   {'label': 'Formal e objetivo', 'value': 'formal'}]
    if not missing:
        fields = []
        question = ('A programação foi salva, mas falta confirmar a criação da rotina no aplicativo.'
                    if status['next_action'] == 'activate_schedule'
                    else 'Revise o resumo de ' + block['title'] + ' para concluirmos este bloco.')
    return {'block_id': block_id, 'block_title': block['title'], 'field': fields[0] if fields else None,
        'fields': fields, 'question': question, 'options': options, 'language': current.get('language', 'pt-BR'),
        'interaction': {'preferred': 'native_question', 'fallback': 'chat',
                        'allow_free_text': True, 'wait_for_answer': True},
        'progress': {'completed': status['completed_blocks'], 'total': status['total_blocks']},
        'missing': missing, 'next_action': status['next_action'], 'purpose': block['title']}


def refresh_setup_view(store: Store) -> None:
    """Write a private, rebuildable progress view without changing any state."""
    if store.workspace_root is None or not store.get('profile', PROFILE_ID):
        return
    from .workspace_files import atomic_write
    status = setup_status(store)
    labels = {'complete': 'Concluído', 'pending': 'Pendente', 'blocked': 'Bloqueado'}
    lines = ['# Configuração da prospecção', '',
        'Este resumo reflete o estado salvo nesta pasta; não concede permissões ou aprovações.', '',
        f'Blocos concluídos: {status["completed_blocks"]} de {status["total_blocks"]}.', '',
        '| Etapa | Situação |', '| --- | --- |']
    lines += [f'| {block["title"]} | {labels[block["status"]]} |' for block in status['blocks']]
    automation = status['automation']
    lines += ['', '## Acompanhamento', '',
        'Somente quando solicitado.' if automation['mode'] == 'manual' else
        'Rotina confirmada e ativa no aplicativo.' if automation['active'] else
        'Rotina ainda não confirmada como ativa. Preferências salvas não criam uma automação.']
    if status['connections']['crm_read_only']:
        lines += ['', 'CRM somente leitura: consultas disponíveis; gravações bloqueadas.']
    if status['complete']:
        lines += ['', 'Configuração concluída. As ações continuam exigindo suas respectivas aprovações.']
    else:
        title = dict(BLOCKS)[status['current_block']]
        lines += ['', 'Próxima etapa: ' + ('ativar e confirmar a rotina no aplicativo.'
            if status['next_action'] == 'activate_schedule' else title + '.')]
    atomic_write(store.workspace_root / 'contexto' / 'configuracao.md', '\n'.join(lines) + '\n')
