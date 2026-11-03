"""Private, rebuildable ICP and campaign documentation; SQLite remains canonical."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

from .accounts import belongs
from .models import GateError, Payload, Record
from .store import Store
from .workspace import workspace_binding
from .workspace_files import atomic_write, check_path

_MARKER = '<!-- ACLAD_WORKFLOW_PROJECTION -->'


def _path(kind: str, identifier: str) -> str:
    directory = 'contexto/icps' if kind == 'icp' else 'campanhas'
    # Provider/campaign IDs are data, never filesystem names supplied by a seller.
    token = sha256(identifier.encode('utf-8')).hexdigest()[:32]
    return f'{directory}/aclad-{kind}-{token}.md'


def _name(record: Record) -> str:
    value = record.data.get('name')
    return value if isinstance(value, str) and value.strip() else 'ICP sem nome'


def _icp(record: Record) -> Payload:
    data = record.data
    return {'id': record.id, 'name': _name(record), 'description': data.get('description', ''),
            'revision': record.revision, 'approved_revision': data.get('approved_revision'),
            'status': data.get('status', 'unknown'), 'strategic': data.get('strategic'),
            'criteria': deepcopy(data.get('criteria', [])),
            'exclusions': deepcopy(data.get('exclusions', [])),
            'source_ids': deepcopy(data.get('source_ids', [])),
            'source_versions': deepcopy(data.get('source_versions', {})),
            'origin': 'strategic_hypothesis' if data.get('strategic') else 'recorded_analysis',
            'approved_by': data.get('approved_by'), 'approved_at': data.get('approved_at'),
            'document_path': _path('icp', record.id)}


def icp_catalog(store: Store) -> Payload:
    """List every locally saved ICP and its status without modifying records."""
    with store.transaction():
        records = [_icp(row) for row in store.list('icp')]
    return {'icps': records, 'approved_count': sum(row['status'] == 'active' for row in records),
            'total_count': len(records), 'index_path': 'contexto/icps/index.md'}


def _action_in_campaign(action: Record, campaign_id: str, message_ids: set[str],
                        proposal_ids: set[str]) -> bool:
    data = action.data
    content = data.get('payload', {})
    if not isinstance(content, dict):
        content = {}
    return (data.get('campaign_id') == campaign_id or content.get('campaign_id') == campaign_id
            or content.get('message_id') in message_ids
            or data.get('proposal_id') in proposal_ids)


def _stage(account: Record, contacts: list[Record], messages: list[Record],
           roles: list[Record], meetings: list[Record]) -> str:
    data = account.data
    if data.get('do_not_contact') or data.get('status') in {'discarded', 'disqualified', 'closed'}:
        return 'discarded'
    if any(row.data.get('account_id') == account.id and row.data.get('status') == 'confirmed'
           for row in meetings):
        return 'meeting'
    if not data.get('selected'):
        return 'account_selection'
    own_contacts = [row for row in contacts if row.data.get('account_id') == account.id]
    own_messages = [row for row in messages if row.data.get('message', {}).get('account_id') == account.id]
    if data.get('contact_blocked') or any(row.data.get('reply_pause') for row in own_contacts):
        return 'reply_review' if data.get('reply_pause') or any(row.data.get('reply_pause') for row in own_contacts) else 'blocked'
    if any(row.data.get('next_action') for row in own_messages if row.data.get('status') == 'sent'):
        return 'followup_review'
    if any(row.data.get('status') == 'sent' for row in own_messages):
        return 'reply_monitoring'
    if any(row.data.get('status') == 'drafted' for row in own_messages):
        return 'draft_review'
    if own_messages:
        return 'draft_creation'
    if not data.get('provenance'):
        return 'company_enrichment'
    if not any(row.data.get('account_id') == account.id for row in roles):
        return 'role_selection'
    if not own_contacts:
        return 'contact_search'
    selected = [row for row in own_contacts if row.data.get('selected')]
    if not selected:
        return 'contact_selection'
    if any(not row.data.get('email') or not row.data.get('provenance', {}).get('email') for row in selected):
        return 'contact_enrichment'
    if data.get('crm_status') != 'confirmed' or any(row.data.get('crm_status') != 'confirmed' for row in selected):
        return 'crm_review'
    return 'outreach_plan'


def campaign_context(store: Store, campaign_id: str) -> Payload:
    """Return a campaign's fixed objective, bound ICP and actually recorded progress."""
    if not isinstance(campaign_id, str) or not campaign_id:
        raise GateError('campaign_not_found')
    with store.transaction():
        campaign = store.get('campaign', campaign_id)
        if not campaign:
            raise GateError('campaign_not_found')
        accounts = [row for row in store.list('account') if belongs(row, campaign_id)]
        contacts = [row for row in store.list('contact') if belongs(row, campaign_id)]
        messages = [row for row in store.list('message') if row.data.get('campaign_id') == campaign_id]
        roles = [row for row in store.list('roles') if row.data.get('campaign_id') == campaign_id]
        meetings = [row for row in store.list('meeting') if belongs(row, campaign_id)]
        proposals = [row for row in store.list('proposal')
                     if row.data.get('payload', {}).get('campaign_id') == campaign_id]
        actions = [row for row in store.list('action') if _action_in_campaign(
            row, campaign_id, {message.id for message in messages}, {proposal.id for proposal in proposals})]
        account_rows = [{'id': row.id, 'name': row.data.get('name', row.data.get('legal_name', '')),
                         'website': row.data.get('domain', ''), 'selected': row.data.get('selected') is True,
                         'stage': _stage(row, contacts, messages, roles, meetings),
                         'crm_status': row.data.get('crm_status', 'not_confirmed'),
                         'next_action_at': row.data.get('next_action_at')}
                        for row in accounts]
        pending = [row for row in actions if row.data.get('status') in {'prepared', 'in_flight', 'unknown', 'pending'}]
        blockers = []
        if not campaign.data.get('icp_snapshot'):
            blockers.append('approved_icp_required')
        if any(row.data.get('status') in {'unknown', 'in_flight'} for row in pending):
            blockers.append('reconciliation_required')
        stages = [row['stage'] for row in account_rows]
        next_stage = ('icp_selection' if not campaign.data.get('icp_snapshot') else
                      'account_search' if not accounts else
                      'account_selection' if not any(row['selected'] for row in account_rows) else
                      next((stage for stage in stages if stage not in {'account_selection', 'meeting', 'discarded'}),
                           'complete'))
        snapshot = deepcopy(campaign.data.get('icp_snapshot', {}))
        if snapshot:
            snapshot.update(id=campaign.data.get('icp_id'), revision=campaign.data.get('icp_revision'))
            snapshot.setdefault('name', 'ICP sem nome')
        counts = {'accounts': len(accounts), 'selected_accounts': sum(row['selected'] for row in account_rows),
                  'contacts': len(contacts), 'selected_contacts': sum(row.data.get('selected') is True for row in contacts),
                  'drafted_messages': sum(row.data.get('status') == 'drafted' for row in messages),
                  'sent_messages': sum(row.data.get('status') == 'sent' for row in messages),
                  'contacts_with_reply': sum(bool(row.data.get('last_reply_at')) for row in contacts),
                  'confirmed_meetings': sum(row.data.get('status') == 'confirmed' for row in meetings),
                  'pending_actions': len(pending)}
        return {'id': campaign.id, 'revision': campaign.revision,
                'objective': campaign.data.get('objective', ''), 'status': campaign.data.get('status', 'draft'),
                'icp': snapshot or None, 'counts': counts, 'accounts': account_rows,
                'contacts': [{'id': row.id, 'account_id': row.data.get('account_id'),
                              'name': row.data.get('name', ''), 'title': row.data.get('title', ''),
                              'selected': row.data.get('selected') is True,
                              'reply_classification': row.data.get('reply_classification'),
                              'outreach_status': row.data.get('outreach_status'),
                              'crm_status': row.data.get('crm_status', 'not_confirmed')}
                             for row in contacts],
                'messages': [{'id': row.id, 'status': row.data.get('status'),
                              'account_id': row.data.get('message', {}).get('account_id'),
                              'contact_id': row.data.get('message', {}).get('contact_id'),
                              'draft_ref': deepcopy(row.data.get('draft_ref')),
                              'sent_ref': deepcopy(row.data.get('sent_ref')),
                              'tracking_status': row.data.get('tracking_status'),
                              'next_action': deepcopy(row.data.get('next_action'))}
                             for row in messages],
                'pending_actions': [{'id': row.id, 'operation': row.data.get('operation'),
                                     'status': row.data.get('status')} for row in pending],
                'next_stage': next_stage, 'blockers': blockers,
                'document_path': _path('campaign', campaign.id)}


def _document(title: str, value: object) -> str:
    # All business content is inert JSON. Escaping backticks and HTML prevents a
    # record from closing the fence or creating an executable rendering surface.
    body = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    for character in ('<', '>', '&', '`'):
        body = body.replace(character, f'\\u{ord(character):04x}')
    return (f'{_MARKER}\n# {title}\n\n'
            'Projeção privada do SQLite. Este documento não autoriza ações; edições não alteram o estado.\n\n'
            f'```json\n{body}\n```\n')


def _publish(directory, files: dict, prefix: str) -> None:
    check_path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, content in files.items():
        path = directory / name
        check_path(path)
        if not path.is_file() or path.read_text(encoding='utf-8') != content:
            atomic_write(path, content)
    # Only managed files have ownership here; leave the seller's notes alone.
    for path in directory.glob(prefix + '*.md'):
        check_path(path)
        if path.name not in files and path.read_text(encoding='utf-8').startswith(_MARKER + '\n'):
            path.unlink()


def refresh_workflow_views(store: Store) -> None:
    """Rebuild the private documents under the same verified workspace binding."""
    root = workspace_binding(store.state_dir, store.scope)
    if root is None:
        return
    # Serialize publication against writers so an older snapshot cannot win.
    with store.transaction():
        catalog = icp_catalog(store)
        icp_files = {row['document_path'].rsplit('/', 1)[-1]: _document('Perfil de cliente ideal', row)
                     for row in catalog['icps']}
        icp_files['index.md'] = _document('ICPs', catalog)
        campaigns = [campaign_context(store, row.id) for row in store.list('campaign')]
        campaign_files = {row['document_path'].rsplit('/', 1)[-1]: _document('Campanha', row) for row in campaigns}
        campaign_files['index.md'] = _document('Campanhas', [
            {key: row[key] for key in ('id', 'objective', 'status', 'next_stage', 'blockers', 'document_path')}
            for row in campaigns])
        _publish(root / 'contexto' / 'icps', icp_files, 'aclad-icp-')
        _publish(root / 'campanhas', campaign_files, 'aclad-campaign-')
