"""Package references must resolve from the consuming skill's own directory."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2] / 'plugins/aclad-prospecting'


class SkillReferencePathTests(unittest.TestCase):
    def test_packaged_references_open_from_each_skill_location(self):
        checked = 0
        broken = []
        for skill in sorted((ROOT / 'skills').glob('*/SKILL.md')):
            text = skill.read_text()
            paths = re.findall(r'`([^`\n]+)`|\]\(([^)\n]+)\)', text)
            for inline, link in paths:
                candidate = inline or link
                if not re.match(r'^(?:\.\./)*(?:references|templates|scheduled|knowledge)/[^ ]+\.md$', candidate):
                    continue
                checked += 1
                path = (skill.parent / candidate).resolve()
                if not path.is_relative_to(ROOT) or not path.is_file():
                    broken.append(f'{skill.relative_to(ROOT)} -> {candidate}')
        self.assertGreater(checked, 10, 'No useful package paths were inspected')
        self.assertEqual(broken, [], '\n'.join(broken))
