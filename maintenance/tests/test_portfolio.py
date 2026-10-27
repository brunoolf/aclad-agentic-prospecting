"""Reviewed commercial offers are separate from factual CRM/research and learning."""
from copy import deepcopy

try:
    from aclad import portfolio
except ImportError:
    portfolio = None
from aclad.learning import capture_correction
from aclad.models import GateError
from aclad.outreach import briefing_context
from aclad.profiles import apply_import, save_profile, validate_profile
from aclad.prospecting import open_campaign
from tests.support import StateTest


class PortfolioTests(StateTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(portfolio, 'Commercial portfolio policy module is missing')

    def offer(self, id='ns', **changes):
        return dict({'id': id, 'name': 'NetSuite', 'kind': 'netsuite',
                     'status': 'approved', 'approved_by': 'seller', 'source_ids': ['partner-site']}, **changes)

    def save(self, offers):
        return save_profile(self.store, {'partner': {'name': 'Partner', 'website': 'https://partner.example', 'offerings': offers},
                          'tool_suggestions': ['HubSpot']})

    def test_approved_netsuite_and_linked_complement_are_active(self):
        offers = [self.offer(), self.offer('tax', name='Avalara', kind='complement', netsuite_relationship={'product': 'NetSuite', 'type': 'integration', 'description': 'Tax integration'}, independent_product=False)]
        self.save(offers)
        context = portfolio.portfolio_context(self.store)
        self.assertEqual([o['id'] for o in context['offerings']], ['ns', 'tax'])
        self.assertEqual(context['status'], 'reviewed')
        self.assertTrue(context['policy']['factual_competitor_research_allowed'])
        self.assertTrue(context['policy']['operational_crm_unrestricted'])

    def test_independent_erp_or_unlinked_complement_is_rejected(self):
        for offer in [self.offer(kind='independent', name='Other ERP'),
                      self.offer(kind='netsuite', name='Other ERP'),
                      self.offer(kind='complement', name='Other CRM'),
                      self.offer(kind='complement', name='Other ERP', netsuite_relationship='arbitrary relation'),
                      self.offer(kind='complement', name='Other ERP', netsuite_relationship={'product': 'Other ERP', 'type': 'extension'}, independent_product=False),
                      self.offer(kind='complement', name='Other ERP', netsuite_relationship={'product': 'NetSuite', 'type': 'integration'}, independent_product=True),
                      self.offer(status='approved', approved_by='')]:
            with self.subTest(offer=offer), self.assertRaises(GateError):
                self.save([offer])

    def test_named_independent_systems_cannot_masquerade_as_complements(self):
        for name in ('SAP', 'Dynamics', 'TOTVS', 'Omie', 'Odoo', 'HubSpot', 'Pipedrive'):
            with self.subTest(name=name), self.assertRaises(GateError):
                self.save([self.offer(name=name, kind='complement', independent_product=False,
                    netsuite_relationship={'product': 'NetSuite', 'type': 'extension'})])

    def test_legacy_profile_readable_but_unreviewed_products_never_active(self):
        legacy = {'partner': {'products': ['NetSuite', 'Other ERP'], 'services': ['Other CRM implementation']}}
        self.assertEqual(validate_profile(legacy), legacy)
        save_profile(self.store, legacy)
        context = portfolio.portfolio_context(self.store)
        self.assertEqual(context['offerings'], [])
        self.assertEqual(context['status'], 'review_required')

    def test_import_cannot_transfer_approval_and_invalid_import_cannot_activate(self):
        package = {'format': 'aclad-profile', 'version': 1, 'created_at': '2026-10-26T12:00:00Z',
                   'sections': {'partner': {'offerings': [self.offer()]}}}
        imported = apply_import(self.store, package, ['partner.offerings'])
        self.assertEqual(imported.data['partner']['offerings'][0]['status'], 'pending_review')
        self.assertEqual(portfolio.portfolio_context(self.store)['offerings'], [])
        bad = deepcopy(package)
        bad['sections']['partner']['offerings'][0].update(name='Other ERP', kind='independent')
        with self.assertRaises(GateError):
            apply_import(self.store, bad, ['partner.offerings'])

    def test_factual_competitor_and_operational_crm_are_kept_without_becoming_offers(self):
        self.save([self.offer()])
        open_campaign(self.store, 'c', 'NetSuite prospecting')
        fact = {'text': 'Company uses SAP and HubSpot', 'source': 'company-site', 'observed_at': '2026-10-26T12:00:00Z'}
        self.store.put('account', 'a', {'campaign_id': 'c', 'selected': True, 'facts': [fact]}, None)
        capture_correction(self.store, 'old', 'Suggest independent CRM implementation', 'partner:product', True, 'e1')
        context = briefing_context(self.store, 'c', 'a')
        self.assertEqual(context['facts'], [fact])
        self.assertEqual([o['id'] for o in context['portfolio']['offerings']], ['ns'])
        self.assertEqual(self.store.get('profile', 'current').data['tool_suggestions'], ['HubSpot'])

    def test_campaign_snapshot_detects_offer_change_before_further_generation(self):
        self.save([self.offer()])
        campaign = open_campaign(self.store, 'c', 'NetSuite prospecting')
        self.assertIn('portfolio_snapshot', campaign.data)
        self.store.put('account', 'a', {'campaign_id': 'c', 'selected': True}, None)
        self.save([self.offer(name='NetSuite', source_ids=['new-reviewed-source'])])
        with self.assertRaises(GateError) as caught:
            briefing_context(self.store, 'c', 'a')
        self.assertEqual(caught.exception.code, 'portfolio_context_changed')

    def test_personal_or_product_learning_never_expands_approved_portfolio(self):
        self.save([self.offer()])
        capture_correction(self.store, 'old', 'Offer Other ERP', 'personal:all', True, 'e1')
        capture_correction(self.store, 'old', 'Offer Other ERP', 'partner:product', True, 'e2')
        self.assertEqual([o['id'] for o in portfolio.portfolio_context(self.store)['offerings']], ['ns'])

    def draft_fixture(self):
        from dataclasses import asdict
        from aclad.models import Capability, ExternalRef
        self.save([self.offer()])
        open_campaign(self.store, 'c', 'NetSuite prospecting')
        self.store.put('account', 'a', {'campaign_id': 'c', 'selected': True, 'crm_status': 'confirmed'}, None)
        self.store.put('contact', 'p', {'campaign_id': 'c', 'account_id': 'a', 'selected': True, 'crm_status': 'confirmed'}, None)
        sender = ExternalRef('mail', 'tenant', 'mail', 'seller@example.com')
        for operation in ('email.create_draft', 'email.send'):
            cap = Capability(operation, operation, 'mail', 'visible', 'authenticated', 'allowed', 'verified', 'free')
            self.store.put('connection', operation, {'capability': asdict(cap), 'account_identity': sender.object_id}, None)
        self.store.put('outreach_plan', 'plan', {'campaign_id': 'c', 'steps': [{'id': 'step', 'contact_id': 'p', 'channel': 'email'}]}, None)
        return {'account_id': 'a', 'contact_id': 'p', 'sender_ref': asdict(sender), 'to': ['buyer@example.com'],
                'cc': [], 'bcc': [], 'subject': 'NetSuite', 'body': 'A question about your operations.',
                'attachments': [], 'source_ids': [], 'plan_step_id': 'step', 'offering_ids': ['ns']}

    def test_draft_proposal_carries_reviewed_portfolio_into_provider_payload(self):
        from aclad.messages import propose_draft
        message = self.draft_fixture()
        proposal = propose_draft(self.store, 'c', message)
        self.assertEqual(proposal.payload.get('portfolio'), portfolio.portfolio_context(self.store))
        self.assertEqual(proposal.payload['message']['offering_ids'], ['ns'])

    def test_draft_cannot_offer_unreviewed_independent_or_missing_offer(self):
        from aclad.messages import propose_draft
        message = self.draft_fixture()
        for ids, code in [(['other-erp'], 'offering_not_approved'), ([], 'message_offering_required')]:
            with self.subTest(ids=ids), self.assertRaises(GateError) as caught:
                propose_draft(self.store, 'c', dict(message, offering_ids=ids))
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.store.list('proposal'), [])

    def test_other_product_references_cannot_be_used_as_netsuite_proof(self):
        self.save([self.offer(authorized_references=['Reviewed NetSuite case'])])
        current = self.store.get('profile', 'current')
        save_profile(self.store, dict(current.data, partner=dict(current.data['partner'], authorized_references=['Other ERP case'])))
        open_campaign(self.store, 'c', 'NetSuite prospecting')
        self.store.put('account', 'a', {'campaign_id': 'c', 'selected': True,
            'proof': ['Reviewed NetSuite case', 'Other ERP case']}, None)
        self.assertEqual(briefing_context(self.store, 'c', 'a')['approved_proof'], ['Reviewed NetSuite case'])

    def test_legacy_migration_cannot_transfer_offer_authorizations(self):
        from aclad.profiles import migrate_legacy_profile
        migrated = migrate_legacy_profile(self.store, {'partner': {'offerings': [self.offer()]}})
        self.assertEqual(migrated.data['partner']['offerings'][0]['status'], 'pending_review')
        self.assertEqual(portfolio.portfolio_context(self.store)['offerings'], [])

    def test_canonical_independent_product_cannot_masquerade_as_complement(self):
        for name in ('SAP', 'HubSpot', 'Microsoft Dynamics 365'):
            with self.subTest(name=name), self.assertRaises(GateError):
                self.save([self.offer(name=name, kind='complement', independent_product=False,
                    netsuite_relationship={'product': 'NetSuite', 'type': 'integration'})])

    def test_real_legacy_partner_requires_review_before_new_draft_offers(self):
        save_profile(self.store, {'partner': {'name': 'Partner', 'products': ['NetSuite', 'Other ERP']}})
        open_campaign(self.store, 'legacy', 'Legacy target')
        with self.assertRaises(GateError) as caught:
            portfolio.validate_message_portfolio(self.store, 'legacy', {})
        self.assertEqual(caught.exception.code, 'portfolio_review_required')
