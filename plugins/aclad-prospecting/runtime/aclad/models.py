"""Shared value objects and validated JSON at the private-state boundary."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone

Payload = dict[str, object]

class GateError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code.replace('_', ' '))

_SECRET_KEYS = {'password', 'passwd', 'access_token', 'refresh_token', 'api_key',
                'apikey', 'authorization', 'credentials', 'client_secret', 'secret'}

def json_value(value: object, depth: int = 0) -> object:
    if depth > 40:
        raise GateError('invalid_json')
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [json_value(v, depth + 1) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise GateError('invalid_json')
            if key.lower().replace('-', '_') in _SECRET_KEYS:
                raise GateError('credentials_not_allowed')
            result[key] = json_value(item, depth + 1)
        return result
    raise GateError('invalid_json')

def payload(value: object) -> Payload:
    if not isinstance(value, dict):
        raise GateError('object_required')
    return json_value(value)

def canonical(value: object) -> str:
    return json.dumps(json_value(value), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)

def utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError):
        raise GateError('invalid_timestamp') from None

def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

@dataclass(frozen=True)
class Scope:
    partner_id: str
    seller_id: str
    instance_id: str
    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in
               (self.partner_id, self.seller_id, self.instance_id)):
            raise GateError('invalid_scope')

@dataclass(frozen=True)
class ExternalRef:
    provider: str
    tenant_id: str
    connection_id: str
    object_id: str

@dataclass(frozen=True)
class Record:
    id: str
    kind: str
    revision: int
    data: Payload

@dataclass(frozen=True)
class Event:
    id: str
    record_id: str
    kind: str
    occurred_at: str
    data: Payload

@dataclass(frozen=True)
class Snapshot:
    event_sequence: int
    records: list[Record]
    pending: list[Record]

@dataclass(frozen=True)
class Capability:
    operation: str
    tool_name: str
    connection_id: str
    visibility: str
    auth: str
    permission: str
    verification: str
    cost: str

@dataclass(frozen=True)
class Proposal:
    id: str
    revision: int
    operation: str
    connection_id: str
    item_ids: list[str]
    payload: Payload
    digest: str
    status: str

@dataclass(frozen=True)
class Approval:
    proposal_id: str
    revision: int
    digest: str
    approved_by: str
    approved_at: str

@dataclass(frozen=True)
class ToolIntent:
    action_id: str
    operation: str
    tool_name: str
    connection_id: str
    payload: Payload
    digest: str

@dataclass(frozen=True)
class ToolResult:
    action_id: str
    status: str
    external_refs: list[ExternalRef]
    data: Payload
