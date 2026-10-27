from datetime import datetime, timedelta, timezone
import importlib
import tempfile
import unittest

from aclad.connections import discover, record_probe
from aclad.models import GateError, Scope, canonical
from aclad.store import Store


class StyleSamplingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, Scope('partner', 'seller', 'instance'))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('aclad.style'), 'bounded reviewed style API missing')
        return importlib.import_module('aclad.style')

    def connect(self, **overrides):
        cap = discover(self.store, [{'provider': 'outlook', 'connection_id': 'mail',
            'operation': 'email.read', 'tool_name': 'mail.read', 'account_identity': 'me@partner.example',
            'supports_sent': True, 'cost': 'free', **overrides}], True)[0]
        record_probe(self.store, cap, {'connection_id': cap.connection_id, 'status_code': 200,
            'account_identity': overrides.get('account_identity', 'me@partner.example'), 'evidence': 'identity-read'})
        return cap

    def message(self, **overrides):
        return {'id': 'sent-one', 'connection_id': 'mail', 'sender': 'me@partner.example',
            'folder': 'sent', 'recipients': ['buyer@prospect.example'], 'professional': True,
            'purpose': 'prospecting', 'internal': False, 'automated': False,
            'sent_at': (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            'body': 'Olá Ana, vi a expansão da empresa. Podemos conversar sobre NetSuite?', **overrides}

    def test_presets_offer_reviewable_tone_length_formality_and_examples(self):
        presets = self.api().style_presets()
        self.assertGreaterEqual(len(presets), 2)
        self.assertTrue(all({'tone', 'length', 'formality', 'example'} <= row.keys() for row in presets))

    def test_generic_2xx_cannot_authorize_sample_without_response_proven_mailbox_identity(self):
        api = self.api()
        cap = discover(self.store, [{'provider': 'outlook', 'connection_id': 'mail',
            'operation': 'email.read', 'tool_name': 'mail.read', 'account_identity': 'me@partner.example',
            'supports_sent': True, 'cost': 'free'}], True)[0]
        result = record_probe(self.store, cap, {'connection_id': cap.connection_id, 'status_code': 200,
            'evidence': 'generic-read-without-authenticated-identity'})
        self.assertEqual((result.auth, result.permission, result.verification),
                         ('unknown', 'unknown', 'declared'))
        with self.assertRaises(GateError):
            api.prepare_style_sample(self.store, 'mail', 'me@partner.example', True)

    def test_sample_requires_explicit_bounded_consent_and_verified_own_sent_capability(self):
        api = self.api()
        self.connect()
        for identity, approved, limit in [('me@partner.example', False, 10), ('other@partner.example', True, 10),
                                           ('me@partner.example', True, 11), ('me@partner.example', True, 0)]:
            with self.assertRaises(GateError):
                api.prepare_style_sample(self.store, 'mail', identity, approved, limit)
        self.assertEqual(self.store.list('analysis'), [])
        self.connect(supports_sent=False)
        with self.assertRaises(GateError):
            api.prepare_style_sample(self.store, 'mail', 'me@partner.example', True)

    def test_request_exposes_bounded_sent_query_and_records_summaries_without_mail_body(self):
        api = self.api()
        self.connect()
        request = api.prepare_style_sample(self.store, 'mail', 'me@partner.example', True, 3)
        self.assertEqual(request.data['query']['folder'], 'sent')
        self.assertEqual(request.data['query']['limit'], 3)
        self.assertEqual(request.data['query']['sender'], 'me@partner.example')
        sample = api.record_style_sample(self.store, request.id, [self.message()])
        self.assertEqual(sample.data['status'], 'needs_review')
        self.assertEqual(sample.data['sample_count'], 1)
        self.assertIn('patterns', sample.data)
        private = canonical([row.data for row in self.store.snapshot().records])
        self.assertNotIn('vi a expansão', private)
        self.assertNotIn('buyer@prospect.example', private)
        self.assertIsNone(self.store.get('profile', 'writing-style'))
        with self.assertRaises(GateError):
            api.approve_style(self.store, sample.id, sample.revision + 1, sample.data['patterns'], 'seller')
        approved = api.approve_style(self.store, sample.id, sample.revision, sample.data['patterns'], 'seller')
        self.assertEqual(approved.data['status'], 'active')
        self.assertEqual(self.store.get('profile', 'writing-style').data['sample_id'], sample.id)

    def test_internal_automated_irrelevant_unsent_and_old_messages_are_excluded(self):
        api = self.api()
        self.connect()
        request = api.prepare_style_sample(self.store, 'mail', 'me@partner.example', True)
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        messages = [self.message(), self.message(id='internal', recipients=['colleague@partner.example']),
                    self.message(id='automated', automated=True), self.message(id='private', professional=False),
                    self.message(id='inbox', folder='inbox'), self.message(id='old', sent_at=old),
                    self.message(id='irrelevant', purpose='support')]
        sample = api.record_style_sample(self.store, request.id, messages)
        self.assertEqual(sample.data['sample_count'], 1)
        self.assertEqual([row['id'] for row in sample.data['references']], ['sent-one'])

    def test_reconnect_mismatched_identity_or_connection_cannot_supply_sample(self):
        api = self.api()
        self.connect()
        request = api.prepare_style_sample(self.store, 'mail', 'me@partner.example', True)
        for changes in ({'sender': 'someone@partner.example'}, {'connection_id': 'other'}):
            with self.assertRaises(GateError):
                api.record_style_sample(self.store, request.id, [self.message(**changes)])
        self.connect(account_identity='other@partner.example')
        with self.assertRaises(GateError):
            api.record_style_sample(self.store, request.id, [self.message()])

    def test_request_excludes_messages_after_consent_and_expires_before_ingestion(self):
        api = self.api()
        self.connect()
        request = api.prepare_style_sample(self.store, 'mail', 'me@partner.example', True)
        until = datetime.fromisoformat(request.data['query']['until'])
        sample = api.record_style_sample(self.store, request.id, [
            self.message(id='boundary', sent_at=until.isoformat()),
            self.message(id='after', sent_at=(until + timedelta(seconds=1)).isoformat())])
        self.assertEqual(sample.data['sample_count'], 1)
        self.assertEqual([row['id'] for row in sample.data['references']], ['boundary'])
        request = api.prepare_style_sample(self.store, 'mail', 'me@partner.example', True)
        self.store.put('analysis', request.id, dict(request.data, expires_at='2000-01-01T00:00:00Z'), request.revision)
        with self.assertRaises(GateError):
            api.record_style_sample(self.store, request.id, [self.message()])

    def test_reviewed_signature_can_be_a_summary_without_retaining_signature_text(self):
        api = self.api()
        self.connect()
        request = api.prepare_style_sample(self.store, 'mail', 'me@partner.example', True)
        sample = api.record_style_sample(self.store, request.id, [self.message()])
        patterns = dict(sample.data['patterns'], signature='encerramento profissional breve')
        try:
            active = api.approve_style(self.store, sample.id, sample.revision, patterns, 'seller')
        except GateError:
            self.fail('reviewed signature summary must be supported')
        self.assertEqual(active.data['patterns']['signature'], 'encerramento profissional breve')

    def test_empty_or_oversized_sample_cannot_be_activated_and_request_is_single_use(self):
        api = self.api()
        self.connect()
        request = api.prepare_style_sample(self.store, 'mail', 'me@partner.example', True, 1)
        with self.assertRaises(GateError):
            api.record_style_sample(self.store, request.id, [self.message(), self.message(id='two')])
        sample = api.record_style_sample(self.store, request.id, [])
        with self.assertRaises(GateError):
            api.approve_style(self.store, sample.id, sample.revision, {'tone': 'friendly'}, 'seller')
        with self.assertRaises(GateError):
            api.record_style_sample(self.store, request.id, [self.message()])


if __name__ == '__main__':
    unittest.main()
