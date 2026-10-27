"""JSON-only command boundary used by skills, not a seller-facing interface."""
from __future__ import annotations
import argparse
import os
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from .models import GateError, Scope, payload
from .store import Store

from .commands import dispatch

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ACLAD: contratos internos e comandos JSON.",
        epilog="Sem estado: help | schema COMMAND | schema profile | examples [COMMAND].")
    for name in ('state-dir', 'partner-id', 'seller-id', 'instance-id'):
        parser.add_argument('--' + name)
    parser.add_argument('--registry-dir')
    parser.add_argument('--workspace')
    parser.add_argument('command', nargs='?', default='help')
    parser.add_argument('topic', nargs='?', help='Somente para help/schema/examples')
    args = parser.parse_args(argv)
    store = None
    try:
        from .contracts import DISCOVERY, command_names, discover
        if args.command in DISCOVERY:
            print(json.dumps(discover(args.command, args.topic), ensure_ascii=False, allow_nan=False))
            return 0
        if args.command not in command_names():
            raise GateError('unknown_command')
        if args.topic is not None:
            raise GateError('invalid_arguments')
        raw = sys.stdin.read(1_048_577)
        if len(raw) > 1_048_576:
            raise GateError('input_too_large')
        try:
            data = payload(json.loads(raw or '{}'))
        except (ValueError, RecursionError):
            raise GateError('invalid_json') from None
        from .instances import initialize_instance, locate_instance, list_instances
        registry = Path(args.registry_dir or os.environ.get('ACLAD_REGISTRY_DIR', str(Path.home()/'.aclad-prospecting')))
        from .workspace import initialize_workspace, locate_workspace
        root = Path(args.workspace).expanduser().resolve() if args.workspace else Path.cwd()
        if args.command in {'workspace-init', 'workspace-locate', 'workspace-migration-preview', 'workspace-migrate'}:
            if args.command == 'workspace-init':
                result = initialize_workspace(root, data.get('name'))
            elif args.command == 'workspace-locate':
                result = locate_workspace(root)
                if result is None:
                    raise GateError('instance_setup_required')
            else:
                from .workspace_migration import preview_migration, migrate_instance
                if args.command == 'workspace-migration-preview':
                    result = preview_migration(registry, data.get('instance_id'), root)
                else:
                    result = migrate_instance(registry, data.get('instance_id'), root, data.get('preview_digest'))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command in {'instance-init','instance-list','instance-locate'}:
            if args.command == 'instance-init':
                result = initialize_instance(registry,data.get('name'))
            elif args.command == 'instance-list':
                result = list_instances(registry)
            else:
                result = locate_instance(registry,data.get('instance_id'))
            print(json.dumps(result,ensure_ascii=False))
            return 0
        selectors = [args.state_dir,args.partner_id,args.seller_id,args.instance_id]
        if any(selectors) and not all(selectors):
            raise GateError('complete_scope_required')
        local = locate_workspace(root)
        if args.workspace and local is None:
            raise GateError('instance_setup_required')
        if local and any(selectors) and selectors != [local['state_dir'],local['partner_id'],local['seller_id'],local['instance_id']]:
            raise GateError('identity_mismatch')
        if not any(selectors):
            selected = local or locate_instance(registry,data.get('instance_id'))
            data.pop('instance_id',None)
            selectors = [selected['state_dir'],selected['partner_id'],selected['seller_id'],selected['instance_id']]
        store = Store(Path(selectors[0]), Scope(*selectors[1:]))
        result = dispatch(store, args.command, data)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, default=asdict))
        return 0
    except GateError as exc:
        error = {'code': exc.code, 'message': str(exc)}
        if exc.code in {'unknown_command', 'invalid_arguments', 'invalid_profile', 'invalid_setup_field'}:
            error['hint'] = 'Use help, schema COMMAND, schema profile ou examples COMMAND antes de executar.'
        print(json.dumps({'error': error}))
        return 2
    except (OSError, sqlite3.Error, TypeError, KeyError, ValueError):
        print(json.dumps({'error': {'code': 'runtime_error', 'message': 'Operation failed; state must be checked before retrying.'}}))
        return 1
    finally:
        if store:
            store.close()

if __name__ == '__main__':
    raise SystemExit(main())
