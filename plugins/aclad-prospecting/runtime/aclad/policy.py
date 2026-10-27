"""Fail-closed operation policy for the native-tool execution bridge."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .models import Capability, GateError, Payload, utc

# Only connector operations deliberately supported by the workflow are executable.
OPERATIONS = {
    'accounts.search': {'selection': None, 'approval': False, 'preflight': False},
    'companies.enrich': {'selection': 'account', 'approval': True, 'preflight': False},
    'people.search': {'selection': 'account', 'approval': False, 'preflight': False},
    'people.reveal_email': {'selection': 'contact', 'approval': True, 'preflight': False},
    'crm.read': {'selection': None, 'approval': False, 'preflight': False},
    'crm.write': {'selection': 'either', 'approval': True, 'preflight': True},
    'email.read': {'selection': None, 'approval': False, 'preflight': False},
    'email.create_draft': {'selection': 'contact', 'approval': True, 'preflight': False},
    'email.send': {'selection': 'contact', 'approval': True, 'preflight': True},
    'calendar.read': {'selection': None, 'approval': False, 'preflight': False},
}


def operation_policy(operation: str) -> dict[str, object]:
    if operation not in OPERATIONS:
        raise GateError('operation_not_allowed')
    return OPERATIONS[operation]


def validate_capability(operation: str, connection_id: str, capability: Capability) -> None:
    if capability.operation != operation:
        raise GateError('operation_mismatch')
    if capability.connection_id != connection_id:
        raise GateError('connection_mismatch')
    if (capability.visibility != 'visible' or capability.auth != 'authenticated'
            or capability.permission != 'allowed' or capability.verification != 'verified'
            or not isinstance(capability.tool_name, str) or not capability.tool_name.strip()):
        raise GateError('capability_unverified')
    if capability.cost not in {'free', 'paid', 'unknown'}:
        raise GateError('cost_unverified')


def validate_cost(capability: Capability, proposal_payload: Payload, count: int) -> None:
    if capability.cost == 'free':
        return
    limits = proposal_payload.get('limits')
    if not isinstance(limits, dict) or limits.get('cost_acknowledged') is not True:
        raise GateError('cost_limit_required')
    maximum = limits.get('max_items')
    if type(maximum) is not int or maximum < max(1, count):
        raise GateError('cost_limit_required')
    credits = limits.get('max_credits')
    if credits is None:
        # Unknown unit prices can still be authorized as a bounded number of
        # operations, but only with an explicit acknowledgement of that limit.
        if limits.get('unknown_cost_accepted') is not True:
            raise GateError('cost_limit_required')
        return
    try:
        if not isinstance(credits, str) or not Decimal(credits).is_finite() or Decimal(credits) <= 0:
            raise InvalidOperation()
    except (InvalidOperation, ValueError):
        raise GateError('cost_limit_required') from None


def validate_preflight(operation: str, connection_id: str, proposal_payload: Payload,
                       preflight: Payload, now: str, reviewed_reply_event_id: str | None = None) -> None:
    if not operation_policy(operation)['preflight']:
        return
    required = {'checked_at', 'connection_id', 'ownership_allowed', 'contact_allowed',
                'opportunity_allowed', 'external_revision'}
    if not required.issubset(preflight):
        raise GateError('preflight_required')
    if preflight['connection_id'] != connection_id:
        raise GateError('connection_mismatch')
    elapsed = (utc(now) - utc(preflight['checked_at'])).total_seconds()
    if elapsed < 0 or elapsed > 300:
        raise GateError('preflight_stale')
    for key, code in [('ownership_allowed', 'ownership_blocked'),
                      ('contact_allowed', 'contact_blocked'),
                      ('opportunity_allowed', 'opportunity_blocked')]:
        if preflight[key] is not True:
            raise GateError(code)
    if operation == 'email.send':
        sender = proposal_payload.get('message', {}).get('sender_ref', {})
        if (preflight.get('sender_connection_id') != sender.get('connection_id')
                or preflight.get('sender_object_id') != sender.get('object_id')
                or not sender.get('object_id')):
            raise GateError('sender_mismatch')
        if preflight.get('crm_confirmed') is not True:
            raise GateError('crm_unconfirmed')
        if reviewed_reply_event_id:
            if any(preflight.get(key) != reviewed_reply_event_id
                   for key in ('reviewed_reply_event_id', 'latest_reply_event_id')):
                raise GateError('reply_review_stale')
        elif preflight.get('recent_replies') is not False:
            raise GateError('contact_blocked')
    expected = proposal_payload.get('external_revision')
    if expected is None or preflight['external_revision'] != expected:
        raise GateError('external_changed')
