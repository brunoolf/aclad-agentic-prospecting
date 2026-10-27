"""Style-only reads reject raw result data before SQLite or event persistence."""
from aclad.approvals import create_proposal, prepare_action, record_result
from aclad.connections import discover, record_probe
from aclad.models import ExternalRef, GateError, ToolResult, canonical, now_utc
from aclad.style import prepare_style_sample, record_style_sample
from tests.support import StateTest


CORPUS = 'SYNTHETIC_PRIVATE_SENT_CORPUS_MUST_NEVER_REACH_GENERIC_RESULTS'


class StyleResultPrivacyGateTests(StateTest):
    def setUp(self):
        super().setUp()
        capability = discover(self.store, [{'provider': 'outlook', 'connection_id': 'mail',
            'tool_name': 'mail.read', 'operation': 'email.read', 'account_identity': 'me@example.invalid',
            'supports_sent': True, 'cost': 'free'}], True)[0]
        self.capability = record_probe(self.store, capability, {'connection_id': 'mail',
            'status_code': 200, 'account_identity': 'me@example.invalid', 'evidence': 'synthetic-probe'})
        self.request = prepare_style_sample(self.store, 'mail', 'me@example.invalid', True, 2)
        proposal = create_proposal(self.store, 'email.read', 'mail', [self.request.id],
            {'style_request_id': self.request.id, 'query': self.request.data['query']})
        self.intent = prepare_action(self.store, proposal.id, self.capability, {}, now_utc())

    def result(self, data, status='succeeded'):
        return ToolResult(self.intent.action_id, status,
            [ExternalRef('outlook', 'tenant', 'mail', 'opaque-native-style-result')], data)

    def summarize(self):
        return record_style_sample(self.store, self.request.id, [{
            'id': 'opaque-sent-message', 'connection_id': 'mail', 'sender': 'me@example.invalid',
            'folder': 'sent', 'recipients': ['buyer@other.invalid'], 'professional': True,
            'purpose': 'prospecting', 'internal': False, 'automated': False,
            'sent_at': self.request.data['query']['until'], 'body': CORPUS,
        }])

    def assert_no_corpus(self):
        self.assertNotIn(CORPUS, canonical([row.data for row in self.store.snapshot().records]))
        self.assertNotIn(CORPUS, canonical(self.store.events_since()))
        self.assertNotIn(CORPUS.encode(), self.store.path.read_bytes())

    def test_rejected_raw_result_can_be_replaced_by_same_action_sanitized_receipt(self):
        # A generic result used to persist the forbidden corpus in records AND events.
        before = self.store.snapshot()
        with self.assertRaises(GateError) as caught:
            record_result(self.store, self.result({'complete': True, 'messages': [{'body': CORPUS}]}))
        self.assertEqual(caught.exception.code, 'style_result_privacy_required')
        self.assertEqual(self.store.snapshot(), before)
        self.assert_no_corpus()
        self.assertEqual(self.store.get('action', self.intent.action_id).data['status'], 'in_flight')
        sample = self.summarize()
        receipt = record_result(self.store, self.result({'complete': True, 'sample_count': 1, 'excluded_count': 0}))
        self.assertEqual(receipt.data['status'], 'succeeded')
        self.assertEqual(len(self.store.list('action')), 1)
        self.assertEqual(sample.data['status'], 'needs_review')
        self.assertIsNone(self.store.get('profile', 'writing-style'))
        self.assert_no_corpus()

    def test_arbitrary_metadata_cannot_hide_corpus_even_in_failed_results(self):
        for status in ('succeeded', 'failed', 'unknown'):
            for field in ('messages', 'body', 'error', 'query', 'external_corpus'):
                with self.subTest(status=status, field=field):
                    before = self.store.snapshot()
                    with self.assertRaises(GateError) as caught:
                        record_result(self.store, self.result({'complete': False, field: CORPUS}, status))
                    self.assertEqual(caught.exception.code, 'style_result_privacy_required')
                    self.assertEqual(self.store.snapshot(), before)
                    self.assert_no_corpus()

    def test_receipt_counts_require_a_consumed_canonical_sample(self):
        for count in (0, 1):
            with self.subTest(count=count):
                with self.assertRaises(GateError) as caught:
                    record_result(self.store, self.result({'complete': True, 'sample_count': count}))
                self.assertEqual(caught.exception.code, 'style_sample_receipt_required')
        self.assertEqual(self.store.get('action', self.intent.action_id).data['status'], 'in_flight')

    def test_receipt_counts_and_types_cannot_invent_a_sample_size(self):
        self.summarize()
        for data, code in [
            ({'complete': 'true', 'sample_count': 1}, 'style_result_privacy_required'),
            ({'complete': True, 'sample_count': True}, 'style_result_privacy_required'),
            ({'complete': True, 'sample_count': '1'}, 'style_result_privacy_required'),
            ({'complete': True, 'sample_count': -1}, 'style_result_privacy_required'),
            ({'complete': True, 'sample_count': 11}, 'style_result_privacy_required'),
            ({'complete': True, 'sample_count': 1, 'excluded_count': -1}, 'style_result_privacy_required'),
            ({'complete': True, 'sample_count': 1, 'excluded_count': True}, 'style_result_privacy_required'),
            ({'complete': True, 'sample_count': 0}, 'style_sample_receipt_required'),
            ({'complete': True, 'sample_count': 1, 'excluded_count': 1}, 'style_sample_receipt_required'),
        ]:
            with self.subTest(data=data):
                before = self.store.snapshot()
                with self.assertRaises(GateError) as caught:
                    record_result(self.store, self.result(data))
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(self.store.snapshot(), before)

    def test_failed_read_can_record_safe_receipt_without_a_sample(self):
        receipt = record_result(self.store, self.result({'complete': False}, 'failed'))
        self.assertEqual(receipt.data['status'], 'failed')
        self.assertEqual(self.store.get('analysis', self.request.id).data['status'], 'prepared')
        self.assert_no_corpus()

    def test_empty_canonical_sample_has_a_truthful_zero_receipt(self):
        sample = record_style_sample(self.store, self.request.id, [])
        self.assertEqual(sample.data['sample_count'], 0)
        receipt = record_result(self.store, self.result({'complete': True, 'sample_count': 0}))
        self.assertEqual(receipt.data['status'], 'succeeded')
        self.assertEqual(receipt.data['external_refs'][0]['object_id'], 'opaque-native-style-result')
        self.assert_no_corpus()

    def test_unknown_read_reconciles_safe_receipt_after_summary_without_replaying_action(self):
        record_result(self.store, self.result({'complete': False}, 'unknown'))
        self.summarize()
        receipt = record_result(self.store, self.result({'complete': True, 'sample_count': 1, 'reconciled': True}))
        self.assertEqual(receipt.data['status'], 'succeeded')
        self.assertEqual(len(self.store.list('action')), 1)
        self.assert_no_corpus()

    def test_generic_reply_read_keeps_its_authorized_normalized_evidence(self):
        proposal = create_proposal(self.store, 'email.read', 'mail', ['campaign'], {'campaign_id': 'campaign'})
        intent = prepare_action(self.store, proposal.id, self.capability, {}, now_utc())
        data = {'complete': True, 'messages': [{'body': 'NORMAL_REPLY_EVIDENCE'}]}
        result = record_result(self.store, ToolResult(intent.action_id, 'succeeded', [], data))
        self.assertEqual(result.data['result'], data)
