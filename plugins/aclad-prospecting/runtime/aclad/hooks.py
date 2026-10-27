"""Optional native lifecycle reinforcement; explicit skill recovery remains required."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    # The verified Claude exec-form hook invokes this file, without shell/PYTHONPATH.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aclad.models import GateError, Payload, Scope, canonical
from aclad.recovery import bootstrap, checkpoint
from aclad.store import Store


EVENTS = ('SessionStart', 'PreToolUse', 'PostToolUse', 'PreCompact',
          'PostCompact', 'Stop', 'SessionEnd')
_SETUP = 'ACLAD: run setup/check-connections and explicit resume with trusted private state before continuing.'


def _message(event: str, text: str) -> Payload:
    if event == 'SessionStart':
        return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}}
    if event in ('PostCompact', 'SessionEnd'):
        return {}  # Claude documents these as side-effect-only events.
    return {'systemMessage': text}


def _deny() -> Payload:
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': 'ACLAD: persist and validate a matching action through the runtime bridge first.'}}


def handle_hook(surface: str, event: str, payload: Payload) -> Payload:
    """Consume documented native event keys; never interpret transcript/tool text."""
    if surface not in ('codex', 'claude') or event not in EVENTS:
        return {}
    if (not isinstance(payload, dict) or payload.get('hook_event_name') != event
            or not isinstance(payload.get('session_id'), str)
            or not isinstance(payload.get('cwd'), str)):
        return _message(event, 'ACLAD: invalid hook event; use the explicit session protocol.')
    values = [os.environ.get(key) for key in ('ACLAD_STATE_DIR', 'ACLAD_PARTNER_ID',
              'ACLAD_SELLER_ID', 'ACLAD_INSTANCE_ID')]
    store = None
    try:
        from aclad.workspace import locate_workspace
        local = locate_workspace(Path(payload['cwd']))
        if local:
            selected = [local['state_dir'], local['partner_id'], local['seller_id'], local['instance_id']]
            if any(values) and values != selected:
                raise GateError('identity_mismatch')
            values = selected
        elif not any(values):
            return {}
        if any(not value for value in values):
            return _message(event, _SETUP)
        directory = Path(values[0]).expanduser()
        if not directory.is_absolute() or not (directory / 'state.sqlite').is_file():
            return _message(event, _SETUP)
        store = Store(directory, Scope(*values[1:]))
        if event in ('SessionStart', 'PostCompact'):
            snapshot = bootstrap(store)
            context = ('ACLAD recovered private state: '
                       f'event_sequence={snapshot.event_sequence}; '
                       f'record_count={len(snapshot.records)}; pending_count={len(snapshot.pending)}. '
                       'Use explicit resume and scoped rules before continuing; reconcile unknown effects.')
            return _message(event, context)
        if event == 'PreToolUse':
            name = payload.get('tool_name')
            known = any(row.data.get('capability', {}).get('tool_name') == name
                        for row in store.list('connection'))
            if not known:
                return {}  # Unknown tools are not claimed to be intercepted.
            args = payload.get('tool_input')
            if not isinstance(args, dict):
                return _deny()
            snapshot = bootstrap(store)
            matching = [row for row in snapshot.records if row.kind == 'action'
                        and row.data.get('status') == 'in_flight'
                        and row.data.get('tool_name') == name
                        and canonical(row.data.get('payload')) == canonical(args)]
            if len(matching) != 1:
                return _deny()
            # No native approval grant: provider/user controls remain authoritative.
            return {}
        checkpoint(store)
        if event == 'PostToolUse':
            return _message(event, 'ACLAD: record the normalized provider result through the bridge; a hook checkpoint does not confirm the effect.')
        return _message(event, 'ACLAD: durable state checkpoint available; explicit resume is required next time.')
    except Exception:
        # No exception detail, tool payload, token, path or transcript on stdout.
        if event == 'PreToolUse':
            return _deny()
        return _message(event, 'ACLAD: state recovery unavailable; use setup/explicit resume before paid or external work.')
    finally:
        if store:
            store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--surface', required=True, choices=('codex', 'claude'))
    args = parser.parse_args(argv)
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise ValueError()
        result = handle_hook(args.surface, raw.get('hook_event_name'), raw)
    except (ValueError, TypeError):
        result = {'systemMessage': 'ACLAD: invalid hook input; use explicit session recovery.'}
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
