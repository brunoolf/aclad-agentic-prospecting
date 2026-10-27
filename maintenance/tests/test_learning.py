"""Learning must never turn unconfirmed behavior or account facts into policy."""
import json
import tempfile
import unittest
from pathlib import Path

from aclad.learning import capture_correction, relevant_rules, revoke_rule
from aclad.models import GateError, Scope
from aclad.store import Store


SCOPE = Scope('partner-a', 'seller-a', 'instance-a')


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / 'state'
        self.store = Store(self.directory, SCOPE)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def capture(self, before='Long introduction', after='Keep introductions short',
                scope_kind='personal:email', explicit=True, evidence_id='edit-1'):
        return capture_correction(self.store, before, after, scope_kind, explicit, evidence_id)

    def test_explicit_personal_preference_survives_reopening(self):
        rule = self.capture()
        self.assertEqual(rule.data['status'], 'active')
        self.store.close()
        self.store = Store(self.directory, SCOPE)
        self.assertEqual([r.id for r in relevant_rules(self.store, 'personal:email')], [rule.id])

    def test_inferred_rule_never_guides_generation(self):
        rule = self.capture(explicit=False)
        self.assertEqual(rule.data['status'], 'candidate')
        self.assertEqual(relevant_rules(self.store, 'personal:email'), [])

    def test_account_fact_and_product_inference_never_become_personal_rules(self):
        account = self.capture('Uses ERP A', 'Uses ERP B', 'account:company-a', True)
        product = self.capture('Product A', 'Product B', 'partner:product', True, 'edit-2')
        self.assertEqual(account.data['status'], 'candidate')
        self.assertEqual(product.data['status'], 'candidate')
        self.assertEqual(relevant_rules(self.store, 'personal:all'), [])
        self.assertEqual(relevant_rules(self.store, 'personal:email'), [])

    def test_all_personal_rules_apply_to_email_but_email_rules_do_not_leak(self):
        shared = self.capture(scope_kind='personal:all')
        email = self.capture(after='Use plain subjects', evidence_id='edit-2')
        self.assertEqual({r.id for r in relevant_rules(self.store, 'personal:email')}, {shared.id, email.id})
        self.assertEqual([r.id for r in relevant_rules(self.store, 'personal:briefing')], [shared.id])
        self.assertEqual(relevant_rules(self.store, 'account:company-a'), [])

    def test_revoke_removes_rule_and_requires_current_revision(self):
        rule = self.capture()
        revoked = revoke_rule(self.store, rule.id, rule.revision, 'Preference changed')
        self.assertEqual(revoked.data['status'], 'revoked')
        self.assertEqual(revoked.data['revocation_reason'], 'Preference changed')
        self.assertEqual(relevant_rules(self.store, 'personal:email'), [])
        with self.assertRaises(GateError):
            revoke_rule(self.store, rule.id, rule.revision, 'Stale request')

    def test_no_edit_does_not_produce_learning_or_event(self):
        for before, after in [('Same', 'Same'), (' Same ', 'Same'), ('', ''), ('Original', '')]:
            with self.subTest(before=before, after=after):
                with self.assertRaises(GateError):
                    self.capture(before, after)
        self.assertEqual(self.store.list('rule'), [])
        self.assertEqual(self.store.snapshot().event_sequence, 0)

    def test_duplicate_correction_keeps_each_evidence_and_can_be_confirmed(self):
        candidate = self.capture(explicit=False)
        active = self.capture(evidence_id='edit-2')
        self.assertEqual(candidate.id, active.id)
        self.assertEqual(active.data['status'], 'active')
        self.assertEqual([e['id'] for e in active.data['evidence']], ['edit-1', 'edit-2'])
        sequence = self.store.snapshot().event_sequence
        repeated = self.capture(evidence_id='edit-2')
        self.assertEqual(repeated.revision, active.revision)
        self.assertEqual(self.store.snapshot().event_sequence, sequence)

    def test_repeated_capture_does_not_silently_revive_revoked_rule(self):
        rule = self.capture()
        revoke_rule(self.store, rule.id, rule.revision, 'No longer wanted')
        repeated = self.capture(evidence_id='edit-2')
        self.assertEqual(repeated.data['status'], 'revoked')
        self.assertEqual(relevant_rules(self.store, 'personal:email'), [])

    def test_evidence_collision_is_rejected_without_overwriting_provenance(self):
        rule = self.capture()
        with self.assertRaises(GateError):
            self.capture(before='Different original')
        self.assertEqual(self.store.get('rule', rule.id).revision, rule.revision)

    def test_other_instance_has_no_preferences_and_cannot_open_this_store(self):
        self.capture()
        other_scope = Scope('partner-a', 'seller-a', 'instance-b')
        with self.assertRaises(GateError):
            Store(self.directory, other_scope)
        other = Store(Path(self.tmp.name) / 'other', other_scope)
        self.addCleanup(other.close)
        self.assertEqual(relevant_rules(other, 'personal:email'), [])

    def test_inputs_require_real_evidence_known_scope_and_short_safe_correction(self):
        for changes in [
            {'scope_kind': 'personal:anything'}, {'scope_kind': 'account:'},
            {'explicit': 'yes'}, {'evidence_id': ''}, {'after': 'x' * 2001},
            {'after': 'Use Authorization: Bearer very-secret-value'},
            {'before': 'access_token=very-secret-value'},
        ]:
            with self.subTest(changes=changes):
                with self.assertRaises(GateError):
                    self.capture(**changes)
        self.assertEqual(self.store.list('rule'), [])

    def test_checkpoint_records_references_and_short_reasons_not_a_chat_dump(self):
        rule = self.capture()
        snapshot = self.store.snapshot()
        persisted = next(r for r in snapshot.records if r.id == rule.id)
        self.assertEqual(persisted.data['evidence'][0]['id'], 'edit-1')
        self.assertLess(len(persisted.data['reason']), 200)
        self.assertNotIn('transcript', json.dumps(persisted.data))
        self.assertGreater(snapshot.event_sequence, 0)
