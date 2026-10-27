from copy import deepcopy
from pathlib import Path
import unittest

from aclad.scheduling import schedule_request, record_schedule_result, next_runs
from tests import test_scheduling as baseline

NOW = baseline.NOW


def target_capability(store, schedule):
    target = {'mode': 'dedicated_chat', 'workspace_path': str(store.workspace_root or store.state_dir),
              'project_id': 'sales-project', 'chat_id': 'followup-chat', 'setup_chat_id': 'setup-chat'}
    return {'available': True, 'verified': True, 'tool_name': 'native.schedule',
            'executor_id': 'local-executor', 'mapping_verified': True, 'target': target,
            'native_configuration': {'schedule': deepcopy(schedule), 'target': deepcopy(target),
                                     'parameters': {'native_schedule': 'verified-adapter-parameters'}}}


def confirmed_result(request, native_id='native-42'):
    return {'status': 'succeeded', 'native_id': native_id, 'evidence': 'native-result-42',
            'effective_schedule': request['schedule'], 'target': request['dependencies']['target'],
            'confirmed_at': NOW, 'next_occurrences': next_runs(request['schedule'], NOW, 3)}


class ScheduleTargetTests(unittest.TestCase):
    tearDown = baseline.SchedulingTests.tearDown
    ready = baseline.SchedulingTests.ready

    def setUp(self):
        baseline.SchedulingTests.setUp(self)
        self.capability = target_capability(self.store, self.valid)

    def test_target_required_before_native_request(self):
        self.ready()
        cap = dict(self.capability)
        cap.pop('target')
        result = schedule_request(self.store, self.valid, cap)
        self.assertEqual(result['status'], 'target_required')
        self.assertFalse(self.store.list('schedule'))

    def test_wrong_workspace_and_setup_chat_rejected(self):
        self.ready()
        for change in ({'workspace_path': str(Path(self.tmp.name) / 'other')},
                       {'chat_id': 'setup-chat'}, {'project_id': ''}):
            with self.subTest(change=change):
                cap = deepcopy(self.capability)
                cap['target'].update(change)
                cap['native_configuration']['target'] = cap['target']
                self.assertEqual(schedule_request(self.store, self.valid, cap)['status'], 'target_required')

    def test_native_times_cannot_be_only_a_prompt_claim(self):
        self.ready()
        cap = deepcopy(self.capability)
        cap['native_configuration']['schedule']['times'] = ['01:00']
        self.assertEqual(schedule_request(self.store, self.valid, cap)['status'], 'mapping_required')
        self.assertFalse(self.store.list('schedule'))

    def test_confirmation_mismatch_keeps_reconciliation_pending(self):
        self.ready()
        request = schedule_request(self.store, self.valid, self.capability)
        response = confirmed_result(request)
        response['effective_schedule'] = {**self.valid, 'times': ['01:00']}
        record = record_schedule_result(self.store, request['request_id'], response)
        self.assertEqual(record.data['status'], 'awaiting_native_confirmation')
        self.assertTrue(record.data['reconciliation_required'])

    def test_native_next_occurrences_must_match_reviewed_schedule(self):
        self.ready()
        request = schedule_request(self.store, self.valid, self.capability)
        response = confirmed_result(request)
        response['next_occurrences'] = ['2026-10-22T01:00:00Z']
        self.assertEqual(record_schedule_result(self.store, request['request_id'], response).data['status'],
                         'awaiting_native_confirmation')

    def test_project_job_has_same_project_state_and_confirmed_destination(self):
        self.ready()
        cap = deepcopy(self.capability)
        cap['target'] = {'mode': 'project_job', 'workspace_path': str(self.store.state_dir),
                         'project_id': 'sales-project'}
        cap['native_configuration']['target'] = cap['target']
        request = schedule_request(self.store, self.valid, cap)
        self.assertEqual(request['dependencies']['target'], cap['target'])
        record = record_schedule_result(self.store, request['request_id'], confirmed_result(request))
        self.assertEqual(record.data['status'], 'active')
        self.assertEqual(record.data['target'], cap['target'])

    def test_legacy_schedule_without_target_needs_reconciliation(self):
        self.ready()
        self.store.put('schedule', 'review-schedule', {'native_id': 'old', 'status': 'active',
            'schedule': self.valid, 'tool_name': 'native.schedule', 'executor_id': 'local-executor'}, None)
        result = schedule_request(self.store, self.valid, self.capability)
        self.assertEqual(result['status'], 'target_reconciliation_required')
