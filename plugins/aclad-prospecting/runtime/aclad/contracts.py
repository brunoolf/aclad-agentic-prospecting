"""Read-only operator discovery derived from live routing, signatures and profile shapes.

Discovery never opens a Store, resolves a workspace or invokes a connector. Examples
are synthetic input illustrations, not observations, consent or executable approvals.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import MISSING, fields, is_dataclass
from importlib import import_module
from inspect import Parameter, signature
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from .commands import COMMANDS
from .models import GateError
from .profiles import PROFILE

DISCOVERY = {'help', 'schema', 'examples'}
# Entry points handled directly by __main__/dispatch rather than COMMANDS.
ENTRY_POINTS = {
    'workspace-init': ('workspace', 'initialize_workspace', {'root'}),
    'workspace-locate': ('workspace', 'locate_workspace', {'start'}),
    'workspace-migration-preview': ('workspace_migration', 'preview_migration', {'registry_dir', 'root'}),
    'workspace-migrate': ('workspace_migration', 'migrate_instance', {'registry_dir', 'root'}),
    'instance-init': ('instances', 'initialize_instance', {'registry_dir'}),
    'instance-list': ('instances', 'list_instances', {'registry_dir'}),
    'instance-locate': ('instances', 'locate_instance', {'registry_dir'}),
    'icp-analyze': ('icp_analysis', 'analyze_icps', set()),
}
SNAPSHOTS = {'status', 'resume', 'checkpoint'}


def command_names() -> list[str]:
    return sorted(set(COMMANDS) | set(ENTRY_POINTS) | SNAPSHOTS)


def _shape_schema(shape: object) -> dict:
    if isinstance(shape, dict):
        return {'type': 'object', 'properties': {key: _shape_schema(value) for key, value in shape.items()},
                'additionalProperties': False}
    if isinstance(shape, list):
        return {'type': 'array', 'items': _shape_schema(shape[0])}
    return {'type': shape}


def _annotation_schema(annotation: object) -> dict:
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        return {'anyOf': [_annotation_schema(item) for item in arguments]}
    if origin is list:
        return {'type': 'array', 'items': _annotation_schema(arguments[0]) if arguments else {}}
    if origin is dict or annotation is dict:
        return {'type': 'object'}
    if is_dataclass(annotation):
        hints = get_type_hints(annotation)
        properties, required = {}, []
        for field in fields(annotation):
            if not field.init:
                continue
            item = _annotation_schema(hints.get(field.name, object))
            if field.default is MISSING and field.default_factory is MISSING:
                required.append(field.name)
            elif field.default is not MISSING:
                item['default'] = deepcopy(field.default)
            # A factory can have effects; describing its type must never invoke it.
            properties[field.name] = item
        return {'type': 'object', 'properties': properties,
                'required': required, 'additionalProperties': False}
    primitive = {str: 'string', int: 'integer', float: 'number', bool: 'boolean', type(None): 'null'}
    return {'type': primitive[annotation]} if annotation in primitive else {}


def _profile_fields(shape: dict, prefix: str = '') -> dict:
    result = {}
    for key, value in shape.items():
        # Literal dotted import-package keys cannot be traversed by _assign.
        if '.' in key:
            continue
        path = f'{prefix}.{key}'.strip('.')
        result[path] = _shape_schema(value)
        if isinstance(value, dict):
            result.update(_profile_fields(value, path))
    return result


def command_schema(command: str) -> dict:
    if command == 'profile':
        return {'topic': 'profile', 'input_schema': _shape_schema(PROFILE),
                'note': 'Campos opcionais; sem credenciais, conexões autenticadas ou autorização herdada.'}
    if command in SNAPSHOTS:
        return {'command': command, 'input_schema': {'type': 'object', 'properties': {},
                                                    'additionalProperties': False}, 'workspace_required': True}
    if command in COMMANDS:
        module, name, with_store = COMMANDS[command]
        hidden = {'store'} if with_store else set()
    elif command in ENTRY_POINTS:
        module, name, hidden = ENTRY_POINTS[command]
    else:
        raise GateError('unknown_command')
    function = getattr(import_module('.' + module, 'aclad'), name)
    hints = get_type_hints(function)
    properties, required = {}, []
    for parameter in signature(function).parameters.values():
        if parameter.name in hidden:
            continue
        item = _annotation_schema(hints.get(parameter.name, parameter.annotation))
        if parameter.default is Parameter.empty:
            required.append(parameter.name)
        else:
            item['default'] = parameter.default
        properties[parameter.name] = item
    result = {'command': command, 'input_schema': {'type': 'object', 'properties': properties,
              'required': required, 'additionalProperties': False},
              'workspace_required': not command.startswith(('workspace-', 'instance-')),
              'note': 'Assinatura real; objetos abertos ainda passam pelas validações e gates do domínio.',
              'recipes': 'references/operator-recipes.md'}
    if command == 'setup-answer':
        from .onboarding import QUESTIONS
        known_fields = _profile_fields(PROFILE)
        # Interview-only choices are not fields in the saved profile shape.
        for row in QUESTIONS:
            known_fields.setdefault(row[0], {'type': 'string'})
        result['fields'] = known_fields
        result['input_schema']['oneOf'] = [
            {'properties': {'field': {'const': path}, 'value': schema}}
            for path, schema in known_fields.items()]
    return result


def _examples() -> list[dict]:
    sender = {'provider': 'example', 'tenant_id': 'tenant-example',
              'connection_id': 'mail-example', 'object_id': 'seller-example'}
    draft = dict(sender, object_id='draft-example')
    message = {'account_id': 'account-example', 'contact_id': 'contact-example',
               'sender_ref': sender, 'to': ['person@example.invalid'], 'cc': [], 'bcc': [],
               'subject': 'Operação financeira', 'body': 'Podemos conversar sobre sua operação financeira?',
               'attachments': [], 'source_ids': ['research-example'], 'plan_step_id': 'step-example',
               'offering_ids': ['netsuite-example']}
    preflight = {'checked_at': '2026-10-27T12:00:00Z', 'connection_id': 'mail-example',
                 'ownership_allowed': True, 'contact_allowed': True, 'opportunity_allowed': True,
                 'external_revision': 'revision-example', 'sender_connection_id': 'mail-example',
                 'sender_object_id': 'seller-example', 'crm_confirmed': True, 'recent_replies': False}
    samples = [
        ('workspace-init', {'name': 'Prospecção Exemplo'}),
        ('setup-next', {}),
        ('setup-answer', {'field': 'partner.name', 'value': 'Parceiro Exemplo'}),
        ('setup-answer', {'field': 'partner.website', 'value': 'https://example.invalid'}),
        ('setup-answer', {'field': 'seller.territory', 'value': ['SP', 'MG']}),
        ('setup-answer', {'field': 'seller.portfolio', 'value': 'Contas próprias de serviços'}),
        ('setup-answer', {'field': 'seller.writing_style', 'value': 'Direto, abertura curta, sem jargão.'}),
        ('setup-answer', {'field': 'schedule_preferences.mode', 'value': 'manual'}),
        ('setup-answer', {'field': 'partner.offerings', 'value': [{'id': 'netsuite-example',
            'name': 'Oracle NetSuite', 'kind': 'netsuite', 'status': 'pending_review',
            'source_ids': ['research-example']}]}),
        ('style-presets', {}),
        ('portfolio-context', {}),
        ('connections-prepare-probe', {'capability': {'operation': 'crm.read',
            'tool_name': 'observed-read-tool', 'connection_id': 'observed-connection',
            'visibility': 'visible', 'auth': 'unknown', 'permission': 'unknown',
            'verification': 'declared', 'cost': 'free'}}),
        ('research-start', {'subject_id': 'partner-example', 'website': 'https://example.invalid',
                            'purpose': 'partner', 'identity_confirmed': True}),
        ('research-context', {'subject_id': 'account-example'}),
        ('generation-context', {'campaign_id': 'campaign-example', 'account_id': 'account-example',
            'contact_id': 'contact-example', 'task': 'email', 'plan_step_id': 'step-example'}),
        ('draft-propose', {'campaign_id': 'campaign-example', 'message': message}),
        ('send-propose', {'draft_ref': draft, 'current_draft': dict(message, external_revision='revision-example'),
                          'preflight': preflight}),
        ('approve', {'proposal_id': 'proposal-example', 'revision': 1, 'digest': 'digest-returned-by-runtime',
                     'approved_by': 'seller-example', 'approved_at': '2026-10-27T12:00:00Z'}),
        ('prepare-action', {'proposal_id': 'proposal-example', 'capability': {
            'operation': 'email.send', 'tool_name': 'tool-verified-by-host', 'connection_id': 'mail-example',
            'visibility': 'visible', 'auth': 'authenticated', 'permission': 'allowed',
            'verification': 'verified', 'cost': 'free'}, 'preflight': preflight,
            'now': '2026-10-27T12:00:00Z'}),
        ('delivery-record', {'message_id': 'message-example', 'result': {'action_id': 'action-example',
            'status': 'succeeded', 'external_refs': [dict(sender, object_id='sent-example')],
            'data': {'sent_at': '2026-10-27T12:00:00Z',
                     'conversation_ref': dict(sender, object_id='conversation-example')}}}),
        ('meetings-record', {'campaign_id': 'campaign-example', 'evidence_id': 'calendar-action-example',
            'observations': [{'ref': dict(sender, connection_id='calendar-example', object_id='event-example'),
                'source_revision': 'revision-example', 'status': 'confirmed',
                'starts_at': '2026-10-28T13:00:00Z', 'ends_at': '2026-10-28T13:30:00Z',
                'account_id': 'account-example', 'contact_ids': ['contact-example']}]}),
        ('learn', {'before': 'Imagino que sua equipe...', 'after': 'Evite sempre a expressão imagino que.',
            'scope_kind': 'personal:email', 'explicit': True, 'evidence_id': 'seller-correction-example'}),
        ('outcome-propose', {'context': {'task': 'email', 'objective': 'Apresentar operação financeira'},
            'instruction': 'Hipótese para revisão; a amostra não comprova eficácia.',
            'evidence_ids': ['outcome-observation-example']}),
        ('outcome-review', {'rule_id': 'rule-returned-by-runtime', 'revision': 1,
            'decision': 'approve', 'evidence_id': 'seller-review-example'}),
    ]
    if 'outcome-context' in COMMANDS:
        samples.append(('outcome-context', {'campaign_id': 'campaign-example', 'task': 'email'}))
    return [{'command': command, 'input': data} for command, data in samples]


def discover(operation: str, topic: str | None = None) -> dict:
    if topic is not None and topic != 'profile' and topic not in command_names():
        raise GateError('unknown_command')
    if operation == 'schema' or operation == 'help' and topic:
        if not topic:
            return {'topics': command_names() + ['profile'], 'next': 'schema COMMAND'}
        return command_schema(topic)
    if operation == 'examples':
        return {'examples': deepcopy([item for item in _examples() if topic is None or item['command'] == topic]),
                'synthetic': True,
                'note': 'Não executar com estes IDs/datas/fatos. Substituir pelos retornos reais; '
                        'exemplos não constituem consentimento ou evidência. Se vazio, consultar schema e receitas.',
                'recipes': 'references/operator-recipes.md'}
    return {'commands': command_names(), 'discovery': ['help', 'schema COMMAND', 'schema profile', 'examples [COMMAND]'],
            'note': 'Descoberta local sem stdin, workspace, banco, registro ou conector. '
                    'O vendedor conversa; o operador trata estes contratos internamente.',
            'recipes': 'references/operator-recipes.md'}
