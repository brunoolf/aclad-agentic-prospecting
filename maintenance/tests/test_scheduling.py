import tempfile
import unittest
from aclad.models import GateError, Scope
from aclad.store import Store
from aclad.onboarding import environment_readiness
from aclad.scheduling import validate_schedule, next_runs, schedule_request, record_schedule_result

NOW = '2026-10-22T10:00:00Z'


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, Scope('partner', 'seller', 'instance'))
        self.valid = {'weekdays': [1, 2, 3, 4, 5], 'times': ['09:00', '13:00', '17:00'],
            'timezone': 'America/Sao_Paulo', 'scope_ids': ['campaign'], 'active': True,
            'notification_policy': 'actionable_changes'}
        self.capability = {'available': True, 'verified': True, 'tool_name': 'native.schedule',
            'native_configuration': {}, 'mapping_verified': True,
            'executor_id': 'local-executor'}
        self.capability['target'] = {'mode': 'project_job', 'workspace_path': str(self.store.state_dir),
                                     'project_id': 'project'}
        self.capability['native_configuration'] = {'schedule': self.valid,
            'target': self.capability['target'], 'parameters': {'host_schedule': 'verified-parameters'}}

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def ready(self):
        environment_readiness(self.store, {'surface': 'codex-local', 'runtime_version': '3.13',
            'durable_state': True, 'identity_resolved': True, 'tools_verified': True,
            'scheduler_verified': True, 'state_accessible_to_executor': True})

    def test_weekdays_hours_and_timezone(self):
        self.assertEqual(next_runs(self.valid, NOW, 4), ['2026-10-22T12:00:00Z',
            '2026-10-22T16:00:00Z', '2026-10-22T20:00:00Z', '2026-10-23T12:00:00Z'])

    def test_dst_missing_advances_to_first_valid_instant_and_deduplicates(self):
        schedule = {**self.valid, 'weekdays': [7], 'times': ['02:30', '03:00'], 'timezone': 'America/New_York'}
        self.assertEqual(next_runs(schedule, '2026-03-08T00:00:00Z', 2),
                         ['2026-03-08T07:00:00Z', '2026-03-15T06:30:00Z'])

    def test_dst_repeated_runs_first_occurrence_once(self):
        schedule = {**self.valid, 'weekdays': [7], 'times': ['01:30'], 'timezone': 'America/New_York'}
        self.assertEqual(next_runs(schedule, '2026-11-01T00:00:00Z', 2),
                         ['2026-11-01T05:30:00Z', '2026-11-08T06:30:00Z'])

    def test_paused_schedule_no_runs(self):
        self.assertEqual(next_runs({**self.valid, 'active': False}, NOW, 3), [])

    def test_invalid_schedule_rejected(self):
        for change in ({'weekdays': []}, {'times': ['25:00']}, {'times': ['09:00', '09:00']},
                       {'timezone': 'Invented/Zone'}, {'scope_ids': []}, {'active': 'yes'},
                       {'notification_policy': 'always_send'}):
            with self.subTest(change=change), self.assertRaises(GateError):
                validate_schedule({**self.valid, **change})

    def test_missing_cloud_storage_or_scheduler_no_fake_task(self):
        environment_readiness(self.store, {'surface': 'chatgpt-cloud', 'durable_state': False})
        self.assertEqual(schedule_request(self.store, self.valid, self.capability)['status'], 'state_unavailable')
        self.ready()
        self.assertEqual(schedule_request(self.store, self.valid, {'available': False})['status'], 'scheduler_unavailable')
        self.assertEqual(self.store.list('schedule'), [])

    def test_native_result_must_be_confirmed_before_id_and_reused_for_pause(self):
        self.ready()
        request = schedule_request(self.store, self.valid, self.capability)
        self.assertEqual(request['operation'], 'create')
        self.assertNotIn('native_id', self.store.get('schedule', request['request_id']).data)
        with self.assertRaises(GateError):
            schedule_request(self.store, self.valid, self.capability)
        record_schedule_result(self.store, request['request_id'], {'status': 'succeeded', 'native_id': 'native-42',
            'evidence': 'scheduler-result-42', 'target': self.capability['target'],
            'effective_schedule': self.valid, 'confirmed_at': NOW,
            'next_occurrences': next_runs(self.valid, NOW, 3)})
        paused = {**self.valid, 'active': False}
        cap = {**self.capability, 'native_configuration': {
            **self.capability['native_configuration'], 'schedule': paused}}
        pause = schedule_request(self.store, paused, cap)
        self.assertEqual(pause['operation'], 'pause')
        self.assertEqual(pause['native_id'], 'native-42')

    def test_scheduler_mapping_required_no_unverified_parameters(self):
        self.ready()
        request = schedule_request(self.store, self.valid,
            {**self.capability, 'mapping_verified': False})
        self.assertEqual(request['status'], 'mapping_required')
        self.assertEqual(self.store.list('schedule'), [])


if __name__ == '__main__':
    unittest.main()
