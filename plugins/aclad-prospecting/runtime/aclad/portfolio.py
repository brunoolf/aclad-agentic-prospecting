"""Reviewed NetSuite commercial scope, independent of operational CRM and research."""
from copy import deepcopy
import hashlib

from .models import GateError, Payload, canonical, payload
from .store import Store


POLICY = {
    'version': 1,
    'allowed_kinds': ['netsuite', 'complement'],
    'complement_requires_netsuite_relationship': True,
    'independent_other_erp_crm_offers_allowed': False,
    'factual_competitor_research_allowed': True,
    'operational_crm_unrestricted': True,
    'other_system_usage_implies_purchase_intent': False,
    'learning_can_expand_portfolio': False,
    'other_product_cases_are_netsuite_proof': False,
}
OFFERING_SHAPE = {'id': 'string', 'name': 'string', 'kind': 'string',
                  'netsuite_relationship': {'product': 'string', 'type': 'string', 'description': 'string'},
                  'independent_product': 'boolean', 'status': 'string',
                  'approved_by': 'string', 'source_ids': ['string'],
                  'authorized_references': ['string']}


def validate_offerings(offerings: list[Payload]) -> list[Payload]:
    """Validate offer claims; caller review, never a site or learning, approves them."""
    if not isinstance(offerings, list):
        raise GateError('invalid_offerings')
    result, ids = [], set()
    for raw in offerings:
        offer = payload(raw)
        if (set(offer) - set(OFFERING_SHAPE)
                or any(not isinstance(offer.get(key), str) or not offer[key].strip()
                       for key in ('id', 'name', 'kind'))):
            raise GateError('invalid_offering')
        if offer['id'] in ids:
            raise GateError('duplicate_offering')
        ids.add(offer['id'])
        if offer['kind'] not in POLICY['allowed_kinds']:
            raise GateError('offering_outside_portfolio', 'Only NetSuite and explicitly linked complements can be offered.')
        if offer['kind'] == 'netsuite' and offer['name'].strip().casefold() not in {'netsuite', 'oracle netsuite'}:
            raise GateError('offering_outside_portfolio',
                'Use name "Oracle NetSuite" or "NetSuite"; record implementation/support in partner.services, not the product identity.')
        if offer.get('independent_product') is not None and type(offer['independent_product']) is not bool:
            raise GateError('invalid_offering')
        if offer.get('independent_product') is True:
            raise GateError('offering_outside_portfolio')
        if offer['kind'] == 'complement':
            relationship = offer.get('netsuite_relationship')
            if (not isinstance(relationship, dict)
                    or set(relationship) - {'product', 'type', 'description'}
                    or relationship.get('product') != 'NetSuite'
                    or relationship.get('type') not in ('integration', 'extension', 'localization')
                    or offer.get('independent_product') is not False):
                raise GateError('netsuite_relationship_required', 'Declare a NetSuite integration, extension or localization, not an independent product.')
            # Exact canonical product identifiers are offer identities, never word bans
            # on factual research, company systems, body text or operational tools.
            independent_names = {'sap', 'sap erp', 'sap s/4hana', 'dynamics', 'totvs', 'omie', 'microsoft dynamics',
                                 'microsoft dynamics 365', 'salesforce', 'hubspot',
                                 'pipedrive', 'odoo', 'monday'}
            if offer['name'].strip().casefold() in independent_names:
                raise GateError('offering_outside_portfolio', 'Name the reviewed NetSuite complement rather than an independent ERP/CRM product.')
        for key in ('source_ids', 'authorized_references'):
            if key in offer and (not isinstance(offer[key], list)
                    or any(not isinstance(item, str) or not item.strip() for item in offer[key])):
                raise GateError('invalid_offering')
        status = offer.setdefault('status', 'pending_review')
        if not isinstance(status, str) or status not in {'pending_review', 'approved'}:
            raise GateError('invalid_offering_review')
        if status == 'approved' and (not isinstance(offer.get('approved_by'), str)
                                      or not offer['approved_by'].strip()):
            raise GateError('offering_approver_required')
        if status == 'approved' and not offer.get('source_ids'):
            raise GateError('offering_evidence_required')
        result.append(offer)
    return result


def portfolio_context(store: Store) -> Payload:
    profile = store.get('profile', 'current')
    partner = profile.data.get('partner', {}) if profile else {}
    offers = validate_offerings(partner.get('offerings', []))
    active = [offer for offer in offers if offer['status'] == 'approved']
    content = {'policy': deepcopy(POLICY), 'offerings': active}
    return dict(content, digest=hashlib.sha256(canonical(content).encode()).hexdigest(),
                status='reviewed' if active else 'review_required',
                configured='offerings' in partner, requires_review=bool(partner),
                pending_offering_ids=[offer['id'] for offer in offers if offer['status'] != 'approved'])


def validate_campaign_portfolio(store: Store, campaign_id: str,
                                require_active: bool = False) -> Payload:
    """Revalidate before new generation/actions while reading legacy campaigns safely."""
    campaign = store.get('campaign', campaign_id)
    if not campaign:
        raise GateError('campaign_required')
    context = portfolio_context(store)
    snapshot = campaign.data.get('portfolio_snapshot')
    if snapshot is not None and snapshot != context:
        raise GateError('portfolio_context_changed', 'Review the changed portfolio in a new campaign before new actions.')
    if require_active and (context['requires_review'] or snapshot is not None) and not context['offerings']:
        raise GateError('portfolio_review_required', 'Review a NetSuite offer or linked complement first.')
    return context


def validate_message_portfolio(store: Store, campaign_id: str, message: Payload) -> Payload:
    context = validate_campaign_portfolio(store, campaign_id, require_active=True)
    ids = message.get('offering_ids', [])
    if not isinstance(ids, list) or any(not isinstance(id, str) for id in ids) or len(ids) != len(set(ids)):
        raise GateError('invalid_message_offerings')
    active = {offer['id'] for offer in context['offerings']}
    if set(ids) - active:
        raise GateError('offering_not_approved')
    if context['configured'] and not ids:
        raise GateError('message_offering_required', 'Select the reviewed offer that grounds the message value.')
    if 'portfolio_digest' in message and message['portfolio_digest'] != context['digest']:
        raise GateError('portfolio_context_changed')
    return context
