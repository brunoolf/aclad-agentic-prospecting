"""Private, evidence-backed corrections; candidates never become implicit policy."""
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4

from .models import Event, GateError, Record
from .store import Store


_PERSONAL = {'personal:briefing', 'personal:email', 'personal:all'}
_SECRET = re.compile(
    r'(?i)(?:\bbearer\s+\S+|(?:access[_ -]?token|refresh[_ -]?token|'
    r'api[_ -]?key|password|client[_ -]?secret)\s*[:=]\s*\S+)'
)


def _text(value: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise GateError('invalid_correction', 'Provide a short correction and evidence reference.')
    if _SECRET.search(value):
        raise GateError('secret_not_allowed', 'Credentials cannot be stored as learning.')
    return value.strip()


def _scope(scope_kind: str) -> str:
    if not isinstance(scope_kind, str) or (
        scope_kind not in _PERSONAL and scope_kind != 'partner:product'
        and not (scope_kind.startswith('account:') and scope_kind[8:].strip())
    ):
        raise GateError('invalid_rule_scope', 'Choose a supported personal, product or account scope.')
    return _text(scope_kind, 300)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def capture_correction(store: Store, before: str, after: str, scope_kind: str,
                       explicit: bool, evidence_id: str) -> Record:
    """Persist a short observed edit, without promoting inferred/account facts.

    ``explicit`` means the seller asked for a reusable personal preference; an
    edit alone is not such a request. Evidence IDs point to private source data.
    Identical captures are idempotent; additional evidence retains provenance.
    """
    scope_kind = _scope(scope_kind)
    if type(explicit) is not bool:
        raise GateError('invalid_correction', 'Explicit confirmation must be a boolean.')
    evidence_id = _text(evidence_id, 256)
    if not isinstance(before, str) or not isinstance(after, str):
        raise GateError('invalid_correction', 'Correction text is required.')
    if not after.strip() or ' '.join(before.split()) == ' '.join(after.split()):
        raise GateError('no_correction', 'Unchanged or absent output is not a learning signal.')
    before, after = _text(before), _text(after)
    canonical = json.dumps([scope_kind, ' '.join(after.split())], ensure_ascii=False)
    rule_id = 'rule-' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    now = _now()
    active = explicit and scope_kind in _PERSONAL
    evidence = {'id': evidence_id, 'before': before, 'explicit': explicit, 'captured_at': now}
    with store.transaction():
        existing = store.get('rule', rule_id)
        if existing:
            data = dict(existing.data)
            sources = list(data['evidence'])
            previous = next((e for e in sources if e['id'] == evidence_id), None)
            if previous:
                if previous['before'] != before or previous['explicit'] != explicit:
                    raise GateError('evidence_conflict', 'Evidence already records a different correction.')
                return existing
            sources.append(evidence)
            data['evidence'] = sources
            data['updated_at'] = now
            # Revocation survives re-observation; repeated edits are not reactivation.
            if active and data['status'] != 'revoked':
                data['status'] = 'active'
                data['reason'] = 'Explicit personal preference requested by the seller.'
        else:
            data = {
                'scope_kind': scope_kind, 'instruction': after,
                'status': 'active' if active else 'candidate',
                'reason': ('Explicit personal preference requested by the seller.' if active
                           else 'Observed correction retained for review in its original scope.'),
                'created_at': now, 'updated_at': now, 'evidence': [evidence],
            }
        record = store.put('rule', rule_id, data, existing.revision if existing else None)
        store.record_event(Event(
            'evt-' + uuid4().hex, rule_id, 'learning_captured', now,
            {'evidence_id': evidence_id, 'scope_kind': scope_kind,
             'revision': record.revision, 'status': data['status'], 'reason': data['reason']},
        ))
        return record


def relevant_rules(store: Store, scope_kind: str) -> list[Record]:
    """Read active rules for the requested scope, with explicit personal-all inheritance."""
    scope_kind = _scope(scope_kind)
    scopes = {scope_kind}
    if scope_kind in _PERSONAL:
        scopes.add('personal:all')
    return [rule for rule in store.list('rule')
            if rule.data.get('status') == 'active' and rule.data.get('scope_kind') in scopes]


def revoke_rule(store: Store, rule_id: str, revision: int, reason: str) -> Record:
    """Revoke the exact version; retain evidence and the historical decision."""
    rule_id, reason = _text(rule_id, 300), _text(reason, 500)
    if type(revision) is not int or revision < 1:
        raise GateError('revision_conflict', 'Use the current rule revision.')
    with store.transaction():
        rule = store.get('rule', rule_id)
        if not rule:
            raise GateError('rule_not_found', 'The rule is not present in this private instance.')
        now = _now()
        data = dict(rule.data)
        data.update(status='revoked', updated_at=now, revoked_at=now, revocation_reason=reason)
        revoked = store.put('rule', rule_id, data, revision)
        store.record_event(Event(
            'evt-' + uuid4().hex, rule_id, 'learning_revoked', now,
            {'revision': revoked.revision, 'reason': reason},
        ))
        return revoked
