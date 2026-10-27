"""Private observational learning from confirmed activity, with explicit rule review.

The observations are candidate evidence, never commercial authority or causal
claims. No body text, remote service, model execution or mailbox scan is needed.
"""
from __future__ import annotations

from hashlib import sha256

from .accounts import belongs
from .learning import _text
from .models import Event, GateError, Payload, Record, canonical, now_utc, payload, utc
from .store import Store
from .result_metrics import confirmed_sent_message

_CONTEXT_FIELDS = {'industry', 'size_band', 'persona', 'objective', 'approach', 'variant'}
_TASKS = {'briefing', 'email', 'persona', 'icp', 'cadence'}
_LIMITATIONS = [
    'Observational outcomes do not establish causality or an A/B test.',
    'Audience, timing and coverage can differ; retain the full denominator.',
    'Small samples and a single positive outcome do not prove general effectiveness.',
    'Multiple touches are attributed to the sequence, not arbitrarily to its last message.',
    'Unqueried silence is unobserved, not a verified negative outcome.',
]


def _hash(value: object) -> str:
    return sha256(canonical(value).encode('utf-8')).hexdigest()


def _context(value: Payload, *, rule: bool = False) -> Payload:
    clean = payload(value)
    allowed = _CONTEXT_FIELDS | ({'task'} if rule else {'source_ids'})
    if set(clean) - allowed:
        raise GateError('invalid_learning_context')
    for key, item in clean.items():
        if key == 'source_ids':
            if not isinstance(item, list) or any(not isinstance(source, str) or not source.strip() for source in item):
                raise GateError('invalid_learning_context')
        elif not isinstance(item, str) or not item.strip() or len(item) > 300:
            raise GateError('invalid_learning_context')
        else:
            clean[key] = _text(item, 300)
    if rule and (clean.get('task') not in _TASKS or not (set(clean) & _CONTEXT_FIELDS)):
        raise GateError('learning_scope_required')
    return clean


def validate_learning_context(store: Store, context: Payload, *, account_id: str | None = None,
                              contact_id: str | None = None, plan_step: Payload | None = None) -> Payload:
    """Validate context before it is frozen into a reviewed plan/message digest.

    Fact sources must contain the exact entity and field in a successful saved
    provider result. Stating an evidence ID alone does not prove a fact. Strategy
    descriptors are reviewed plan descriptors, not provider claims.
    """
    clean = _context(context)
    source_ids = clean.get('source_ids', [])
    facts = {'industry': (account_id, 'industry'), 'size_band': (account_id, 'size'),
             'persona': (contact_id, 'title')}
    for key, (entity_id, field) in facts.items():
        if key not in clean:
            continue
        proven = False
        for source_id in source_ids:
            source = store.get('action', source_id)
            if not source or source.data.get('status') != 'succeeded' or source.data.get('operation') not in {
                    'accounts.search', 'people.search', 'crm.read', 'companies.enrich'}:
                continue
            result = source.data.get('result', {})
            items = result.get('candidates', []) + result.get('items', [])
            for item in items:
                if isinstance(item, dict) and entity_id and item.get('id') == entity_id:
                    fields = item.get('fields', item)
                    if isinstance(fields, dict) and fields.get(field) == clean[key]:
                        proven = True
        if not proven:
            raise GateError('learning_context_evidence_required')
    if plan_step is not None:
        for key, field in (('objective', 'objective'), ('approach', 'angle')):
            if key in clean and clean[key] != plan_step.get(field):
                raise GateError('learning_context_plan_mismatch')
        variant = plan_step.get('learning_context', {}).get('variant')
        if 'variant' in clean and variant is not None and clean['variant'] != variant:
            raise GateError('learning_context_plan_mismatch')
    clean['source_ids'] = sorted(set(source_ids))
    return clean


def freeze_learning_basis(store: Store, campaign_id: str, message: Payload) -> Payload:
    """Freeze the reviewed plan version inside the proposal digest, before sending."""
    matching = [(plan, step) for plan in store.list('outreach_plan')
        if plan.data.get('campaign_id') == campaign_id for step in plan.data.get('steps', [])
        if step.get('id') == message.get('plan_step_id')
        and step.get('contact_id') == message.get('contact_id') and step.get('channel') == 'email']
    if len(matching) != 1:
        raise GateError('plan_step_required')
    plan, step = matching[0]
    if 'learning_context' in message:
        if message['learning_context'] != step.get('learning_context'):
            raise GateError('learning_context_mismatch')
        validate_learning_context(store, message['learning_context'], account_id=message.get('account_id'),
                                  contact_id=message.get('contact_id'), plan_step=step)
    campaign = store.get('campaign', campaign_id)
    if campaign is None:
        raise GateError('campaign_required')
    return payload({'campaign_id': campaign_id, 'plan_id': plan.id, 'plan_revision': plan.revision,
                    'icp_id': plan.data.get('icp_id', campaign.data.get('icp_id')),
                    'icp_revision': plan.data.get('icp_revision', campaign.data.get('icp_revision')),
                    'step': step})


def _confirmed_versions(store: Store) -> list[Payload]:
    versions = []
    seen = set()
    for message in store.list('message'):
        if not confirmed_sent_message(store, message):
            continue
        action = store.get('action', message.data.get('send_action_id', ''))
        if not action or action.data.get('operation') != 'email.send' or action.data.get('status') != 'succeeded':
            continue
        content = action.data.get('payload', {})
        current = content.get('message', {})
        refs = action.data.get('external_refs', [])
        campaign_id = content.get('campaign_id')
        campaign = store.get('campaign', campaign_id or '')
        account = store.get('account', current.get('account_id', ''))
        if (content.get('message_id') != message.id or current != message.data.get('current_message')
                or not refs or not campaign or not account or not belongs(account, campaign.id)):
            continue
        ref = refs[0]
        if not isinstance(ref, dict) or set(ref) != {'provider', 'tenant_id', 'connection_id', 'object_id'}:
            continue
        identity = canonical(ref)
        if identity in seen:
            continue
        basis = content.get('learning_basis')
        frozen_basis = isinstance(basis, dict)
        if isinstance(basis, dict):
            if (basis.get('campaign_id') != campaign.id or not isinstance(basis.get('plan_id'), str)
                    or type(basis.get('plan_revision')) is not int or basis['plan_revision'] < 1
                    or not isinstance(basis.get('step'), dict)):
                continue
            step = basis['step']
            if (step.get('id') != current.get('plan_step_id')
                    or step.get('contact_id') != current.get('contact_id') or step.get('channel') != 'email'):
                continue
        else:
            matching = [(plan, step) for plan in store.list('outreach_plan')
                if plan.data.get('campaign_id') == campaign.id for step in plan.data.get('steps', [])
                if step.get('id') == current.get('plan_step_id') and step.get('contact_id') == current.get('contact_id')]
            if len(matching) != 1:
                continue
            plan, step = matching[0]
            basis = {'plan_id': plan.id, 'plan_revision': plan.revision,
                     'icp_id': plan.data.get('icp_id', campaign.data.get('icp_id')),
                     'icp_revision': plan.data.get('icp_revision', campaign.data.get('icp_revision'))}
        # Explicit contextual claims must match the reviewed plan and approved
        # send payload. Missing claims may only recover frozen strategy below.
        raw = current.get('learning_context', {})
        if raw and raw != step.get('learning_context'):
            continue
        try:
            context = _context(raw)
            sent_at = message.data['sent_at']
            utc(sent_at)
        except (GateError, KeyError):
            continue
        if not raw and frozen_basis:
            # These strategy descriptors were part of the exact send approval.
            # A mutable current plan cannot supply missing historical context;
            # nor can provider facts or a variant absent from the sent message.
            for key, field in (('objective', 'objective'), ('approach', 'angle')):
                try:
                    context.update(_context({key: step.get(field)}))
                except GateError:
                    # An unrepresentable descriptor remains unknown without
                    # removing this confirmed exposure from its denominator.
                    pass
        seen.add(identity)
        versions.append({'campaign_id': campaign.id, 'plan_id': basis['plan_id'],
            'plan_revision': basis['plan_revision'], 'icp_id': basis.get('icp_id'),
            'icp_revision': basis.get('icp_revision'),
            'context': {key: value for key, value in context.items() if key != 'source_ids'},
            'account_id': account.id,
            'account_key': canonical(account.data['external_ref']) if isinstance(account.data.get('external_ref'), dict) else 'local:' + account.id,
            'message_id': message.id, 'action_id': action.id,
            'message_digest': _hash(current), 'source_ids': context.get('source_ids', []),
            'sent_at': sent_at, 'external_ref': ref,
            'conversation_ref': message.data.get('conversation_ref'),
            'personal_rule_ids': current.get('personal_rule_ids', [])})
    return sorted(versions, key=lambda item: (item['sent_at'], item['message_id']))


def _reply_evidence(store: Store) -> list[Payload]:
    """Deduplicate external human messages across revision observations."""
    found = {}
    for observed in store.events_since():
        if observed['kind'] != 'reply.observed':
            continue
        event = observed['data']
        if not isinstance(event, dict) or event.get('kind') != 'email':
            continue
        ref = event.get('external_ref')
        if not isinstance(ref, dict):
            continue
        key = canonical(ref)
        old = found.get(key)
        revision = str(event.get('source_revision', ''))
        old_revision = str(old.get('source_revision', '')) if old else ''
        if old:
            if revision.isdecimal() and old_revision.isdecimal():
                if int(revision) < int(old_revision):
                    continue
            elif revision != old_revision:
                found[key] = dict(event, classification='needs_review')
                continue
        found[key] = event
    return [event for event in found.values() if event.get('classification') in
            {'interested', 'question', 'not_now', 'no', 'do_not_contact', 'meeting'}]


def _covered_at(store: Store, campaign_id: str, conversation: Payload | None, sent_at: str) -> str | None:
    if not isinstance(conversation, dict):
        return None
    checked = []
    for cursor in store.list('cursor'):
        data = cursor.data
        if (data.get('connection_id') != conversation.get('connection_id')
                or data.get('source') not in {'email', 'mail', 'replies', 'inbox'}
                or data.get('scope_ids') is not None and campaign_id not in data['scope_ids']):
            continue
        try:
            if utc(data['last_success']) >= utc(sent_at):
                checked.append(data['last_success'])
        except (GateError, KeyError):
            continue
    return max(checked, key=utc) if checked else None


def _meeting_evidence(store: Store, campaign_id: str, account_id: str) -> list[Payload]:
    # Calendar normalization owns proof validation; only that canonical record
    # type counts. Email text classified as "meeting" remains a reply only.
    return [row.data for row in store.list('meeting')
            if belongs(row, campaign_id) and row.data.get('account_id') == account_id
            and row.data.get('ever_confirmed') is True]


def _outcome_observation_data(store: Store) -> dict[str, Payload]:
    """Compute the complete local sample without writing projections."""
    # Establish the complete account sequence before splitting any strategy
    # cells. Otherwise one reply would make each preceding variant appear
    # independently successful while discarding the other preceding touches.
    sequences = {}
    for version in _confirmed_versions(store):
        key = canonical([version['campaign_id'], version['icp_id'],
                         version['icp_revision'], version['account_key']])
        sequences.setdefault(key, []).append(version)
    groups = {}
    for versions in sequences.values():
        first = versions[0]
        common = {key: value for key, value in first['context'].items()
                  if all(v['context'].get(key) == value for v in versions)}
        plans = sorted({v['plan_id'] for v in versions})
        plan_versions = sorted({canonical([v['plan_id'], v['plan_revision']]) for v in versions})
        group = {'campaign_id': first['campaign_id'], 'icp_id': first['icp_id'],
                 'icp_revision': first['icp_revision'], 'context': common,
                 'plan_id': plans[0] if len(plans) == 1 else None,
                 'plan_ids': plans, 'plan_revision': first['plan_revision'] if len(plan_versions) == 1 else None}
        identifier = 'outcome-' + _hash(group)
        if identifier not in groups:
            groups[identifier] = (group, {})
        groups[identifier][1][first['account_key']] = {
            'account_id': first['account_id'], 'account_ids': sorted({v['account_id'] for v in versions}),
            'ambiguous_attribution': len({canonical(v['context']) for v in versions}) > 1 or len(plan_versions) > 1,
            'versions': [{key: value for key, value in v.items() if key != 'account_key'} for v in versions]}
    replies = _reply_evidence(store)
    output = {}
    for identifier, (group, by_account) in sorted(groups.items()):
        exposures = []
        for _, exposure in sorted(by_account.items()):
            versions = exposure['versions']
            first_sent = min((version['sent_at'] for version in versions), key=utc)
            latest_sent = max((version['sent_at'] for version in versions), key=utc)
            conversations = [version.get('conversation_ref') for version in versions if version.get('conversation_ref')]
            responses = [event for event in replies if event.get('account_id') in exposure['account_ids']
                and event.get('conversation_ref') in conversations and utc(event['occurred_at']) >= utc(first_sent)]
            checked = [_covered_at(store, group['campaign_id'], conversation, latest_sent) for conversation in conversations]
            exposure['reply_refs'] = [event['external_ref'] for event in responses]
            exposure['meetings'] = [meeting for account_id in exposure['account_ids']
                                   for meeting in _meeting_evidence(store, group['campaign_id'], account_id)]
            exposure['checked_at'] = max((value for value in checked if value), default=None, key=utc)
            exposure['outcome'] = 'human_reply' if responses else 'checked_without_reply' if exposure['checked_at'] else 'unobserved'
            exposures.append(exposure)
        data = dict(group, type='outcome_observation', status='candidate', attribution='sequence',
            exposure_count=len(exposures), replied_account_count=sum(bool(e['reply_refs']) for e in exposures),
            meeting_account_count=sum(bool(e['meetings']) for e in exposures),
            checked_without_reply=sum(e['outcome'] == 'checked_without_reply' for e in exposures),
            unobserved_count=sum(e['outcome'] == 'unobserved' for e in exposures), exposures=exposures,
            window={'first_sent_at': min((v['sent_at'] for e in exposures for v in e['versions']), key=utc),
                    'last_sent_at': max((v['sent_at'] for e in exposures for v in e['versions']), key=utc),
                    'last_checked_at': max((e['checked_at'] for e in exposures if e['checked_at']), default=None, key=utc)},
            limitations=list(_LIMITATIONS))
        output[identifier] = data
    return output


def refresh_outcome_observations(store: Store) -> list[Record]:
    """Refresh stable private cohort observations without connectors or a model."""
    with store.transaction():
        groups = _outcome_observation_data(store)
        output = []
        for identifier, data in groups.items():
            old = store.get('analysis', identifier)
            row = old if old and old.data == data else store.put('analysis', identifier, data, old.revision if old else None)
            output.append(row)
        superseded = []
        for prior in store.list('analysis'):
            if prior.data.get('type') != 'outcome_observation' or prior.id in groups:
                continue
            replacements = sorted(row.id for row in output if row.data['campaign_id'] == prior.data.get('campaign_id')
                and row.data['icp_id'] == prior.data.get('icp_id') and row.data['icp_revision'] == prior.data.get('icp_revision'))
            data = dict(prior.data, status='superseded', superseded_by=replacements)
            if prior.data != data:
                prior = store.put('analysis', prior.id, data, prior.revision)
            superseded.append(prior)
        _suspend_changed_rules(store, [*output, *superseded])
        return output


def outcome_context(store: Store, campaign_id: str, task: str = 'email') -> Payload:
    """Read complete persisted cohorts, including after outreach pauses or DNC.

    This never bootstraps actions, refreshes projections, or authorizes contact.
    A changed local sample requires normal resume/projection before proposing.
    """
    if task not in _TASKS:
        raise GateError('invalid_rule_scope')
    if store.get('campaign', campaign_id) is None:
        raise GateError('campaign_required')
    expected = {key: data for key, data in _outcome_observation_data(store).items()
                if data['campaign_id'] == campaign_id}
    rows = [row for row in store.list('analysis')
            if row.data.get('type') == 'outcome_observation'
            and row.data.get('campaign_id') == campaign_id
            and row.data.get('status') != 'superseded' and row.data.get('exposure_count', 0) > 0]
    current = {row.id: row.data for row in rows} == expected
    common = {key: value for key, value in rows[0].data.get('context', {}).items()
              if all(row.data.get('context', {}).get(key) == value for row in rows)} if rows else {}
    observations = []
    for row in rows:
        context = row.data.get('context', {})
        observations.append({
            'id': row.id, 'revision': row.revision, 'context': context,
            'evidence_ids': [row.id],
            'proposal_context': dict(context, task=task) if context and current else None,
            'sample': {'exposed': row.data['exposure_count'],
                       'replied': row.data['replied_account_count'],
                       'meetings': row.data['meeting_account_count'],
                       'checked_without_reply': row.data['checked_without_reply'],
                       'unobserved': row.data['unobserved_count']},
            'window': row.data['window'], 'attribution': row.data['attribution'],
            'limitations': row.data['limitations'],
        })
    return payload({'campaign_id': campaign_id, 'task': task,
                    'status': 'current' if current else 'refresh_required',
                    'proposal_context': dict(common, task=task) if common and current else None,
                    'evidence_ids': [row.id for row in rows],
                    'observations': observations, 'limitations': list(_LIMITATIONS)})


def _observations(store: Store, evidence_ids: list[str]) -> list[Record]:
    if not isinstance(evidence_ids, list) or not evidence_ids or any(not isinstance(item, str) or not item for item in evidence_ids):
        raise GateError('learning_evidence_required')
    pending, resolved, seen = list(evidence_ids), {}, set()
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            continue
        seen.add(identifier)
        row = store.get('analysis', identifier)
        if row is None or row.data.get('type') != 'outcome_observation' or row.data.get('exposure_count', 0) < 1:
            raise GateError('learning_evidence_required')
        if row.data.get('status') == 'superseded':
            replacements = row.data.get('superseded_by', [])
            if not replacements:
                raise GateError('learning_evidence_stale')
            pending.extend(replacements)
        else:
            resolved[row.id] = row
    rows = [resolved[key] for key in sorted(resolved)]
    return rows


def propose_outcome_rule(store: Store, context: Payload, instruction: str,
                         evidence_ids: list[str]) -> Record:
    """Prepare a scoped hypothesis, preserving rejected/revoked decisions."""
    clean = _context(context, rule=True)
    instruction = _text(instruction)
    with store.transaction():
        identifier = 'performance-' + _hash([clean, ' '.join(instruction.split())])
        old = store.get('rule', identifier)
        retained_ids = set(old.data.get('observation_revisions', {})) if old else set()
        observations = _observations(store, sorted(retained_ids | set(evidence_ids)))
        for observation in observations:
            if any(observation.data.get('context', {}).get(key) != value
                   for key, value in clean.items() if key != 'task'):
                raise GateError('learning_evidence_scope_mismatch')
        evidence = {row.id: row.revision for row in observations}
        if old and old.data.get('observation_revisions') == evidence:
            return old
        now = now_utc()
        data = dict(old.data) if old else {'scope_kind': 'performance', 'context': clean,
            'instruction': instruction, 'status': 'candidate', 'created_at': now,
            'history': [], 'limitations': list(_LIMITATIONS)}
        data.update(observation_revisions=evidence, updated_at=now,
            sample={'exposed': sum(row.data['exposure_count'] for row in observations),
                    'replied': sum(row.data['replied_account_count'] for row in observations),
                    'unobserved': sum(row.data['unobserved_count'] for row in observations)})
        if old and old.data.get('status') == 'active':
            data['status'] = 'needs_review'
            data['divergence'] = 'Evidence changed after approval; review the updated full sample.'
        return store.put('rule', identifier, data, old.revision if old else None)


def review_outcome_rule(store: Store, rule_id: str, revision: int,
                        decision: str, evidence_id: str) -> Record:
    """Apply an explicit seller decision to the exact local hypothesis version."""
    if decision not in {'approve', 'reject', 'revoke'}:
        raise GateError('invalid_learning_review')
    evidence_id = _text(evidence_id, 256)
    if type(revision) is not int or revision < 1:
        raise GateError('revision_conflict')
    with store.transaction():
        rule = store.get('rule', rule_id)
        if not rule or rule.data.get('scope_kind') != 'performance':
            raise GateError('rule_not_found')
        if rule.revision != revision:
            raise GateError('revision_conflict')
        if rule.data.get('status') == 'revoked' and decision == 'approve':
            raise GateError('rule_revoked')
        observations = _observations(store, list(rule.data.get('observation_revisions', {})))
        if decision == 'approve' and any(rule.data['observation_revisions'].get(row.id) != row.revision for row in observations):
            raise GateError('learning_evidence_stale')
        now = now_utc()
        entry = {'decision': decision, 'reviewed_revision': revision, 'evidence_id': evidence_id,
                 'reviewed_at': now, 'seller_id': store.scope.seller_id}
        data = dict(rule.data, status={'approve': 'active', 'reject': 'rejected', 'revoke': 'revoked'}[decision],
                    updated_at=now, history=[*rule.data.get('history', []), entry])
        result = store.put('rule', rule.id, data, revision)
        store.record_event(Event('review-' + _hash([rule.id, revision, decision, evidence_id]), rule.id,
                                 'outcome_rule_reviewed', now, entry))
        return result


def _suspend_changed_rules(store: Store, observations: list[Record]) -> None:
    revisions = {row.id: row.revision for row in observations}
    for rule in store.list('rule'):
        if rule.data.get('scope_kind') != 'performance':
            continue
        prior = rule.data.get('observation_revisions', {})
        changed = {key: revisions[key] for key, revision in prior.items()
                   if key in revisions and revisions[key] != revision}
        if not changed:
            continue
        # Revocation is sticky. Evidence still records divergence privately.
        divergence = {'observation_revisions': changed,
                      'reason': 'Observed outcomes changed; review the full sample before reuse.'}
        if rule.data.get('divergence') == divergence:
            continue
        status = 'needs_review' if rule.data.get('status') == 'active' else rule.data.get('status')
        store.put('rule', rule.id, dict(rule.data, status=status, divergence=divergence), rule.revision)


def relevant_outcome_rules(store: Store, context: Payload) -> list[Record]:
    """Read approved rules for a concrete matching context; unknown is no wildcard."""
    clean = _context(context, rule=True)
    result = []
    for rule in store.list('rule'):
        if rule.data.get('scope_kind') != 'performance' or rule.data.get('status') != 'active':
            continue
        scope = rule.data.get('context', {})
        if not scope or any(clean.get(key) != value for key, value in scope.items()):
            continue
        if any((row := store.get('analysis', identifier)) is None or row.revision != revision
               for identifier, revision in rule.data.get('observation_revisions', {}).items()):
            continue
        result.append(rule)
    return result
