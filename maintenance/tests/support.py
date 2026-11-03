from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from aclad.models import Scope, ToolResult
from aclad.store import Store
SCOPE = Scope('partner-a', 'seller-a', 'instance-a')
NOW = '2026-10-22T12:00:00Z'

class StateTest(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state', SCOPE)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)

class FakeBridge:
    def __init__(self):
        self.calls = []
        self.results = {}
    def call(self, intent):
        self.calls.append(intent)
        if intent.action_id not in self.results:
            raise AssertionError('No external result fixture for action')
        result = self.results[intent.action_id]
        if isinstance(result, Exception):
            raise result
        return result


def complete_guided_workspace_setup(store):
    """Simulate a seller reviewing the real guided flow, without provider calls.

    Old result fixtures deliberately use bare seeded campaign/message records.
    Only project-local fixtures need the new setup prerequisite. Their existing
    business records stay intact; no review flags are written directly.
    """
    if store.workspace_root is None:
        return
    from aclad.connections import discover, record_probe
    from aclad.icps import propose_icp, approve_icp, bind_icp
    from aclad.onboarding import environment_readiness, save_answer
    from aclad.prospecting import open_campaign
    from aclad.setup_flow import BLOCKS, complete_block, setup_status, start_setup
    start_setup(store)
    profile = store.get('profile', 'current')
    settings = profile.data if profile else {}
    defaults = [('language', 'pt-BR'), ('partner.name', 'Parceiro sintético'),
                ('partner.website', 'https://partner.example.invalid'),
                ('seller.name', 'Vendedor sintético'), ('seller.territory', ['BR']),
                ('seller.size_bands', ['Todos']), ('seller.writing_style', 'Consultivo')]
    for field, value in defaults:
        current = settings
        for part in field.split('.'):
            current = current.get(part) if isinstance(current, dict) else None
        if not current:
            save_answer(store, field, value)
    if not settings.get('partner', {}).get('offerings'):
        save_answer(store, 'partner.offerings', [{'id': 'fixture-netsuite', 'name': 'NetSuite',
            'kind': 'netsuite', 'status': 'approved', 'approved_by': 'seller-fixture',
            'source_ids': ['synthetic-partner-review']}])
    save_answer(store, 'setup.prospecting_history', 'new')
    save_answer(store, 'schedule_preferences.mode', 'manual')
    save_answer(store, 'icp.criteria.industries', [])
    save_answer(store, 'icp.criteria.subindustries', [])
    environment_readiness(store, {'surface': 'codex-local', 'runtime_version': '3.13',
        'durable_state': True, 'state_accessible_to_executor': True,
        'identity_resolved': True, 'tools_verified': True, 'scheduler_verified': False})

    tools = []
    for row in store.list('connection'):
        cap = row.data.get('capability', {})
        tools.append({'operation': cap['operation'], 'tool_name': cap['tool_name'],
            'connection_id': row.data.get('native_connection_id', cap['connection_id']),
            'provider': row.data.get('provider', 'fixture-mail'),
            'account_identity': row.data.get('account_identity', 'seller-fixture'),
            'cost': cap.get('cost', 'free')})
        if not row.data.get('native_connection_id'):
            # Migrate raw synthetic inventory into discover's canonical IDs.
            # Production records are untouched; this is fixture construction.
            store.db.execute('DELETE FROM records WHERE kind=? AND id=?', ('connection', row.id))
    for operation in ('crm.read', 'accounts.search', 'people.search', 'email.read',
                      'email.create_draft', 'email.send'):
        if any(tool['operation'] == operation for tool in tools):
            continue
        family = 'crm' if operation.startswith('crm.') else 'data' if operation in {'accounts.search', 'people.search'} else 'mail'
        sibling = next((tool for tool in tools if tool['operation'].startswith('email.')), None) if family == 'mail' else None
        tools.append({'operation': operation,
            'tool_name': operation if sibling else 'fixture.' + operation,
            'connection_id': sibling['connection_id'] if sibling else 'fixture-' + family,
            'provider': sibling['provider'] if sibling else 'fixture-' + family,
            'account_identity': sibling['account_identity'] if sibling else 'seller-fixture', 'cost': 'free'})
    caps = discover(store, tools, True)
    for cap in caps:
        tool = next(tool for tool in tools if tool['operation'] == cap.operation
                    and tool['tool_name'] == cap.tool_name)
        # These are explicit saved synthetic provider observations, not live
        # writes/searches. Existing exact-operation proofs remain testable.
        record_probe(store, cap, {'connection_id': cap.connection_id, 'status_code': 200,
            'account_identity': tool['account_identity'], 'evidence': 'offline fixture provider response'})

    approved = [row for row in store.list('icp') if row.data.get('status') == 'active'
                and row.data.get('name') and row.data.get('approved_revision')]
    if not approved:
        proposal = propose_icp(store, [{'field': 'industry', 'operator': 'in',
            'value': ['Manufacturing'], 'basis': 'hypothesis'}], [], [], True,
            name='ICP de preparação sintética')
        approved = [approve_icp(store, proposal.id, proposal.revision, 'seller-fixture')]
    bound = [row for row in store.list('campaign') if any(
        row.data.get('icp_id') == icp.id
        and row.data.get('icp_revision') == icp.data['approved_revision']
        and row.data.get('icp_snapshot') == icp.data['approved_versions'][str(icp.data['approved_revision'])]
        for icp in approved)]
    if not bound:
        campaign = open_campaign(store, 'fixture-guided-campaign', 'Preparar teste sintético')
        icp = approved[0]
        bind_icp(store, campaign.id, icp.id, icp.data['approved_revision'])
    for block, _ in BLOCKS:
        complete_block(store, block, 'seller-fixture')
    status = setup_status(store)
    if not status['complete']:
        raise AssertionError('Guided fixture setup incomplete: ' + str(status))
