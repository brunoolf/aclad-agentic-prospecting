"""Private identity sets stop here; only closed numeric values reach reports."""
from __future__ import annotations

from dataclasses import dataclass, fields
import json
from .accounts import belongs
from .models import GateError, Payload, canonical, utc
from .store import Store


@dataclass(frozen=True)
class Rate:
    numerator: int
    denominator: int

    def __post_init__(self):
        if (type(self.numerator) is not int or type(self.denominator) is not int
                or self.numerator < 0 or self.denominator < self.numerator):
            raise GateError('invalid_results_metrics')


@dataclass(frozen=True)
class ResultMetrics:
    searched_accounts: int
    ever_selected_accounts: int
    current_selected_accounts: int
    contacted_accounts: int
    sent_messages: int
    human_reply_messages: int
    replied_accounts: int
    booked_meetings: int
    active_meetings: int
    cancelled_meetings: int
    meeting_accounts: int
    pending_actions: int
    reply_conversations_total: int
    reply_conversations_checked: int
    calendar_accounts_total: int
    calendar_accounts_checked: int
    account_sources_total: int
    account_sources_checked: int
    selection: Rate
    approach: Rate
    reply: Rate
    booking: Rate
    reply_to_booking: Rate

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in {'selection', 'approach', 'reply', 'booking', 'reply_to_booking'}:
                if type(value) is not Rate:
                    raise GateError('invalid_results_metrics')
            elif type(value) is not int or value < 0:
                raise GateError('invalid_results_metrics')
        for prefix in ('reply_conversations', 'calendar_accounts', 'account_sources'):
            if getattr(self, prefix + '_checked') > getattr(self, prefix + '_total'):
                raise GateError('invalid_results_metrics')


def _reference(value):
    if (isinstance(value, dict) and set(value) == {'provider', 'tenant_id', 'connection_id', 'object_id'}
            and all(isinstance(v, str) and v for v in value.values())):
        return canonical(value)
    return None


def confirmed_sent_message(store: Store, message) -> bool:
    """The message and saved successful send must describe the same effect."""
    data = message.data
    action = store.get('action', data.get('send_action_id', ''))
    sent = _reference(data.get('sent_ref'))
    if not action or not sent or data.get('status') != 'sent':
        return False
    proof = action.data
    content = proof.get('payload', {})
    return (proof.get('operation') == 'email.send' and proof.get('status') == 'succeeded'
        and content.get('message_id', proof.get('proposal_id')) == message.id
        and content.get('message') == data.get('current_message', data.get('message'))
        and data['sent_ref'].get('connection_id') == proof.get('connection_id')
        and sent in {_reference(r) for r in proof.get('external_refs', [])})


def _new_cohort(account_ids):
    result = {key: set() for key in ('searched', 'ever_selected', 'current_selected', 'contacted',
        'replied', 'meeting', 'sent_messages', 'human_replies', 'meetings', 'active_meetings', 'cancelled_meetings')}
    result['coverage'] = {key: set() for key in ('reply_conversations_total', 'reply_conversations_checked',
        'calendar_accounts_total', 'calendar_accounts_checked', 'account_sources_total', 'account_sources_checked')}
    result['account_ids'] = account_ids
    for key in ('sent_by_account', 'reply_by_account', 'meeting_by_account'):
        result[key] = {}
    return result


def collect_cohorts(store: Store) -> dict[str, Payload]:
    """Build campaign intersections privately, never serialize these identity sets."""
    accounts = {row.id: row for row in store.list('account')}
    identities = {identifier: _reference(row.data.get('external_ref')) or 'local:' + identifier
                  for identifier, row in accounts.items()}
    cohorts = {campaign.id: _new_cohort(identities.copy()) for campaign in store.list('campaign')}
    actions = {row.id: row for row in store.list('action')}
    messages = store.list('message')
    events = store.events_since()
    for event in events:
        cohort = cohorts.get(event['record_id'])
        if not cohort:
            continue
        data = event['data']
        if event['kind'] == 'candidates_recorded' and data.get('kind') == 'account':
            action = actions.get(data.get('evidence_id'))
            if not action or action.data.get('status') != 'succeeded':
                continue
            candidates = action.data.get('result', {}).get('candidates', [])
            if not isinstance(candidates, list):
                continue
            actual_ids = {item.get('id') for item in candidates if isinstance(item, dict) and isinstance(item.get('id'), str)}
            accepted = data.get('item_ids')
            source = canonical([action.data.get('connection_id'), action.data.get('operation')])
            cohort['coverage']['account_sources_total'].add(source)
            # Legacy batches with a subset have no recoverable accepted population.
            if not isinstance(accepted, list):
                accepted = list(actual_ids) if data.get('count') == len(candidates) else []
            if action.data.get('result', {}).get('complete') is True and len(accepted) == data.get('count'):
                cohort['coverage']['account_sources_checked'].add(source)
            for identifier in accepted:
                if identifier in actual_ids and identifier in accounts and belongs(accounts[identifier], event['record_id']):
                    cohort['searched'].add(identities[identifier])
        elif event['kind'] == 'accounts_selected':
            for identifier in data.get('item_ids', []):
                if identifier in accounts and belongs(accounts[identifier], event['record_id']):
                    cohort['ever_selected'].add(identities[identifier])
    for campaign_id, cohort in cohorts.items():
        for identifier, row in accounts.items():
            if belongs(row, campaign_id) and row.data.get('selected') is True:
                cohort['current_selected'].add(identities[identifier])
    tracked = {}
    for message in messages:
        campaign_id = message.data.get('campaign_id')
        cohort = cohorts.get(campaign_id)
        content = message.data.get('current_message', message.data.get('message', {}))
        account_id = content.get('account_id')
        account = accounts.get(account_id)
        action = actions.get(message.data.get('send_action_id'))
        sent_ref = _reference(message.data.get('sent_ref'))
        if (not cohort or not account or not belongs(account, campaign_id)
                or not confirmed_sent_message(store, message) or not sent_ref
                or not action or action.data.get('status') != 'succeeded'
                or action.data.get('operation') != 'email.send'
                or sent_ref not in {_reference(r) for r in action.data.get('external_refs', [])}):
            continue
        key = identities[account_id]
        cohort['contacted'].add(key)
        cohort['sent_messages'].add(sent_ref)
        cohort['sent_by_account'].setdefault(key, set()).add(sent_ref)
        conversation = _reference(message.data.get('conversation_ref'))
        if conversation:
            cohort['coverage']['reply_conversations_total'].add(conversation)
            tracked.setdefault(conversation, []).append((campaign_id, key, content.get('contact_id'), message.data.get('sent_at')))
    # Native message identity deduplicates rereads and revisions. Numeric revisions
    # establish ordering; opaque conflicting revisions stay unclassified.
    replies = {}
    for event in events:
        if event['kind'] != 'reply.observed':
            continue
        raw = event['data']
        key = _reference(raw.get('external_ref'))
        if not key:
            continue
        previous = replies.get(key)
        if previous:
            old, new = str(previous.get('source_revision')), str(raw.get('source_revision'))
            if old.isdecimal() and new.isdecimal():
                if int(new) < int(old):
                    continue
            elif old != new:
                replies[key] = dict(raw, classification='needs_review')
                continue
        replies[key] = raw
    humans = {'interested', 'question', 'not_now', 'no', 'do_not_contact', 'meeting'}
    for native_id, reply in replies.items():
        if reply.get('kind') != 'email' or reply.get('classification') not in humans:
            continue
        account_key = identities.get(reply.get('account_id'))
        for campaign_id, key, contact_id, sent_at in tracked.get(_reference(reply.get('conversation_ref')), []):
            if key != account_key or contact_id != reply.get('contact_id'):
                continue
            if sent_at and utc(reply['occurred_at']) < utc(sent_at):
                continue
            cohort = cohorts[campaign_id]
            cohort['replied'].add(key)
            cohort['human_replies'].add(native_id)
            cohort['reply_by_account'].setdefault(key, set()).add(native_id)
    for row in store.list('meeting'):
        if row.data.get('ever_confirmed') is not True:
            continue
        native_id = _reference(row.data.get('ref'))
        if not native_id:
            continue
        for campaign_id, cohort in cohorts.items():
            key = identities.get(row.data.get('account_id'))
            if not belongs(row, campaign_id) or not key:
                continue
            cohort['meeting'].add(key)
            cohort['meetings'].add(native_id)
            cohort['meeting_by_account'].setdefault(key, set()).add(native_id)
            if row.data.get('status') in {'confirmed', 'cancelled'}:
                cohort['active_meetings' if row.data['status'] == 'confirmed' else 'cancelled_meetings'].add(native_id)
    for campaign_id, cohort in cohorts.items():
        coverage = cohort['coverage']
        coverage['calendar_accounts_total'].update(cohort['contacted'])
        for cursor in store.list('cursor'):
            if cursor.data.get('source') != 'email' or not cursor.data.get('last_success'):
                continue
            scope = cursor.data.get('scope_ids')
            if scope is not None and campaign_id not in scope:
                continue
            for conversation, mappings in tracked.items():
                ref = json.loads(conversation)
                if ref['connection_id'] != cursor.data.get('connection_id'):
                    continue
                timestamps = [sent_at for c, _, _, sent_at in mappings if c == campaign_id]
                try:
                    fresh = timestamps and all(isinstance(value, str) and value for value in timestamps) and (
                        utc(cursor.data['last_success']) >= max(map(utc, timestamps)))
                except GateError:
                    fresh = False
                if fresh:
                    coverage['reply_conversations_checked'].add(conversation)
        for action in actions.values():
            data, query = action.data, action.data.get('payload', {})
            if (data.get('operation') != 'calendar.read' or data.get('status') != 'succeeded'
                    or data.get('result', {}).get('complete') is not True
                    or query.get('campaign_id') != campaign_id):
                continue
            account_ids = query.get('account_ids', [])
            if not isinstance(account_ids, list) or any(not isinstance(item, str) or not item for item in account_ids):
                continue
            for identifier in account_ids:
                key = identities.get(identifier)
                if key in cohort['contacted']:
                    timestamps = [sent_at for mappings in tracked.values() for c, account_key, _, sent_at in mappings
                                  if c == campaign_id and account_key == key]
                    try:
                        fresh = timestamps and all(isinstance(value, str) and value for value in timestamps) and (
                            isinstance(data.get('prepared_at'), str) and
                            utc(data['prepared_at']) >= max(map(utc, timestamps)))
                    except GateError:
                        fresh = False
                    if fresh:
                        coverage['calendar_accounts_checked'].add(key)
    return cohorts


def calculate_results(store: Store) -> ResultMetrics:
    cohorts = list(collect_cohorts(store).values())
    def union(key):
        return set().union(*(c[key] for c in cohorts))
    def conversion(numerator, denominator):
        return Rate(len(set().union(*(c[numerator] & c[denominator] for c in cohorts))), len(union(denominator)))
    responded = set().union(*(c['contacted'] & c['replied'] for c in cohorts))
    booked_replies = set().union(*(c['contacted'] & c['replied'] & c['meeting'] for c in cohorts))
    coverage = {key: len(set().union(*(c['coverage'][key] for c in cohorts))) for key in
        ('reply_conversations_total', 'reply_conversations_checked', 'calendar_accounts_total',
         'calendar_accounts_checked', 'account_sources_total', 'account_sources_checked')}
    pending = sum(row.data.get('status') in {'in_flight', 'unknown', 'pending', 'needs_review'}
                  for row in store.list('action'))
    return ResultMetrics(len(union('searched')), len(union('ever_selected')), len(union('current_selected')),
        len(union('contacted')), len(union('sent_messages')), len(union('human_replies')), len(responded),
        len(union('meetings')), len(union('active_meetings')), len(union('cancelled_meetings')),
        len(union('meeting')), pending, **coverage,
        selection=conversion('ever_selected', 'searched'), approach=conversion('contacted', 'ever_selected'),
        reply=conversion('replied', 'contacted'), booking=conversion('meeting', 'contacted'),
        reply_to_booking=Rate(len(booked_replies), len(responded)))
