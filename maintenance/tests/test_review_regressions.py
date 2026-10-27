"""Regression cases reproduced by the independent whole-branch review."""
from dataclasses import asdict
from pathlib import Path
import json
import os
import subprocess
import sys

from aclad.accounts import select_accounts
from aclad.approvals import approve, create_proposal, prepare_action
from aclad.connections import discover, record_probe
from aclad.crm import propose_crm, prepare_crm_item, record_crm_item, reconcile_crm
from aclad.models import Capability, ExternalRef, GateError, ToolResult
from aclad.onboarding import environment_readiness
from aclad.prospecting import record_candidates, select_contacts, prepare_prospecting
from tests.support import StateTest, NOW


class ReviewRegressions(StateTest):
    def setUp(self):
        super().setUp()
        self.owner = ExternalRef('crm', 'tenant', 'crm', 'seller')
        self.store.put('campaign', 'c', {'status': 'active'}, None)
        self.store.put('account', 'a', {'selected': True, 'campaign_id': 'c',
            'eligibility': 'eligible', 'crm_status': 'verified', 'owner_ref': asdict(self.owner)}, None)
        self.store.put('contact', 'p', {'selected': True, 'campaign_id': 'c', 'account_id': 'a'}, None)

    def capability(self, operation, connection='crm', cost='free'):
        cap = Capability(operation, 'native.' + operation, connection, 'visible',
                         'authenticated', 'allowed', 'verified', cost)
        old = self.store.get('connection', operation)
        self.store.put('connection', operation, {'capability': asdict(cap),
            'account_identity': 'seller'}, old.revision if old else None)
        return cap

    def approved(self, proposal):
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        return proposal

    def crm_unknown(self, update=False):
        ref = asdict(ExternalRef('crm', 'tenant', 'crm', 'remote-a')) if update else None
        if update:
            old = self.store.get('account', 'a')
            self.store.put('account', 'a', dict(old.data, crm_external_ref=ref), old.revision)
        change = {'local_id': 'a', 'entity': 'account', 'external_ref': ref,
            'external_revision': 'old' if update else 'new',
            'before': {'name': 'OLD'} if update else {}, 'after': {'name': 'NEW'},
            'links': {}, 'provenance': []}
        proposal = self.approved(propose_crm(self.store, 'c', [change], self.owner))
        cap = self.capability('crm.write')
        preflight = {'checked_at': NOW, 'connection_id': 'crm', 'external_revision': 'old' if update else 'new',
            'ownership_allowed': True, 'contact_allowed': True, 'opportunity_allowed': True}
        intent = prepare_crm_item(self.store, proposal.id, proposal.payload['changes'][0]['change_id'], cap, preflight, NOW)
        record_crm_item(self.store, ToolResult(intent.action_id, 'unknown', [], {}))
        return change, intent, cap, preflight

    def test_reconnection_shares_generation_across_operations_and_later_discovery(self):
        def tools(identity, operations):
            return [{'tool_name': 'native.' + op, 'operation': op, 'connection_id': 'mail',
                'provider': 'outlook', 'account_identity': identity, 'cost': 'free'} for op in operations]
        operations = ['email.create_draft', 'email.send', 'email.read']
        old = discover(self.store, tools('first', operations), True)
        new = discover(self.store, tools('second', operations[:2]), False)
        self.assertEqual(len({cap.connection_id for cap in new[:2]}), 1)
        self.assertNotEqual(new[0].connection_id, old[0].connection_id)
        later = discover(self.store, tools('second', operations), True)
        self.assertEqual({cap.connection_id for cap in later}, {new[0].connection_id})
        with self.assertRaises(GateError):
            record_probe(self.store, old[0], {'connection_id': 'mail', 'status_code': 200, 'evidence': 'stale'})

    def test_candidate_refresh_preserves_contact_and_account_state(self):
        for kind, identifier in [('contact', 'p'), ('account', 'a')]:
            with self.subTest(kind=kind):
                ref = asdict(ExternalRef('data', 'tenant', 'data', identifier))
                current = self.store.get(kind, identifier)
                protected = {'do_not_contact': True, 'contact_blocked': True, 'crm_status': 'confirmed',
                    'crm_external_ref': asdict(ExternalRef('crm', 'tenant', 'crm', 'remote-' + identifier)),
                    'email': 'original@example.invalid', 'provenance': {'email': {'source': 'approved-reveal'}},
                    'next_action_at': NOW, 'history': ['existing'], 'external_ref': ref}
                self.store.put(kind, identifier, dict(current.data, **protected), current.revision)
                candidate = {'id': identifier, 'name': 'Fresh name', 'source_at': NOW, 'external_ref': ref,
                    'selected': False, 'do_not_contact': False, 'email': 'different@example.invalid'}
                if kind == 'contact':
                    candidate['account_id'] = 'a'
                evidence_id = 'search-' + kind
                self.store.put('action', evidence_id, {'operation': 'people.search' if kind == 'contact' else 'accounts.search',
                    'status': 'succeeded', 'connection_id': 'data', 'result': {'candidates': [candidate]}}, None)
                row = record_candidates(self.store, 'c', kind, [candidate], evidence_id)[0]
                for key, value in protected.items():
                    self.assertEqual(row.data[key], value, key)
                self.assertEqual(row.data['name'], 'Fresh name')
                self.assertTrue(row.data['selected'])

    def test_candidate_local_id_cannot_replace_another_external_identity(self):
        old = self.store.get('contact', 'p')
        self.store.put('contact', 'p', dict(old.data, external_ref=asdict(ExternalRef('data', 't', 'data', 'original'))), old.revision)
        candidate = {'id': 'p', 'account_id': 'a', 'source_at': NOW,
            'external_ref': asdict(ExternalRef('data', 't', 'data', 'other'))}
        self.store.put('action', 'search', {'operation': 'people.search', 'status': 'succeeded',
            'connection_id': 'data', 'result': {'candidates': [candidate]}}, None)
        with self.assertRaises(GateError) as caught:
            record_candidates(self.store, 'c', 'contact', [candidate], 'search')
        self.assertEqual(caught.exception.code, 'candidate_identity_conflict')

    def test_account_deselection_cancels_dependent_reveal_and_gate_checks_parent(self):
        cap = self.capability('people.reveal_email', 'data', 'paid')
        limits = {'max_items': 1, 'max_credits': '1', 'cost_acknowledged': True}
        proposal = self.approved(prepare_prospecting(self.store, 'c', 'people.reveal_email', ['p'], cap, limits))
        select_accounts(self.store, 'c', [])
        self.assertFalse(self.store.get('contact', 'p').data['selected'])
        with self.assertRaises(GateError):
            prepare_action(self.store, proposal.id, cap, {}, NOW)
        # Even an independently constructed proposal cannot bypass the parent.
        contact = self.store.get('contact', 'p')
        self.store.put('contact', 'p', dict(contact.data, selected=True), contact.revision)
        another = self.approved(create_proposal(self.store, 'people.reveal_email', 'data', ['p'], {'limits': limits}))
        with self.assertRaises(GateError) as caught:
            prepare_action(self.store, another.id, cap, {}, NOW)
        self.assertEqual(caught.exception.code, 'selection_required')
        self.assertEqual(self.store.list('action'), [])

    def test_crm_unchanged_or_conflicting_observation_cannot_confirm_update(self):
        change, intent, _, _ = self.crm_unknown(update=True)
        base = {'complete': True, 'local_id': 'a', 'external_ref': change['external_ref'],
            'fields': {'name': 'OLD'}, 'external_revision': 'old', 'links': {},
            'owner_ref': asdict(self.owner), 'evidence': 'verified CRM read'}
        for observation in [base, dict(base, fields={'name': 'NEW'}),
                dict(base, fields={'name': 'NEW'}, external_revision='new', owner_ref={})]:
            result = reconcile_crm(self.store, intent.action_id, [observation])
            self.assertEqual(result.data['status'], 'unknown')
        result = reconcile_crm(self.store, intent.action_id,
            [dict(base, fields={'name': 'NEW'}, external_revision='new')])
        self.assertEqual(result.data['status'], 'succeeded')

    def test_crm_create_requires_unique_correlation_and_approved_fields(self):
        _, intent, _, _ = self.crm_unknown()
        base = {'complete': True, 'local_id': 'a',
            'external_ref': asdict(ExternalRef('crm', 'tenant', 'crm', 'created-a')),
            'fields': {'name': 'NEW'}, 'links': {}, 'owner_ref': asdict(self.owner), 'evidence': 'CRM read'}
        self.assertEqual(reconcile_crm(self.store, intent.action_id, [base]).data['status'], 'unknown')
        proven = dict(base, operation_id=intent.payload['operation_id'])
        self.assertEqual(reconcile_crm(self.store, intent.action_id, [proven, proven]).data['status'], 'unknown')
        self.assertEqual(reconcile_crm(self.store, intent.action_id, [proven]).data['status'], 'succeeded')

    def test_crm_reproposal_cannot_repeat_unknown_or_inflight_effect(self):
        change, first, cap, preflight = self.crm_unknown()
        for name in ('NEW', 'CHANGED'):
            proposal = self.approved(propose_crm(self.store, 'c', [dict(change, after={'name': name})], self.owner))
            with self.assertRaises(GateError) as caught:
                prepare_crm_item(self.store, proposal.id, proposal.payload['changes'][0]['change_id'], cap, preflight, NOW)
            self.assertEqual(caught.exception.code, 'reconciliation_required')
        self.assertEqual(len(self.store.list('action')), 1)

    def test_negative_environment_diagnosis_blocks_paid_and_external_intents(self):
        environment_readiness(self.store, {'surface': 'chatgpt-cloud', 'durable_state': False})
        cap = self.capability('people.reveal_email', 'data', 'paid')
        proposal = self.approved(create_proposal(self.store, cap.operation, 'data', ['p'],
            {'limits': {'max_items': 1, 'max_credits': '1', 'cost_acknowledged': True}}))
        with self.assertRaises(GateError) as caught:
            prepare_action(self.store, proposal.id, cap, {}, NOW)
        self.assertEqual(caught.exception.code, 'environment_unavailable')
        self.assertEqual(self.store.list('action'), [])

    def test_crm_overlapping_inflight_intent_blocks_even_a_different_change(self):
        change = {'local_id': 'a', 'entity': 'account', 'external_ref': None,
            'before': {}, 'after': {'name': 'NEW'}, 'links': {}, 'provenance': []}
        cap = self.capability('crm.write')
        preflight = {'connection_id': 'crm', 'checked_at': NOW, 'external_revision': 'new',
            'ownership_allowed': True, 'contact_allowed': True, 'opportunity_allowed': True}
        for index, name in enumerate(('NEW', 'DIFFERENT')):
            proposal = self.approved(propose_crm(self.store, 'c', [dict(change, after={'name': name})], self.owner))
            if index == 0:
                prepare_crm_item(self.store, proposal.id, proposal.payload['changes'][0]['change_id'], cap, preflight, NOW)
            else:
                with self.assertRaises(GateError) as caught:
                    prepare_crm_item(self.store, proposal.id, proposal.payload['changes'][0]['change_id'], cap, preflight, NOW)
                self.assertEqual(caught.exception.code, 'reconciliation_required')

    def test_crm_read_write_after_switch_rejects_old_approval_and_uses_new_owner(self):
        from aclad.approvals import record_result
        def inventory(identity):
            return [{'operation': op, 'tool_name': 'native.' + op, 'connection_id': 'crm',
                'provider': 'crm', 'account_identity': identity, 'cost': 'free'}
                for op in ('crm.read', 'crm.write')]
        old = discover(self.store, inventory('old-seller'), True)
        stale = self.approved(create_proposal(self.store, 'crm.write', 'crm', ['a'], {'external_revision': 'new'}))
        switched = discover(self.store, inventory('new-seller'), True)
        caps = {cap.operation: record_probe(self.store, cap, {'connection_id': cap.connection_id,
            'status_code': 200, 'account_identity': 'new-seller', 'evidence': 'synthetic reauthentication'}) for cap in switched}
        with self.assertRaises(GateError):
            prepare_action(self.store, stale.id, caps['crm.write'], {}, NOW)
        owner = ExternalRef('crm', 'new-tenant', caps['crm.read'].connection_id, 'new-seller')
        read = create_proposal(self.store, 'crm.read', owner.connection_id, ['a'], {})
        intent = prepare_action(self.store, read.id, caps['crm.read'], {}, NOW)
        record_result(self.store, ToolResult(intent.action_id, 'succeeded', [], {'complete': True, 'users': [asdict(owner)]}))
        change = {'local_id': 'a', 'entity': 'account', 'external_ref': None,
            'before': {}, 'after': {'name': 'Company'}, 'links': {}, 'provenance': []}
        proposal = self.approved(propose_crm(self.store, 'c', [change], owner))
        preflight = {'connection_id': owner.connection_id, 'checked_at': NOW, 'external_revision': 'new',
            'ownership_allowed': True, 'contact_allowed': True, 'opportunity_allowed': True}
        intent = prepare_crm_item(self.store, proposal.id, proposal.payload['changes'][0]['change_id'], caps['crm.write'], preflight, NOW)
        record_crm_item(self.store, ToolResult(intent.action_id, 'succeeded',
            [ExternalRef('crm', 'new-tenant', owner.connection_id, 'created')], {}))
        self.assertEqual(self.store.get('account', 'a').data['owner_ref'], asdict(owner))

    def test_draft_send_after_mailbox_switch(self):
        from aclad.messages import propose_draft, propose_send
        from aclad.delivery import record_delivery
        def inventory(identity):
            return [{'operation': op, 'tool_name': 'native.' + op, 'connection_id': 'mail',
                'provider': 'mail', 'account_identity': identity, 'cost': 'free'}
                for op in ('email.create_draft', 'email.send')]
        discover(self.store, inventory('old-seller'), True)
        caps = {cap.operation: record_probe(self.store, cap, {'connection_id': cap.connection_id,
            'status_code': 200, 'account_identity': 'new-seller', 'evidence': 'synthetic reauthentication'})
            for cap in discover(self.store, inventory('new-seller'), True)}
        connection = caps['email.send'].connection_id
        for kind, identifier in [('account', 'a'), ('contact', 'p')]:
            row = self.store.get(kind, identifier)
            self.store.put(kind, identifier, dict(row.data, crm_status='confirmed'), row.revision)
        self.store.put('outreach_plan', 'plan', {'campaign_id': 'c',
            'steps': [{'id': 'step', 'contact_id': 'p', 'channel': 'email'}]}, None)
        message = {'account_id': 'a', 'contact_id': 'p',
            'sender_ref': asdict(ExternalRef('mail', 'new-tenant', connection, 'new-seller')),
            'to': ['buyer@example.invalid'], 'cc': [], 'bcc': [], 'subject': 'Hello', 'body': 'Question',
            'attachments': [], 'source_ids': [], 'plan_step_id': 'step'}
        draft = self.approved(propose_draft(self.store, 'c', message))
        intent = prepare_action(self.store, draft.id, caps['email.create_draft'], {}, NOW)
        draft_ref = ExternalRef('mail', 'new-tenant', connection, 'draft-new')
        record_delivery(self.store, ToolResult(intent.action_id, 'succeeded', [draft_ref], {}), draft.id)
        preflight = {'connection_id': connection, 'checked_at': NOW, 'external_revision': 'rev1',
            'ownership_allowed': True, 'contact_allowed': True, 'opportunity_allowed': True,
            'sender_connection_id': connection, 'sender_object_id': 'new-seller', 'crm_confirmed': True,
            'recent_replies': False}
        send = self.approved(propose_send(self.store, draft_ref, dict(message, external_revision='rev1'), preflight))
        self.assertEqual(prepare_action(self.store, send.id, caps['email.send'], preflight, NOW).connection_id, connection)

    def test_retry_requires_correlated_definitive_no_effect_reconciliation(self):
        change, first, cap, preflight = self.crm_unknown()
        observed = {'complete': True, 'local_id': 'a', 'status': 'not_applied',
            'definitive_no_effect': True, 'operation_id': first.payload['operation_id'],
            'evidence': 'Provider operation status confirmed no effect'}
        result = reconcile_crm(self.store, first.action_id, [observed])
        self.assertEqual(result.data['status'], 'failed')
        proposal = self.approved(propose_crm(self.store, 'c', [change], self.owner))
        retry = prepare_crm_item(self.store, proposal.id, proposal.payload['changes'][0]['change_id'], cap, preflight, NOW)
        self.assertEqual(retry.payload['operation_id'], first.payload['operation_id'])
