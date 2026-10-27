"""Transition regressions from the 0.4 whole-change review (synthetic adapters only)."""
from contextlib import redirect_stdout
from io import StringIO
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from aclad.commands import dispatch
from aclad.models import GateError
from aclad.recovery import bootstrap, checkpoint
from aclad.research import record_research_evidence
from tests.support import StateTest
from tests.test_research import Site, SITE
from tests import test_scheduling as scheduling_baseline
NOW = scheduling_baseline.NOW
from tests.test_schedule_targets import target_capability, confirmed_result
from tests import test_portfolio as portfolio_baseline


def cli(store, command, data):
    """Exercise the shipped JSON/argparse boundary with a second SQLite handle."""
    from aclad.__main__ import main
    output = StringIO()
    with patch('sys.stdin', StringIO(json.dumps(data))), redirect_stdout(output):
        status = main(['--state-dir', str(store.state_dir), '--partner-id', store.scope.partner_id,
            '--seller-id', store.scope.seller_id, '--instance-id', store.scope.instance_id, command])
    return status, json.loads(output.getvalue())


class ConnectionTransitionTests(StateTest):
    def invalidate(self, identity):
        tool = {'provider': 'outlook', 'connection_id': 'native-mail', 'operation': 'email.read',
                'tool_name': 'native.read', 'account_identity': 'seller@example.com', 'cost': 'free',
                'supports_sent': True}
        cap = dispatch(self.store, 'connections-discover', {'visible_tools': [tool], 'visibility_complete': True})[0]
        response = {'connection_id': cap.connection_id, 'status_code': 200,
                    'account_identity': 'seller@example.com', 'evidence': 'read-1'}
        dispatch(self.store, 'connections-record-probe', {'capability': asdict(cap), 'response': response})
        catalog = [{'provider': 'outlook', 'operations': ['email.read']}]
        self.assertEqual(dispatch(self.store, 'connections-checklist', {'providers': ['outlook'], 'catalog': catalog})[0]['status'], 'ready')
        status, result = cli(self.store, 'connections-record-probe', {'capability': asdict(cap),
            'response': dict(response, account_identity=identity, evidence='read-2')})
        self.assertEqual(status, 2)
        self.assertEqual(result['error']['code'], 'connection_mismatch')
        row = dispatch(self.store, 'connections-checklist', {'providers': ['outlook'], 'catalog': catalog})[0]
        self.assertFalse(row['authenticated'])
        self.assertNotEqual(row['status'], 'ready')
        saved = self.store.list('connection')[0]
        self.assertEqual(saved.data['probe']['diagnostic'], 'connection_mismatch')
        self.assertEqual(saved.data['probe']['account_identity'], identity)
        with self.assertRaises(GateError) as caught:
            dispatch(self.store, 'style-sample-prepare', {'connection_id': cap.connection_id,
                'identity': 'seller@example.com', 'approved': True})
        self.assertEqual(caught.exception.code, 'style_sent_access_required')
        dispatch(self.store, 'connections-record-probe', {'capability': asdict(cap), 'response': response})
        self.assertEqual(dispatch(self.store, 'connections-checklist', {'providers': ['outlook'], 'catalog': catalog})[0]['status'], 'ready')

    def test_null_identity_revokes_previously_ready_connection(self):
        self.invalidate(None)

    def test_changed_identity_revokes_previously_ready_connection(self):
        self.invalidate('other@example.com')


class CorpusProjectionTests(StateTest):
    def test_real_host_ingestion_current_and_old_runs_is_bounded_in_every_recovery_view(self):
        self.store.put('account', 'a', {'selected': True, 'domain': 'example.com'}, None)
        runs, host_ids = [], []
        for stamp in ('2026-10-20T12:00:00Z', '2026-10-26T12:00:00Z'):
            with patch('aclad.research.now_utc', return_value=stamp):
                run = dispatch(self.store, 'research-start', {'subject_id': 'a', 'website': SITE,
                    'purpose': 'prospect', 'identity_confirmed': True})
            runs.append(run.id)
            items = [{'url': SITE + f'/report-{i}.pdf', 'title': f'Report {i}',
                'text': 'HOST_CORPUS_SENTINEL-' + 'X' * 49000, 'source': 'host.document/result',
                'collected_at': stamp} for i in range(3)]
            with patch('aclad.research.public_url', side_effect=lambda url: url):
                evidence = record_research_evidence(self.store, run.id, items, 'document', stamp)
            host_ids.append(evidence.id)
        self.assertNotEqual(runs[0], runs[1])
        for result in (asdict(bootstrap(self.store)), asdict(checkpoint(self.store)), dispatch(self.store, 'status', {})):
            self.assertFalse('HOST_CORPUS_SENTINEL' in str(result), 'Host corpus leaked into public recovery')
            for host_id in host_ids:
                projection = next(r['data'] for r in result['records'] if r['id'] == host_id)
                self.assertNotIn('items', projection)
                self.assertEqual(projection['item_count'], 3)
                self.assertEqual(projection['content_access'], 'research-context')
            self.assertLess(len(str(result)), 18000)
        self.assertEqual(len(self.store.get('analysis', host_ids[0]).data['items'][0]['text']), 49021)
        context = dispatch(self.store, 'research-context', {'subject_id': 'a', 'limit': 1})
        self.assertIn('HOST_CORPUS_SENTINEL', context['evidence'][0]['excerpt'])
        self.assertEqual(len(context['evidence']), 1)


class LegacyScheduleLifecycleTests(StateTest):
    def setUp(self):
        super().setUp()
        self.valid = {'weekdays': [1, 2, 3, 4, 5], 'times': ['09:00'], 'timezone': 'America/Sao_Paulo',
            'scope_ids': ['campaign'], 'active': True, 'notification_policy': 'actionable_changes'}
        scheduling_baseline.SchedulingTests.ready(self)
        self.capability = target_capability(self.store, self.valid)
        self.store.put('campaign', 'campaign', {'name': 'Campaign'}, None)
        self.store.put('schedule', 'review-schedule', {'native_id': 'legacy-native-42', 'status': 'active',
            'schedule': self.valid, 'tool_name': 'native.schedule', 'executor_id': 'local-executor',
            'evidence': 'original-native-evidence'}, None)

    def assert_scheduled_blocked(self, code):
        with self.assertRaises(GateError) as caught:
            dispatch(self.store, 'review-start', {'origin': 'scheduled', 'now': NOW})
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.store.list('run'), [])

    def test_upgrade_blocks_entry_then_adopts_same_native_id_and_resumes(self):
        self.assert_scheduled_blocked('schedule_target_reconciliation_required')
        request = dispatch(self.store, 'schedule-request', {'schedule': self.valid, 'scheduler_capability': self.capability})
        self.assertEqual(request['status'], 'target_reconciliation_required')
        self.assertEqual(request['operation'], 'reconcile')
        self.assertEqual(request['native_id'], 'legacy-native-42')
        self.assertTrue(self.store.get('schedule', 'review-schedule').data['reconciliation_required'])
        self.assert_scheduled_blocked('schedule_not_active')
        wrong = confirmed_result(request, 'duplicate-id')
        with self.assertRaises(GateError) as caught:
            dispatch(self.store, 'schedule-record-result', {'request_id': 'review-schedule', 'response': wrong})
        self.assertEqual(caught.exception.code, 'scheduler_identity_changed')
        recorded = dispatch(self.store, 'schedule-record-result', {'request_id': 'review-schedule',
            'response': confirmed_result(request, 'legacy-native-42')})
        self.assertEqual(recorded.data['status'], 'active')
        self.assertEqual(recorded.data['native_id'], 'legacy-native-42')
        self.assertEqual(len(self.store.list('schedule')), 1)
        run = dispatch(self.store, 'review-start', {'origin': 'scheduled', 'now': NOW})
        self.assertEqual(run.data['status'], 'running')
        self.assertEqual(run.data['scope_ids'], ['campaign'])

    def test_upgrade_can_pause_by_existing_id_and_manual_review_still_works(self):
        paused = dict(self.valid, active=False)
        cap = target_capability(self.store, paused)
        request = dispatch(self.store, 'schedule-request', {'schedule': paused, 'scheduler_capability': cap})
        self.assertEqual(request['operation'], 'pause')
        self.assertEqual(request['native_id'], 'legacy-native-42')
        recorded = dispatch(self.store, 'schedule-record-result', {'request_id': 'review-schedule',
            'response': confirmed_result(request, 'legacy-native-42')})
        self.assertEqual(recorded.data['status'], 'paused')
        self.assert_scheduled_blocked('schedule_not_active')
        manual = dispatch(self.store, 'review-start', {'origin': 'manual', 'now': NOW})
        self.assertEqual(manual.data['status'], 'running')
        self.assertEqual(len(self.store.list('schedule')), 1)


class CoverageBudgetTests(StateTest):
    def test_shipped_commands_expand_and_resume_existing_537_page_site_without_refetch(self):
        self.store.put('account', 'a', {'selected': True, 'domain': 'example.com'}, None)
        run = dispatch(self.store, 'research-start', {'subject_id': 'a', 'website': SITE,
            'purpose': 'prospect', 'identity_confirmed': True})
        site = Site()
        site.pages = {'/robots.txt': ('text/plain', 'User-agent: *\nDisallow:'),
            '/sitemap.xml': ('application/xml', '<urlset>' + ''.join(f'<url><loc>{SITE}/p{i}</loc></url>' for i in range(536)) + '</urlset>'),
            '/': ('text/html', '<p>Company homepage content.</p>')}
        site.pages.update({f'/p{i}': ('text/html', f'<p>Company page content {i}</p>') for i in range(536)})
        with patch('aclad.research.fetch_public', side_effect=lambda url, **kwargs: site(url)):
            for _ in range(6):
                before = dispatch(self.store, 'research-crawl', {'research_id': run.id, 'max_pages': 100})
            self.assertEqual(before['coverage']['pages_read'], 498)
            self.assertEqual(before['coverage']['budget_deferred'], 39)
            self.assertFalse(before['coverage']['known_frontier_complete'])
            for invalid in (True, 499, 100001, '800'):
                with self.assertRaises(GateError) as caught:
                    dispatch(self.store, 'research-budget', {'research_id': run.id, 'max_urls': invalid})
                self.assertEqual(caught.exception.code, 'invalid_research_budget')
            status, expanded = cli(self.store, 'research-budget', {'research_id': run.id, 'max_urls': 800})
            self.assertEqual(status, 0)
            self.assertEqual(expanded['id'], run.id)
            self.assertEqual(expanded['data']['limits']['max_urls'], 800)
            after = dispatch(self.store, 'research-crawl', {'research_id': run.id, 'max_pages': 100})
        self.assertEqual(after['coverage']['pages_read'], 537)
        self.assertEqual(after['coverage']['pending'], 0)
        self.assertEqual(after['coverage']['budget_deferred'], 0)
        self.assertTrue(after['coverage']['known_frontier_complete'])
        self.assertNotIn('url_limit', after['coverage']['limitations'])
        self.assertEqual(len(site.calls), len(set(site.calls)))
        self.assertEqual(site.calls.count(SITE + '/sitemap.xml'), 1)
        self.assertEqual(len([r for r in self.store.list('analysis') if r.data.get('type') == 'research_run']), 1)


class MigrationApprovalTests(StateTest):
    offer = portfolio_baseline.PortfolioTests.offer
    save = portfolio_baseline.PortfolioTests.save
    draft_fixture = portfolio_baseline.PortfolioTests.draft_fixture

    def test_unrelated_migration_preserves_reviewed_offerings_campaign_and_approved_draft(self):
        from aclad.approvals import approve, prepare_action
        from aclad.messages import propose_draft
        from aclad.portfolio import portfolio_context
        from aclad.profiles import migrate_legacy_profile
        message = self.draft_fixture()
        proposal = propose_draft(self.store, 'c', message)
        approve(self.store, proposal.id, proposal.revision, proposal.digest, 'seller', NOW)
        before = deepcopy(portfolio_context(self.store))
        migrated = migrate_legacy_profile(self.store, {'language': 'pt-BR'})
        self.assertEqual(migrated.data['partner']['offerings'][0]['status'], 'approved')
        self.assertEqual(migrated.data['partner']['offerings'][0]['approved_by'], 'seller')
        self.assertEqual(portfolio_context(self.store), before)
        from aclad.models import Capability
        cap = Capability(**self.store.get('connection', 'email.create_draft').data['capability'])
        intent = prepare_action(self.store, proposal.id, cap, {}, NOW)
        self.assertEqual(intent.operation, 'email.create_draft')


class RobotsBoundTests(StateTest):
    def test_extreme_robots_rate_returns_json_safe_durable_block_without_page_fetch(self):
        self.store.put('account', 'a', {'selected': True, 'domain': 'example.com'}, None)
        run = dispatch(self.store, 'research-start', {'subject_id': 'a', 'website': SITE,
            'purpose': 'prospect', 'identity_confirmed': True})
        site = Site()
        site.pages['/robots.txt'] = ('text/plain', 'User-agent: *\nRequest-rate: 1/' + '9' * 1000)
        with patch('aclad.research.fetch_public', side_effect=lambda url, **kwargs: site(url)):
            status, result = cli(self.store, 'research-crawl', {'research_id': run.id})
            self.assertEqual(status, 0)
            again = dispatch(self.store, 'research-crawl', {'research_id': run.id})
        self.assertEqual(site.calls, [SITE + '/robots.txt'])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['errors'][0]['code'], 'invalid_robots_request_rate')
        self.assertTrue(result['errors'][0]['terminal'])
        self.assertFalse(result['coverage']['known_frontier_complete'])
        self.assertEqual(again['errors'], result['errors'])
        self.assertEqual(self.store.get('analysis', run.id).data['errors'], result['errors'])


class SetupCommandContractTests(StateTest):
    offer = portfolio_baseline.PortfolioTests.offer

    def test_documented_review_command_preserves_other_profile_fields_and_reaches_research_recovery(self):
        skill = (Path(__file__).resolve().parents[2] / 'plugins/aclad-prospecting/skills/setup/SKILL.md').read_text()
        self.assertFalse('profile-save' in skill, 'Setup instructs nonexistent command')
        self.assertIn('partner.offerings', skill)
        dispatch(self.store, 'setup-answer', {'field': 'partner.name', 'value': 'Partner'})
        dispatch(self.store, 'setup-answer', {'field': 'partner.website', 'value': SITE})
        dispatch(self.store, 'setup-answer', {'field': 'seller.name', 'value': 'Seller'})
        dispatch(self.store, 'setup-answer', {'field': 'tool_suggestions', 'value': ['HubSpot']})
        pending = self.offer(status='pending_review')
        pending.pop('approved_by')
        dispatch(self.store, 'setup-answer', {'field': 'partner.offerings', 'value': [pending]})
        dispatch(self.store, 'setup-answer', {'field': 'partner.offerings', 'value': [self.offer()]})
        profile = self.store.get('profile', 'current').data
        self.assertEqual(profile['seller']['name'], 'Seller')
        self.assertEqual(profile['tool_suggestions'], ['HubSpot'])
        self.assertEqual(profile['partner']['name'], 'Partner')
        self.assertEqual(profile['partner']['website'], SITE)
        self.assertEqual(profile['partner']['offerings'][0]['status'], 'approved')
        run = dispatch(self.store, 'research-start', {'subject_id': self.store.scope.partner_id,
            'website': SITE, 'purpose': 'partner', 'identity_confirmed': True})
        with patch('aclad.research.fetch_public', side_effect=lambda url, **kwargs: Site()(url)):
            dispatch(self.store, 'research-crawl', {'research_id': run.id})
        self.assertGreater(len(dispatch(self.store, 'research-context', {'subject_id': self.store.scope.partner_id})['evidence']), 0)
        self.assertEqual(next(r['data'] for r in dispatch(self.store, 'status', {})['records'] if r['id'] == 'current'), profile)
