"""Build reviewed plugin artifacts by explicit file allowlist, outside the checkout."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = PROJECT_ROOT / 'plugins' / 'aclad-prospecting'
sys.path.insert(0, str(PLUGIN_ROOT / 'runtime'))
from aclad.models import GateError


RUNTIME = ('__init__', '__main__', 'models', 'migrations', 'store', 'instances', 'commands',
           'approvals', 'policy', 'recovery', 'learning', 'profiles', 'connections',
           'onboarding', 'knowledge', 'icp_analysis', 'icps', 'accounts', 'prospecting',
           'crm', 'outreach', 'messages', 'delivery', 'followup', 'scheduling', 'hooks',
           'workspace', 'workspace_files', 'workspace_migration', 'context',
           'meetings', 'result_metrics', 'results', 'local_views', 'outcome_learning',
           'portfolio', 'research', 'web_fetch', 'style', 'contracts')
SKILLS = ('setup', 'check-connections', 'build-icp', 'find-accounts', 'prioritize',
          'batch', 'check-crm', 'research-account', 'find-contacts', 'enrich-contacts',
          'save-to-crm', 'briefing', 'outreach', 'replies', 'learn')
REFERENCES = ('runtime-contracts.md', 'session-protocol.md', 'connectors.md',
              'connector-bindings.md', 'connector-catalog.json', 'approval-gates.md',
              'platform-capabilities.md', 'platform-evidence.md', 'workspace-protocol.md',
              'operator-recipes.md')
KNOWLEDGE = ('ideal-customer', 'product-notes', 'competitors', 'proof',
             'tone-of-voice', 'pain-by-vertical', 'objections')
FILES = (('plugin.json', '.codex-plugin/plugin.json', '.claude-plugin/plugin.json',
          'assets/icon-light.png', 'assets/icon-dark.png',
          'README.md', 'LICENSE', 'hooks/README.md',
          'hooks/codex.json', 'hooks/claude.json', 'knowledge/learned-rules.md',
          'knowledge/playbooks/manifest.json', 'config/README.md',
          'config/partner.example.json', 'config/profile.schema.json',
          'agents/account-researcher.md', 'scheduled/reply-control.md')
         + tuple('runtime/aclad/' + name + '.py' for name in RUNTIME)
         + tuple('skills/' + name + '/SKILL.md' for name in SKILLS)
         + tuple('references/' + name for name in REFERENCES)
         + tuple('knowledge/skeleton/' + name + '.md' for name in KNOWLEDGE)
         + tuple('templates/' + name + '.md' for name in ('briefing', 'email', 'short-message'))
         + tuple('templates/workspace/' + name + '.md' for name in ('AGENTS', 'CLAUDE', 'empresa', 'vendedor')))
EVENTS = ('SessionStart', 'PreToolUse', 'PostToolUse', 'PreCompact', 'PostCompact', 'Stop', 'SessionEnd')


def _handler(surface: str, event: str) -> dict:
    if surface == 'codex':
        return {'type': 'command',
                'command': 'PYTHONPATH="${PLUGIN_ROOT}/runtime" python3 -m aclad.hooks --surface codex',
                'timeout': 3 if event == 'SessionEnd' else 10}
    return {'type': 'command', 'command': 'python3',
            'args': ['${CLAUDE_PLUGIN_ROOT}/runtime/aclad/hooks.py', '--surface', 'claude'],
            'timeout': 10}


def _json(data: bytes) -> dict:
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise GateError('invalid_package_json', 'Package JSON must be a valid object.') from None


def _read(repo: Path, name: str) -> bytes:
    path = repo / name
    if not path.is_file() or not path.resolve().is_relative_to(repo):
        raise GateError('package_path_unavailable', 'A required public package path is missing or outside the repository.')
    for part in (path, *path.parents):
        if part == repo:
            break
        if part.is_symlink():
            raise GateError('package_symlink_not_allowed', 'Reviewed package paths must be ordinary repository files.')
    return path.read_bytes()


def _hooks(data: bytes, surface: str) -> None:
    config = _json(data)
    if set(config) - {'description', 'hooks'} or not isinstance(config.get('hooks'), dict):
        raise GateError('invalid_hook_config')
    events = config['hooks']
    if set(events) != set(EVENTS) or any(events[event] != [{'hooks': [_handler(surface, event)]}] for event in EVENTS):
        raise GateError('unverified_hook_config', 'Only the reviewed native lifecycle handlers can be packaged.')


def _manifest(value: dict, contents: dict[str, bytes]) -> None:
    if (not isinstance(value.get('name'), str) or re.fullmatch(r'[a-z0-9][a-z0-9-]*', value['name']) is None
            or not isinstance(value.get('version'), str)
            or re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?', value['version']) is None):
        raise GateError('invalid_plugin_manifest')
    if 'mcpServers' in value:
        raise GateError('unverified_mcp_config', 'The package ships no configured private MCP servers.')
    for key in ('skills', 'hooks', 'agents', 'commands'):
        if key not in value:
            continue
        path = value[key]
        if not isinstance(path, str) or not path.startswith('./') or '..' in Path(path).parts:
            raise GateError('invalid_manifest_path')
        relative = path[2:].rstrip('/')
        if not any(name == relative or name.startswith(relative + '/') for name in contents):
            raise GateError('manifest_path_not_packaged')
    extension = value.get('extensions', {}).get('com.openai', {})
    if not isinstance(extension, dict):
        raise GateError('invalid_plugin_manifest')
    for key in ('hooks', 'onboardingSkill'):
        if key in extension:
            path = extension[key]
            if (not isinstance(path, str) or not path.startswith('./')
                    or '..' in Path(path).parts or path[2:] not in contents):
                raise GateError('manifest_path_not_packaged')
    interface = extension.get('interface', value.get('interface'))
    if interface is not None:
        if (not isinstance(interface, dict) or not isinstance(interface.get('shortDescription'), str)
                or len(interface['shortDescription']) > 30
                or interface.get('category') != 'Business & Operations'):
            raise GateError('invalid_plugin_listing')
        for key in ('logo', 'logoDark', 'composerIcon', 'composerIconDark'):
            path = interface.get(key)
            if (not isinstance(path, str) or not path.startswith('./assets/')
                    or '..' in Path(path).parts or path[2:] not in contents):
                raise GateError('invalid_plugin_asset')
            data = contents[path[2:]]
            if len(data) > 5 * 1024 * 1024 or not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) < 33:
                raise GateError('invalid_plugin_asset')
            width, height = struct.unpack('>II', data[16:24])
            if width != height or not 48 <= width <= 4096:
                raise GateError('invalid_plugin_asset')


def _public_catalog(data: bytes) -> bytes:
    manifest = _json(data)
    if (set(manifest) != {'version', 'rules'} or type(manifest.get('version')) is not int
            or manifest['version'] != 1 or not isinstance(manifest.get('rules'), list)):
        raise GateError('invalid_knowledge_catalog')
    public = []
    for rule in manifest['rules']:
        if not isinstance(rule, dict):
            raise GateError('invalid_knowledge_catalog')
        if rule.get('audience') != 'partner' or rule.get('status') != 'approved':
            continue
        if set(rule) != {'id', 'source_file', 'source_page', 'source_date', 'reviewed_at',
                         'stage', 'industry', 'persona', 'audience', 'status', 'rule', 'valid_until'}:
            raise GateError('unreviewed_public_knowledge')
        if not rule.get('reviewed_at') or not rule.get('source_file') or not rule.get('source_page'):
            raise GateError('unreviewed_public_knowledge')
        public.append(rule)
    return (json.dumps({'version': 1, 'rules': public}, ensure_ascii=False, indent=2) + '\n').encode()


def build_plugin(repo: Path, destination: Path, surface: str) -> Path:
    """Produce one target ZIP, retaining both manifests but selecting native hooks."""
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    plugin = repo / 'plugins' / 'aclad-prospecting'
    if not (plugin / 'plugin.json').is_file():
        plugin = repo
    if surface not in ('codex', 'claude'):
        raise GateError('unknown_package_surface')
    if destination.is_relative_to(repo):
        raise GateError('package_destination_inside_repo')
    contents = {name: _read(plugin, name) for name in FILES}
    for target in ('codex', 'claude'):
        _hooks(contents['hooks/' + target + '.json'], target)
    # Claude merges its conventional hooks/hooks.json with an explicit manifest
    # hook file. Its manifest already declares hooks/claude.json (also needed
    # by Git installs); ship that single registration instead of both.
    if surface == 'codex':
        contents['hooks/hooks.json'] = contents['hooks/codex.json']
    contents['knowledge/playbooks/manifest.json'] = _public_catalog(contents['knowledge/playbooks/manifest.json'])
    manifests = [_json(contents[name]) for name in ('plugin.json', '.codex-plugin/plugin.json', '.claude-plugin/plugin.json')]
    for manifest in manifests:
        _manifest(manifest, contents)
    if any(manifest['name'] != manifests[0]['name'] or manifest['version'] != manifests[0]['version']
           for manifest in manifests[1:]):
        raise GateError('plugin_manifest_mismatch')
    if manifests[0].get('extensions', {}).get('com.openai', {}).get('interface') != manifests[1].get('interface'):
        raise GateError('plugin_listing_mismatch')
    if set(manifests[0]) & {'skills', 'mcpServers', 'apps', 'interface'}:
        raise GateError('invalid_portable_manifest')
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{manifests[0]['name']}-{surface}-{manifests[0]['version']}.zip"
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as package:
        for name, data in sorted(contents.items()):
            package.writestr(name, data)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=PROJECT_ROOT)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--surface', choices=('codex', 'claude'), required=True)
    args = parser.parse_args()
    try:
        print(build_plugin(args.repo, args.destination, args.surface))
        return 0
    except GateError as exc:
        print(f'{exc.code}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
