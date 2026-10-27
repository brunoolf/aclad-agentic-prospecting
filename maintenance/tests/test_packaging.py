import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from aclad.models import GateError
from tools.build_plugin import build_plugin


class OfficialLayoutTests(unittest.TestCase):
    def test_official_marketplaces_resolve_the_canonical_nested_plugin(self):
        root = Path(__file__).resolve().parents[2]
        expected = (root / 'plugins/aclad-prospecting').resolve()
        for manifest in ('.agents/plugins/marketplace.json', '.claude-plugin/marketplace.json'):
            with self.subTest(manifest=manifest):
                catalog = json.loads((root / manifest).read_text())
                entry, = [row for row in catalog['plugins'] if row['name'] == 'aclad-prospecting']
                source = entry['source']
                relative = source['path'] if isinstance(source, dict) else source
                resolved = (root / relative).resolve()
                self.assertEqual(resolved, expected)
                self.assertEqual(json.loads((resolved / 'plugin.json').read_text())['name'], entry['name'])


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo with spaces'
        self.repo.mkdir()
        self.plugin = self.repo / 'plugins/aclad-prospecting'
        self.plugin.mkdir(parents=True)
        self.destination = Path(self.tmp.name) / 'artifacts'
        original = Path(__file__).resolve().parents[2] / 'plugins/aclad-prospecting'
        for directory in ('runtime','skills','references','knowledge','templates','agents','scheduled','hooks','.codex-plugin','.claude-plugin'):
            shutil.copytree(original / directory,self.plugin / directory,symlinks=True,
                            ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for name in ('README.md','LICENSE'):
            shutil.copyfile(original/name,self.plugin/name)
        if (original/'plugin.json').exists():
            shutil.copyfile(original/'plugin.json', self.plugin/'plugin.json')
        if (original/'assets').exists():
            shutil.copytree(original/'assets', self.plugin/'assets')
        (self.plugin/'config').mkdir()
        for name in ('README.md','partner.example.json','profile.schema.json'):
            shutil.copyfile(original/'config'/name,self.plugin/'config'/name)

    def build(self,surface='codex'):
        return build_plugin(self.repo,self.destination,surface)

    def test_package_excludes_private_authoring_and_unknown_files(self):
        for name in ('config/partner.json','config/token.txt','runtime/aclad/state.sqlite',
                     'runtime/aclad/private.py','skills/setup/seller.json','knowledge/examples/customer.md',
                     'record/private.md','docs/spec.md','NetSuite Guides/internal.pdf','.git/config','backup.bak',
                     '.local/archive/seller.md','CHANGELOG.md','COMO-INSTALAR.md'):
            path=self.plugin/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('PRIVATE')
        archive_private = self.repo / '.local/archive/seller.md'
        archive_private.parent.mkdir(parents=True)
        archive_private.write_text('PRIVATE_ROOT_ARCHIVE')
        archive=self.build()
        self.assertFalse(archive.is_relative_to(self.repo))
        with zipfile.ZipFile(archive) as package:
            names=package.namelist()
            self.assertIn('runtime/aclad/hooks.py',names)
            self.assertIn('skills/build-icp/SKILL.md',names)
            self.assertIn('LICENSE',names)
            self.assertIn('README.md',names)
            self.assertNotIn('COMO-INSTALAR.md',names)
            self.assertNotIn('CHANGELOG.md',names)
            self.assertNotIn('config/partner.json',names)
            self.assertNotIn('runtime/aclad/private.py',names)
            self.assertFalse(any(n.startswith(('NetSuite Guides/','docs/','.git/','record/','.local/','maintenance/')) for n in names))
            self.assertFalse(any(n.endswith(('.sqlite','.db','.bak')) for n in names))
            self.assertFalse(any(b'PRIVATE' in package.read(n) for n in names))

    def test_both_manifests_resolve_and_target_selects_native_hook_schema(self):
        for surface in ('codex','claude'):
            with zipfile.ZipFile(self.build(surface)) as package:
                names=package.namelist()
                for name in ('.codex-plugin/plugin.json','.claude-plugin/plugin.json'):
                    manifest=json.loads(package.read(name))
                    self.assertNotIn('mcpServers',manifest)
                    for field in ('skills','hooks'):
                        path=manifest.get(field)
                        if isinstance(path,str):
                            self.assertTrue(any(n==path[2:] or n.startswith(path[2:].rstrip('/')+'/') for n in names))
                if surface == 'claude':
                    self.assertNotIn('hooks/hooks.json', names)
                    declared = json.loads(package.read('.claude-plugin/plugin.json'))['hooks'][2:]
                    target = json.loads(package.read(declared))
                else:
                    target = json.loads(package.read('hooks/hooks.json'))
                source=json.loads(package.read('hooks/'+surface+'.json'))
                self.assertEqual(target,source)

    def test_invalid_or_unverified_hook_json_prevents_artifact(self):
        config=self.plugin/'hooks/codex.json'
        config.write_text('{invalid')
        with self.assertRaises(GateError):
            self.build()
        self.assertFalse(self.destination.exists())

    def test_manifest_escape_or_symlink_is_rejected(self):
        source=self.plugin/'templates/email.md'
        source.unlink()
        outside=Path(self.tmp.name)/'secret.md';outside.write_text('outside')
        source.symlink_to(outside)
        with self.assertRaises(GateError):
            self.build()

    def test_manifest_path_must_exist_inside_allowlist(self):
        path=self.plugin/'.codex-plugin/plugin.json'
        manifest=json.loads(path.read_text());manifest['hooks']='../../outside.json'
        path.write_text(json.dumps(manifest))
        with self.assertRaises(GateError):
            self.build()

    def test_public_knowledge_excludes_authoring_rules(self):
        with zipfile.ZipFile(self.build()) as package:
            catalog=json.loads(package.read('knowledge/playbooks/manifest.json'))
        self.assertTrue(catalog['rules'])
        self.assertTrue(all(r['audience']=='partner' and r['status']=='approved' for r in catalog['rules']))

    def test_unreviewed_extra_knowledge_fields_cannot_leak_customer_rows(self):
        path=self.plugin/'knowledge/playbooks/manifest.json'
        catalog=json.loads(path.read_text())
        catalog['rules'][0]['customer_rows']=[{'email':'private@example.invalid'}]
        path.write_text(json.dumps(catalog))
        with self.assertRaises(GateError):
            self.build()

    def test_destination_inside_repo_or_unknown_surface_is_rejected(self):
        with self.assertRaises(GateError):
            build_plugin(self.repo,self.repo/'dist','codex')
        with self.assertRaises(GateError):
            self.build('invented')

    def test_workspace_artifacts_never_ship(self):
        for name in ('.aclad/state.sqlite','.aclad/workspace.json','.aclad/backups/backup.sqlite',
                     'contexto/resultados.md','contexto/aprendizados.md','contexto/vendedor.md'):
            path=self.plugin/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('SELLER_PRIVATE_SENTINEL')
        for surface in ('codex','claude'):
            with zipfile.ZipFile(self.build(surface)) as package:
                self.assertFalse(any(name.startswith(('.aclad/','contexto/')) for name in package.namelist()))
                self.assertFalse(any(b'SELLER_PRIVATE_SENTINEL' in package.read(name) for name in package.namelist()))

    def test_new_runtime_templates_and_version_ship(self):
        for surface in ('codex','claude'):
            with zipfile.ZipFile(self.build(surface)) as package:
                for manifest in ('.codex-plugin/plugin.json','.claude-plugin/plugin.json'):
                    self.assertEqual(json.loads(package.read(manifest))['version'],'0.4.1')
                for name in ('runtime/aclad/local_views.py','runtime/aclad/outcome_learning.py',
                             'templates/workspace/AGENTS.md','references/workspace-protocol.md'):
                    self.assertIn(name,package.namelist())
                hook_path = ('hooks/hooks.json' if surface == 'codex' else
                    json.loads(package.read('.claude-plugin/plugin.json'))['hooks'][2:])
                hooks=json.loads(package.read(hook_path))
                expected=3 if surface=='codex' else 10
                self.assertEqual(hooks['hooks']['SessionEnd'][0]['hooks'][0]['timeout'],expected)

    def test_portable_listing_icons_and_compatibility_match(self):
        with zipfile.ZipFile(self.build()) as package:
            portable = json.loads(package.read('plugin.json'))
            compat = json.loads(package.read('.codex-plugin/plugin.json'))
            settings = portable['extensions']['com.openai']
            self.assertEqual(portable['version'], '0.4.1')
            self.assertEqual(settings['interface'], compat['interface'])
            self.assertEqual(settings['hooks'], './hooks/codex.json')
            self.assertEqual(settings['onboardingSkill'], './skills/setup/SKILL.md')
            listing = settings['interface']
            self.assertLessEqual(len(listing['shortDescription']), 30)
            self.assertEqual(listing['category'], 'Business & Operations')
            for key in ('logo', 'logoDark', 'composerIcon', 'composerIconDark'):
                self.assertTrue(package.read(listing[key][2:]).startswith(b'\x89PNG\r\n\x1a\n'))

    def test_missing_or_escaping_listing_assets_rejected(self):
        path = self.plugin/'.codex-plugin/plugin.json'
        manifest = json.loads(path.read_text())
        manifest['interface']['logo'] = '../../private.png'
        path.write_text(json.dumps(manifest))
        with self.assertRaises(GateError):
            self.build()

    def test_new_research_and_policy_modules_ship(self):
        with zipfile.ZipFile(self.build()) as package:
            for module in ('portfolio', 'research', 'web_fetch', 'style'):
                self.assertIn(f'runtime/aclad/{module}.py', package.namelist())

    def test_discovery_and_operator_recipes_ship_for_a_fresh_install(self):
        for surface in ('codex', 'claude'):
            with zipfile.ZipFile(self.build(surface)) as package:
                self.assertIn('runtime/aclad/contracts.py', package.namelist())
                self.assertIn('references/operator-recipes.md', package.namelist())
