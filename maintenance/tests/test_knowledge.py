import unittest
from aclad.knowledge import validate_source, select_playbooks
from aclad.models import GateError
from tests.support import NOW

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id':'hon','source_file':'Quick Guide.pdf','source_page':39,
          'source_date':None,'reviewed_at':NOW,'stage':'outreach','industry':None,
          'persona':None,'audience':'partner','status':'approved',
          'rule':'Present the pain as a hypothesis to validate.','valid_until':None}
    def test_internal_rules_are_not_exported_as_partner_guidance(self):
        source = dict(self.source, audience='authoring')
        self.assertEqual(select_playbooks([source], 'outreach', None, None, 'partner', NOW), [])
    def test_missing_source_prevents_approval(self):
        with self.assertRaises(GateError):
            validate_source(dict(self.source, source_page=None))
    def test_expired_or_unreviewed_rules_are_not_selected(self):
        for override in ({'status':'unreviewed'}, {'valid_until':'2026-01-01T00:00:00Z'}):
            self.assertEqual(select_playbooks([dict(self.source, **override)], 'outreach', None, None, 'partner', NOW), [])
    def test_matching_persona_industry_and_stage(self):
        cfo = dict(self.source, id='cfo', industry='manufacturing', persona='cfo')
        self.assertEqual([r['id'] for r in select_playbooks([self.source,cfo], 'outreach', 'manufacturing','cfo','partner', NOW)], ['hon','cfo'])
        self.assertEqual(select_playbooks([cfo], 'outreach','services','cfo','partner', NOW), [])
    def test_no_cadence_rule_is_an_explicit_empty_result(self):
        self.assertEqual(select_playbooks([self.source], 'cadence',None,None,'partner',NOW), [])
