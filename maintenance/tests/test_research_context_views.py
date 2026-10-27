from dataclasses import asdict

from aclad.commands import dispatch
from aclad.recovery import bootstrap, checkpoint
from tests.support import StateTest


class ResearchContextViewTests(StateTest):
    def test_resume_checkpoint_and_status_do_not_dump_the_collected_site(self):
        self.store.put('analysis', 'page', {'type': 'research_page', 'url': 'https://example.com/',
            'title': 'Example', 'text': 'PRIVATE_CORPUS_SENTINEL', 'body': 'RAW_BINARY_SENTINEL',
            'sha256': 'abc', 'collected_at': '2026-10-26T12:00:00Z', 'status': 'read'}, None)
        self.store.put('analysis', 'run', {'type': 'research_run', 'status': 'pending',
            'subject_id': 'a', 'queue': [{'url': 'https://example.com/next'}],
            'visited': ['https://example.com/'], 'page_ids': ['page']}, None)
        for result in (asdict(bootstrap(self.store)), asdict(checkpoint(self.store)),
                       dispatch(self.store, 'status', {})):
            with self.subTest(result_type=type(result)):
                self.assertNotIn('PRIVATE_CORPUS_SENTINEL', str(result))
                self.assertNotIn('RAW_BINARY_SENTINEL', str(result))
                run = next(record for record in result['records'] if record['id'] == 'run')
                self.assertEqual(run['data']['queued_count'], 1)
                self.assertNotIn('queue', run['data'])
        self.assertEqual(self.store.get('analysis', 'page').data['text'], 'PRIVATE_CORPUS_SENTINEL')
