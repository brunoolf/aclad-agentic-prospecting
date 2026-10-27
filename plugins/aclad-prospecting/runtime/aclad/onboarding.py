"""Resumable seller interview and conservative per-surface readiness."""
from __future__ import annotations
from copy import deepcopy
import re
from uuid import uuid4
from .models import Event, GateError, Payload, Record, now_utc, payload
from .profiles import _assign, _current, _lookup, save_profile, validate_profile
from .store import Store

# One question at a time. Host may translate other languages without changing field semantics.
QUESTIONS = [
 ('language', 'Em qual idioma vamos conversar e preparar os materiais?', '¿En qué idioma conversamos y preparamos los materiales?', 'Which language should we use for the conversation and materials?'),
 ('import_choice', 'Você recebeu um perfil da sua empresa para importar ou prefere começar do zero?', '¿Recibiste un perfil de tu empresa para importar o prefieres empezar de cero?', 'Did you receive a company profile to import, or should we start from scratch?'),
 ('partner.name', 'Qual é o nome da sua empresa e o site dela? Vou pesquisar o contexto público para sua revisão.', '¿Cuál es el nombre de tu empresa y su sitio web? Investigaré el contexto público para tu revisión.', 'What is your company name and website? I will research the public context for your review.'),
 ('partner.website', 'Qual é o site da sua empresa para começarmos a pesquisa?', '¿Cuál es el sitio web de tu empresa para comenzar la investigación?', 'What is your company website so we can start the research?'),
 ('partner.products', 'Quais produtos e serviços sua empresa vende?', '¿Qué productos y servicios vende tu empresa?', 'Which products and services does your company sell?'),
 ('partner.differentiators', 'Quais diferenciais e referências autorizadas ajudam a explicar a experiência do parceiro?', '¿Qué ventajas y referencias autorizadas explican la experiencia del socio?', 'Which differentiators and authorized references describe your experience?'),
 ('seller.name', 'Como você prefere ser chamado?', '¿Cómo prefieres que te llamemos?', 'What should I call you?'),
 ('seller.territory', 'Quais regiões e territórios você trabalha?', '¿Qué regiones y territorios trabajas?', 'Which territories do you cover?'),
 ('seller.size_bands', 'Quais portes de empresa você atende?', '¿Qué tamaños de empresa atiendes?', 'Which company sizes do you serve?'),
 ('crm_mapping.provider', 'Qual CRM você usa? Vamos aproveitar a conexão existente ou orientar o login.', '¿Qué CRM usas? Aprovecharemos la conexión existente o te guiaremos con el inicio de sesión.', 'Which CRM do you use? We will reuse the connection or guide native login.'),
 ('seller.crm_user_id', 'Qual usuário do CRM representa você? Vou resolver a identidade pela conexão antes de atribuir contas.', '¿Qué usuario del CRM te representa? Verificaremos la identidad antes de asignar cuentas.', 'Which CRM user represents you? We will resolve the identity before assigning accounts.'),
 ('crm_mapping.customer_field', 'Como o CRM identifica uma empresa cliente? Vou conferir o campo e o significado com você.', '¿Cómo identifica tu CRM a una empresa cliente? Revisaremos el campo y su significado.', 'How does the CRM identify a customer company? We will review the field and meaning.'),
 ('crm_mapping.owner_field', 'Qual campo identifica o responsável da conta no CRM?', '¿Qué campo identifica al responsable de la cuenta en el CRM?', 'Which CRM field identifies the account owner?'),
 ('tool_suggestions', 'Quais fontes de prospecção, e-mail e calendário você utiliza?', '¿Qué fuentes de prospección, correo y calendario utilizas?', 'Which prospecting, email and calendar tools do you use?'),
 ('seller.writing_style', 'Prefere um tom direto, consultivo ou formal? Posso mostrar exemplos ou, com sua aceitação, analisar até dez prospecções profissionais recentes dos seus enviados, excluindo mensagens internas e automáticas. Você revisa os padrões antes de ativar.', '¿Prefieres un tono directo, consultivo o formal? Puedo mostrar ejemplos o, si aceptas, analizar hasta diez prospecciones profesionales recientes de tus enviados, excluyendo mensajes internos y automáticos. Revisas los patrones antes de activarlos.', 'Would you prefer a direct, consultative, or formal tone? I can show examples or, with your consent, analyze up to ten recent professional prospecting messages you sent, excluding internal and automated mail. You review the patterns before activation.'),
 ('seller.selected_example_ids', 'Quer selecionar exemplos de escrita ou seguir sem exemplos?', '¿Quieres seleccionar ejemplos de escritura o continuar sin ejemplos?', 'Would you like to select writing examples or continue without examples?'),
 ('icp_choice', 'Quer analisar clientes do parceiro, seus clientes, suas contas em prospecção ou construir um novo ICP?', '¿Quieres analizar clientes del socio, tus clientes, tus cuentas en prospección o crear un ICP nuevo?', 'Would you like to analyze partner customers, your customers, your prospect accounts, or build a new ICP?'),
 ('schedule_preferences.mode', 'Você quer que eu confira as respostas quando você pedir, automaticamente nos dias e horários que escolher, ou as duas coisas? Nessas conferências, trago quem respondeu e o próximo passo sugerido; mensagens só serão enviadas depois da sua aprovação.', '¿Quieres que revise las respuestas cuando lo pidas, automáticamente los días y horarios que elijas, o ambas cosas? En esas revisiones mostraré quién respondió y el siguiente paso sugerido; los mensajes solo se enviarán después de tu aprobación.', 'Would you like me to check replies when you ask, automatically on the days and times you choose, or both? I will bring you who replied and a suggested next step; messages will only be sent after your approval.'),
 ('schedule_preferences.timezone', 'Qual é seu fuso horário? Isso evita follow-ups no horário errado.', '¿Cuál es tu zona horaria? Esto evita seguimientos a la hora incorrecta.', 'Which timezone should we use for follow-ups?'),
]


def next_question(store: Store) -> Payload | None:
    current = _current(store)
    progress = store.get('profile', 'onboarding')
    answered = progress.data.get('answers', {}) if progress else {}
    language = current.get('language', 'pt-BR')
    index = 2 if str(language).startswith('es') else 3 if str(language).startswith('en') else 1
    for row in QUESTIONS:
        field = row[0]
        if field in answered or _lookup(current, field) is not None:
            continue
        return {'field': field, 'fields': ['partner.name', 'partner.website'] if field == 'partner.name' else [field],
                'question': row[index], 'language': language,
                'purpose': {'language': 'Idioma da conversa e materiais',
                            'import_choice': 'Reaproveitar apenas o contexto revisado'}.get(field, field.split('.')[0])}
    return None


def save_answer(store: Store, field: str, value: object) -> Record:
    if not isinstance(field, str):
        raise GateError('invalid_setup_field')
    with store.transaction():
        current = _current(store)
        special = {'import_choice', 'icp_choice'}
        if field in special:
            if not isinstance(value, str) or not value.strip():
                raise GateError('invalid_setup_answer')
        else:
            # Profile validation rejects paths not in the recursively defined shape.
            _assign(current, field, value)
            validate_profile(current)
            if field == 'seller.selected_example_ids':
                available = {example['id'] for example in current.get('seller', {}).get('writing_examples', [])}
                if any(identifier not in available for identifier in value):
                    raise GateError('unselected_example', 'Select only writing examples supplied by you.')
            if field == 'schedule_preferences.mode' and value not in {'manual', 'scheduled', 'combined'}:
                raise GateError('invalid_schedule_mode')
            if field == 'schedule_preferences.timezone':
                from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
                try:
                    ZoneInfo(value)
                except (ValueError, ZoneInfoNotFoundError) as exc:
                    raise GateError('invalid_timezone') from exc
        with store.transaction():
            result = save_profile(store, current, 'setup.answer_saved')
            progress = store.get('profile', 'onboarding')
            data = deepcopy(progress.data) if progress else {'answers': {}}
            data['answers'][field] = deepcopy(value)
            store.put('profile', 'onboarding', data, progress.revision if progress else None)
            store.record_event(Event(str(uuid4()), result.id, 'setup.progress_saved', now_utc(), {'field': field}))
            from .recovery import checkpoint
            checkpoint(store)
        return result

def selected_writing_examples(store: Store) -> list[Payload]:
    seller = _current(store).get('seller', {})
    selected = seller.get('selected_example_ids', [])
    return [deepcopy(example) for example in seller.get('writing_examples', []) if example['id'] in selected]


def environment_readiness(store: Store, facts: Payload) -> Payload:
    facts = payload(facts)
    reasons = []
    version = facts.get('runtime_version', '')
    match = re.fullmatch(r'(\d+)\.(\d+)(?:\.\d+)?', version) if isinstance(version, str) else None
    runtime_ok = bool(match and tuple(map(int, match.groups())) >= (3, 11))
    is_cloud = str(facts.get('surface', '')).endswith('cloud')
    durable = facts.get('durable_state') is True and facts.get('state_accessible_to_executor') is True
    remote_fields = ('remote_conditional_updates', 'remote_concurrency', 'remote_durable_events',
                     'remote_recovery_verified', 'remote_access_control_verified')
    if is_cloud and not all(facts.get(field) is True for field in remote_fields):
        durable = False
    if not durable:
        reasons.append('configure_durable_state')
    if not runtime_ok:
        reasons.append('runtime_3_11_required')
    identity_ok = facts.get('identity_resolved') is True
    if not identity_ok:
        reasons.append('resolve_identity')
    tools_ok = facts.get('tools_verified') is True
    if not tools_ok:
        reasons.append('connect_tools')
    external = durable and runtime_ok and identity_ok and tools_ok
    result = {'status': 'ready' if external else 'limited' if durable else 'state_unavailable',
              'surface': facts.get('surface', 'unknown'), 'can_configure': True,
              'can_external_actions': external, 'can_paid_actions': external,
              'can_schedule': external and facts.get('scheduler_verified') is True,
              'approval_required': True, 'next_steps': reasons,
              'checked_at': now_utc()}
    previous = store.get('profile', 'environment')
    with store.transaction():
        store.put('profile', 'environment', result, previous.revision if previous else None)
        store.record_event(Event(str(uuid4()), 'environment', 'environment.checked', now_utc(),
                                 {'status': result['status'], 'surface': result['surface']}))
    return result
