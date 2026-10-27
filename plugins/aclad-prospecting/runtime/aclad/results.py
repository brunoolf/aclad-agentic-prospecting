"""Numeric-only report renderer. It receives no commercial records or strings."""
from decimal import Decimal, ROUND_HALF_UP
from .models import GateError
from .result_metrics import Rate, ResultMetrics

_COUNT_LABELS = (
    ('Contas buscadas', 'searched_accounts'),
    ('Contas selecionadas pelo vendedor', 'ever_selected_accounts'),
    ('Contas selecionadas atualmente', 'current_selected_accounts'),
    ('Contas contatadas', 'contacted_accounts'),
    ('E-mails enviados', 'sent_messages'),
    ('Respostas humanas recebidas', 'human_reply_messages'),
    ('Contas com resposta humana', 'replied_accounts'),
    ('Reuniões marcadas', 'booked_meetings'),
    ('Reuniões ativas', 'active_meetings'),
    ('Reuniões canceladas', 'cancelled_meetings'),
    ('Contas com reunião', 'meeting_accounts'),
    ('Ações pendentes', 'pending_actions'),
)
_RATE_LABELS = (('Seleção', 'selection'), ('Abordagem', 'approach'), ('Resposta', 'reply'),
                ('Agendamento', 'booking'), ('Resposta → reunião', 'reply_to_booking'))


def _percent(rate: Rate) -> str:
    if not rate.denominator:
        return 'N/D'
    number = (Decimal(rate.numerator) * 100 / Decimal(rate.denominator)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return f'{number:.2f}%'.replace('.', ',')


def render_results(metrics: ResultMetrics) -> str:
    if type(metrics) is not ResultMetrics:
        raise GateError('invalid_results_metrics')
    metrics.__post_init__()
    lines = ['# Resultados', '',
        'Projeção recalculada automaticamente a partir do estado confirmado. Edições deste arquivo não alteram o estado.',
        '', '| Indicador | Quantidade |', '|---|---:|']
    lines.extend(f'| {label} | {getattr(metrics, key)} |' for label, key in _COUNT_LABELS)
    lines += ['', '| Taxa | Numerador | Denominador | Percentual |', '|---|---:|---:|---:|']
    for label, key in _RATE_LABELS:
        rate = getattr(metrics, key)
        lines.append(f'| {label} | {rate.numerator} | {rate.denominator} | {_percent(rate)} |')
    lines += ['', 'N/D indica denominador zero.', '', '| Cobertura | Consultado | Total |', '|---|---:|---:|']
    for label, prefix in (('Conversas acompanhadas', 'reply_conversations'),
                          ('Contas no calendário', 'calendar_accounts'),
                          ('Fontes de contas', 'account_sources')):
        lines.append(f'| {label} | {getattr(metrics, prefix + "_checked")} | {getattr(metrics, prefix + "_total")} |')
    lines += ['', 'Cobertura incompleta ou não consultada não comprova ausência de respostas ou reuniões.', '']
    return '\n'.join(lines)


def refresh_results(store) -> None:
    """Serialize snapshot, atomic publication and private acknowledgement per DB.

    A failed replace never rolls back the business transaction already committed.
    Holding BEGIN IMMEDIATE through publication prevents an older writer winning.
    """
    if store.workspace_root is None:
        return
    from .workspace_files import atomic_write, check_path
    from .result_metrics import calculate_results
    from .context import refresh_private_context, refresh_learning_context
    path = store.workspace_root / 'contexto' / 'resultados.md'
    try:
        with store.transaction():
            content = render_results(calculate_results(store))
            check_path(path)
            if not path.is_file() or path.read_text(encoding='utf-8') != content:
                atomic_write(path, content)
            refresh_private_context(store)
            refresh_learning_context(store)
            generation = store.db.execute("SELECT value FROM metadata WHERE key='results_generation'").fetchone()
            store.db.execute("INSERT INTO metadata VALUES('results_published',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (generation[0] if generation else '0',))
    except (OSError, UnicodeError, GateError) as exc:
        if isinstance(exc, GateError) and exc.code not in {'workspace_path_unavailable', 'workspace_conflict'}:
            raise
        raise GateError('results_report_unavailable') from None


def ensure_results_current(store) -> None:
    if store.workspace_root is None:
        return
    if store._depth:
        # Do not publish uncommitted business state. Nested preparations still
        # must reject stale/missing reports before creating any new intent.
        from .result_metrics import calculate_results
        from .workspace_files import check_path
        path = store.workspace_root / 'contexto' / 'resultados.md'
        try:
            check_path(path)
            metadata = dict(store.db.execute("SELECT key,value FROM metadata WHERE key IN ('results_generation','results_published')"))
            if (metadata.get('results_generation', '0') != metadata.get('results_published', '0')
                    or path.read_text(encoding='utf-8') != render_results(calculate_results(store))):
                raise GateError('results_report_unavailable')
        except (OSError, UnicodeError):
            raise GateError('results_report_unavailable') from None
        return
    from .local_views import refresh_local_views
    refresh_local_views(store)


def results_report_status(store) -> dict:
    """Read-only diagnostic; a broken projection must not hide durable effects."""
    if store.workspace_root is None:
        return {'status': 'not_configured'}
    from .result_metrics import calculate_results
    from .workspace_files import check_path
    path = store.workspace_root / 'contexto' / 'resultados.md'
    try:
        check_path(path)
        metadata = dict(store.db.execute("SELECT key,value FROM metadata WHERE key IN ('results_generation','results_published')"))
        current = metadata.get('results_generation', '0') == metadata.get('results_published', '0')
        if current and path.read_text(encoding='utf-8') == render_results(calculate_results(store)):
            return {'status': 'current'}
    except (OSError, UnicodeError, GateError):
        pass
    return {'status': 'pending', 'code': 'results_report_unavailable'}
