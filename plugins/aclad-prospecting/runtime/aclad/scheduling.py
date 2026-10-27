"""Timezone-aware review previews and explicit requests to native schedulers."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .models import Event, GateError, Payload, Record, now_utc, payload, utc
from .store import Store

DST_RULE = ('Horário repetido: primeira ocorrência. Horário inexistente: primeiro '
            'instante válido do mesmo dia. Colisões são executadas uma vez.')
FIELDS = {'weekdays', 'times', 'timezone', 'scope_ids', 'active', 'notification_policy'}


def _target(store: Store, value: object) -> Payload | None:
    if not isinstance(value, dict):
        return None
    allowed = {'mode', 'workspace_path', 'project_id', 'chat_id', 'setup_chat_id'}
    if set(value) - allowed or any(not isinstance(v, str) or not v.strip() for v in value.values()):
        return None
    if not value.get('project_id') or value.get('mode') not in {'project_job', 'dedicated_chat'}:
        return None
    root = store.workspace_root or store.state_dir
    path = value.get('workspace_path', '')
    if not Path(path).is_absolute() or Path(path).resolve() != root.resolve():
        return None
    if value['mode'] == 'dedicated_chat':
        if (not value.get('chat_id') or not value.get('setup_chat_id')
                or value['chat_id'] == value['setup_chat_id']):
            return None
    elif 'chat_id' in value:
        return None
    return {**value, 'workspace_path': str(root.resolve())}


def _mapping_matches(configuration: object, schedule: Payload, target: Payload) -> bool:
    if not isinstance(configuration, dict) or configuration.get('target') != target:
        return False
    try:
        return (validate_schedule(configuration.get('schedule', {})) == schedule
                and isinstance(configuration.get('parameters'), dict) and bool(configuration['parameters']))
    except GateError:
        return False


def validate_schedule(payload_value: Payload) -> Payload:
    clean = payload(payload_value)
    if set(clean) != FIELDS:
        raise GateError('invalid_schedule', 'Provide days, times, timezone, scope, active flag and notification policy.')
    days, times, scope = clean['weekdays'], clean['times'], clean['scope_ids']
    if (not isinstance(days, list) or not days or any(type(day) is not int or day not in range(1, 8) for day in days)
            or len(set(days)) != len(days)):
        raise GateError('invalid_weekdays')
    if (not isinstance(times, list) or not times or any(not isinstance(value, str) or
            not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value) for value in times)
            or len(set(times)) != len(times)):
        raise GateError('invalid_schedule_times')
    if (not isinstance(scope, list) or not scope or any(not isinstance(id, str) or not id for id in scope)
            or len(set(scope)) != len(scope)):
        raise GateError('invalid_schedule_scope')
    if type(clean['active']) is not bool or clean['notification_policy'] != 'actionable_changes':
        raise GateError('invalid_schedule_policy')
    try:
        if not isinstance(clean['timezone'], str):
            raise ValueError()
        ZoneInfo(clean['timezone'])
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise GateError('timezone_unavailable', 'Use an available IANA timezone; the timezone will not be substituted.') from exc
    return {**clean, 'weekdays': sorted(days), 'times': sorted(times), 'scope_ids': sorted(scope)}


def _first_valid(naive: datetime, tz: ZoneInfo) -> datetime | None:
    original_date = naive.date()
    while naive.date() == original_date:
        candidate = naive.replace(tzinfo=tz, fold=0)
        # zoneinfo accepts nonexistent local times, so prove validity by round trip.
        if candidate.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == naive:
            return candidate.astimezone(timezone.utc)
        naive += timedelta(minutes=1)
    return None


def next_runs(schedule: Payload, after: str, count: int) -> list[str]:
    clean = validate_schedule(schedule)
    instant = utc(after)
    if type(count) is not int or count < 1 or count > 1000:
        raise GateError('invalid_run_count')
    if not clean['active']:
        return []
    tz = ZoneInfo(clean['timezone'])
    day = instant.astimezone(tz).date()
    runs = set()
    for offset in range(count * 14 + 370):
        current = day + timedelta(days=offset)
        if current.isoweekday() not in clean['weekdays']:
            continue
        for clock in clean['times']:
            hour, minute = map(int, clock.split(':'))
            candidate = _first_valid(datetime.combine(current, time(hour, minute)), tz)
            if candidate is not None and candidate > instant:
                runs.add(candidate)
        if len(runs) >= count:
            return [item.isoformat().replace('+00:00', 'Z') for item in sorted(runs)[:count]]
    raise GateError('schedule_horizon_exceeded')


def schedule_request(store: Store, schedule: Payload, scheduler_capability: Payload) -> Payload:
    clean, capability = validate_schedule(schedule), payload(scheduler_capability)
    environment = store.get('profile', 'environment')
    if not environment or environment.data.get('status') == 'state_unavailable':
        return {'status': 'state_unavailable', 'can_schedule': False,
                'next_step': 'Configure armazenamento durável acessível ao executor; a consulta manual continua disponível.'}
    if environment.data.get('can_schedule') is not True:
        return {'status': 'scheduler_unavailable', 'can_schedule': False,
                'next_step': 'Verifique runtime, identidade, ferramentas e executor antes de agendar.'}
    if (capability.get('available') is not True or capability.get('verified') is not True
            or not isinstance(capability.get('tool_name'), str) or not capability['tool_name']):
        return {'status': 'scheduler_unavailable', 'can_schedule': False,
                'next_step': 'Descubra a ferramenta nativa de agendamento e valide suas permissões.'}
    target = _target(store, capability.get('target'))
    if target is None:
        return {'status': 'target_required', 'can_schedule': False,
                'next_step': 'Use o mesmo projeto e pasta, em um chat de acompanhamento separado ou tarefa do projeto. A conferência manual continua disponível.'}
    if (capability.get('mapping_verified') is not True
            or not _mapping_matches(capability.get('native_configuration'), clean, target)):
        return {'status': 'mapping_required', 'can_schedule': False,
                'next_step': 'Mapeie a programação revisada para os parâmetros realmente aceitos pelo scheduler nativo.'}
    if not isinstance(capability.get('executor_id'), str) or not capability['executor_id']:
        raise GateError('executor_identity_required')
    request_id = 'review-schedule'
    with store.transaction():
        old = store.get('schedule', request_id)
        if old and old.data.get('status') == 'awaiting_native_confirmation':
            raise GateError('schedule_reconciliation_required', 'Check native scheduler before repeating an uncertain request.')
        native_id = old.data.get('native_id') if old else None
        legacy_target = bool(native_id and _target(store, old.data.get('target')) is None)
        if native_id and (old.data.get('tool_name') != capability['tool_name'] or
                          old.data.get('executor_id') != capability['executor_id'] or
                          not legacy_target and old.data.get('target') != target):
            raise GateError('scheduler_identity_changed', 'Reconcile the existing task before changing its executor.')
        instructions = ('Execute a skill replies em origem scheduled, apenas campanhas selecionadas abaixo. '
            'Adquira o lease antes do bootstrap; recupere estado e reconcilie efeitos incertos. '
            'Leia somente contas e conversas acompanhadas e registre páginas/cursores transacionalmente. '
            'Não envie mensagens, não grave CRM nem enriqueça dados pagos. '
            'Prepare sugestões para revisão. Sem alteração acionável, fique em silêncio. '
            'Notifique mudança relevante, falha ou ação necessária. '
            f'Instância: {asdict(store.scope)}. Diretório privado: {str(store.state_dir)}. '
            f'Campanhas: {clean["scope_ids"]}.')
        operation = ('pause' if native_id and not clean['active'] else 'reconcile' if legacy_target
                     else 'update' if native_id else 'create')
        result = {'status': 'target_reconciliation_required' if operation == 'reconcile' else 'request_prepared',
            'request_id': request_id, 'operation': operation,
            'name': 'Acompanhamento de prospecção', 'instructions': instructions,
            'native_configuration': capability['native_configuration'], 'tool_name': capability['tool_name'],
            'dependencies': {'state_dir': str(store.state_dir), 'scope': asdict(store.scope),
                             'executor_id': capability['executor_id'], 'target': target},
            'schedule': clean, 'dst_rule': DST_RULE, 'approval_required': True}
        if native_id:
            result['native_id'] = native_id
        record_data = {**(old.data if old else {}), 'schedule': clean, 'status': 'awaiting_native_confirmation',
            'tool_name': capability['tool_name'], 'executor_id': capability['executor_id'],
            'target': target, 'native_configuration': capability['native_configuration'],
            'operation': operation, 'created_at': now_utc()}
        if native_id:
            record_data['native_id'] = native_id
        if legacy_target:
            record_data['reconciliation_required'] = True
            record_data['reconciliation_source'] = old.data
            result['can_schedule'] = False
            result['next_step'] = ('Consultar a rotina pelo ID existente e conferir/mover o destino; '
                                   'registrar evidência nativa. Nunca criar outra rotina.')
        store.put('schedule', request_id, record_data, old.revision if old else None)
        store.record_event(Event('schedule-request-' + now_utc(), request_id, 'schedule.request_prepared', now_utc(),
                                 {'operation': operation}))
        return result


def record_schedule_result(store: Store, request_id: str, response: Payload) -> Record:
    """Host records real confirmation; uncertain creation may never be blindly retried."""
    clean = payload(response)
    with store.transaction():
        old = store.get('schedule', request_id)
        if not old or old.data.get('status') != 'awaiting_native_confirmation':
            raise GateError('schedule_request_required')
        data = dict(old.data)
        if (clean.get('status') == 'succeeded' and isinstance(clean.get('native_id'), str)
                and clean['native_id'] and isinstance(clean.get('evidence'), str) and clean['evidence']):
            if data.get('native_id') and data['native_id'] != clean['native_id']:
                raise GateError('scheduler_identity_changed')
            # Retain the real native ID even when the mapping needs reconciliation:
            # an uncertain task must never be recreated under another ID.
            data.update(native_id=clean['native_id'], evidence=clean['evidence'])
            try:
                matches = (validate_schedule(clean.get('effective_schedule', {})) == data['schedule']
                    and _target(store, clean.get('target')) == data.get('target')
                    and data.get('target') is not None
                    and isinstance(clean.get('confirmed_at'), str)
                    and clean.get('next_occurrences') == next_runs(data['schedule'], clean['confirmed_at'], 3))
            except (GateError, ValueError, TypeError):
                matches = False
            if matches:
                data.update(status='active' if data['schedule']['active'] else 'paused',
                            confirmed_at=clean['confirmed_at'], next_occurrences=clean['next_occurrences'])
                data.pop('reconciliation_required', None)
            else:
                data['reconciliation_required'] = True
        elif clean.get('status') == 'failed' and clean.get('definitive_no_effect') is True:
            data['status'] = 'failed'
        else:
            data['reconciliation_required'] = True
        result = store.put('schedule', old.id, data, old.revision)
        store.record_event(Event('schedule-result-' + now_utc(), old.id, 'schedule.result_recorded', now_utc(),
                                 {'status': data['status']}))
        return result
