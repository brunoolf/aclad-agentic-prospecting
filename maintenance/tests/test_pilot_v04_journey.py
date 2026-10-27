from copy import deepcopy
from dataclasses import asdict

from aclad.approvals import approve, prepare_action
from aclad.commands import dispatch
from aclad.messages import propose_draft
from aclad.models import Capability, GateError
from aclad.outreach import generation_context
from aclad.profiles import save_profile
from tests import test_outcome_observations as journey


def company_site(url):
    homepage = url.endswith('/')
    return {'url': url, 'status': 200 if homepage else 404,
            'content_type': 'text/html' if homepage else 'text/plain',
            'text': '<title>Factory A</title><p>Opened a new factory for industrial production.</p>' if homepage else '',
            'body': ''}


class PilotV04JourneyTests(journey.OutcomeFixture):
    def setUp(self):
        super().setUp()
        self.offer = {'id': 'ns', 'name': 'NetSuite', 'kind': 'netsuite', 'status': 'approved',
                      'approved_by': 'seller', 'source_ids': ['reviewed-partner-source']}
        save_profile(self.store, {'partner': {'name': 'Partner', 'website': 'https://example.com',
            'offerings': [self.offer]}, 'tool_suggestions': ['monday', 'unknown-source']})

    def test_commands_expose_presets_checklist_and_resumable_research(self):
        presets = dispatch(self.store, 'style-presets', {})
        self.assertEqual(len(presets), 3)
        checklist = dispatch(self.store, 'connections-checklist', {
            'providers': ['unknown-source'], 'catalog': []})
        self.assertTrue(checklist[0]['next_step'])
        run = dispatch(self.store, 'research-start', {'subject_id': self.store.scope.partner_id,
            'website': 'https://example.com', 'purpose': 'partner', 'identity_confirmed': True})
        self.assertTrue(run.id)
        context = dispatch(self.store, 'research-context', {'subject_id': self.store.scope.partner_id})
        self.assertEqual(context['trust'], 'untrusted_external_data')
        self.assertFalse(context['coverage']['complete'])

    def test_each_company_generation_uses_own_research_and_reviewed_style(self):
        from aclad.research import start_research, crawl_batch
        account = self.store.get('account', 'a')
        self.store.put('account', 'a', dict(account.data, domain='example.com', name='Factory A'), account.revision)
        run = start_research(self.store, 'a', 'https://example.com', 'prospect', True)
        crawl_batch(self.store, run.id, fetcher=company_site)
        self.store.put('profile', 'writing-style', {'status': 'active', 'approved_by': 'seller',
            'sample_id': 'reviewed-sample', 'patterns': {'tone': 'consultivo', 'length': 'curto'}}, None)
        context = generation_context(self.store, 'campaign', 'a', 'contact-a')
        self.assertTrue(context['research']['account']['evidence'])
        self.assertEqual(context['reviewed_style']['patterns']['tone'], 'consultivo')
        self.assertEqual(context['personalization']['account_id'], 'a')
        other = generation_context(self.store, 'campaign', 'b', 'contact-b')
        self.assertEqual(other['research']['account']['evidence'], [])
        self.assertEqual(other['personalization']['status'], 'needs_research')
        self.assertEqual(other['portfolio']['offerings'][0]['id'], 'ns')

    def test_offer_change_after_draft_approval_blocks_external_action(self):
        from aclad.portfolio import portfolio_context
        message = {'account_id': 'a', 'contact_id': 'contact-a', 'sender_ref': asdict(self.sender),
            'to': ['buyer@example.com'], 'cc': [], 'bcc': [], 'subject': 'Operations',
            'body': 'A reviewed operations question.', 'attachments': [], 'source_ids': [],
            'plan_step_id': 'step-a-0', 'offering_ids': ['ns'],
            'portfolio_digest': portfolio_context(self.store)['digest']}
        draft = propose_draft(self.store, 'campaign', message)
        approve(self.store, draft.id, draft.revision, draft.digest, 'seller', journey.NOW)
        profile = deepcopy(self.store.get('profile', 'current').data)
        profile['partner']['offerings'][0]['source_ids'] = ['changed-reviewed-source']
        save_profile(self.store, profile)
        capability = Capability('email.create_draft', 'email.create_draft', 'mail', 'visible',
                                'authenticated', 'allowed', 'verified', 'free')
        with self.assertRaises(GateError) as caught:
            prepare_action(self.store, draft.id, capability, {}, journey.NOW)
        self.assertEqual(caught.exception.code, 'portfolio_context_changed')
        self.assertEqual(self.store.list('action'), [])

    def test_reviewed_style_is_recoverable_in_private_workspace_context(self):
        from pathlib import Path
        from aclad.workspace import initialize_workspace
        from aclad.store import Store
        from aclad.models import Scope
        info = initialize_workspace(Path(self.tmp.name)/'private-project', 'Seller')
        state = Store(Path(info['state_dir']), Scope(info['partner_id'], info['seller_id'], info['instance_id']))
        self.addCleanup(state.close)
        state.put('profile', 'writing-style', {'status': 'active', 'approved_by': 'seller',
            'patterns': {'tone': 'consultivo-curto'}, 'sample_id': 'reviewed-sample'}, None)
        text = (Path(info['root'])/'contexto/vendedor.md').read_text()
        self.assertIn('consultivo-curto', text)
        numeric = (Path(info['root'])/'contexto/resultados.md').read_text()
        self.assertNotIn('consultivo-curto', numeric)
