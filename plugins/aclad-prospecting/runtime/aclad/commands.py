"""Allowlisted CLI routing. Connector calls remain in the chat host."""
from dataclasses import asdict
from importlib import import_module
from inspect import signature
from .models import Capability, ExternalRef, GateError, ToolResult, now_utc

# module, function, consumes Store. CLI names never select arbitrary code.
COMMANDS = {
 'connections-checklist':('connections','connection_checklist',True),
 'connections-prepare-probe':('connections','prepare_bound_probe',True),
 'portfolio-context':('portfolio','portfolio_context',True),
 'connections-step':('connections','update_connection_step',True),
 'style-presets':('style','style_presets',False),
 'style-sample-prepare':('style','prepare_style_sample',True),
 'style-sample-record':('style','record_style_sample',True),
 'style-approve':('style','approve_style',True),
 'research-start':('research','start_research',True),
 'research-crawl':('research','crawl_batch',True),
 'research-budget':('research','expand_research_budget',True),
 'research-record-evidence':('research','record_research_evidence',True),
 'research-evidence':('research','record_research_evidence',True),
 'research-context':('research','research_context',True),
 'proposal-create':('approvals','create_proposal',True),
 'approve':('approvals','approve',True),
 'prepare-action':('approvals','prepare_action',True),
 'record-result':('approvals','record_result',True),
 'meetings-record':('meetings','record_meetings',True),
 'outcome-propose':('outcome_learning','propose_outcome_rule',True),
 'outcome-context':('outcome_learning','outcome_context',True),
 'outcome-review':('outcome_learning','review_outcome_rule',True),
 'outcome-rules':('outcome_learning','relevant_outcome_rules',True),
 'learn':('learning','capture_correction',True),
 'rules':('learning','relevant_rules',True),
 'revoke-rule':('learning','revoke_rule',True),
 'account-match':('accounts','match_account',False),
 'account-check':('prospecting','check_account',True),
 'enrichment-record':('prospecting','apply_enrichment',True),
 'account-eligibility':('accounts','eligibility',False),
 'accounts-select':('accounts','select_accounts',True),
 'profile-export':('profiles','export_profile',True),
 'profile-import-preview':('profiles','preview_import',True),
 'profile-import-apply':('profiles','apply_import',True),
 'connections-discover':('connections','discover',True),
 'connections-record-probe':('connections','record_probe',True),
 'connections-guidance':('connections','connection_guidance',False),
 'normalize-result':('connections','normalize_result',False),
 'setup-next':('onboarding','next_question',True),
 'setup-answer':('onboarding','save_answer',True),
 'environment-check':('onboarding','environment_readiness',True),
 'icp-propose':('icps','propose_icp',True),
 'icp-approve':('icps','approve_icp',True),
 'icp-bind':('icps','bind_icp',True),
 'campaign-create':('prospecting','open_campaign',True),
 'candidates-record':('prospecting','record_candidates',True),
 'roles-confirm':('prospecting','confirm_roles',True),
 'contacts-select':('prospecting','select_contacts',True),
 'prospecting-propose':('prospecting','prepare_prospecting',True),
 'crm-propose':('crm','propose_crm',True),
 'crm-item-prepare':('crm','prepare_crm_item',True),
 'crm-item-record':('crm','record_crm_item',True),
 'crm-reconcile':('crm','reconcile_crm',True),
 'generation-context':('outreach','generation_context',True),
 'briefing-context':('outreach','briefing_context',True),
 'outreach-plan':('outreach','plan_outreach',True),
 'draft-propose':('messages','propose_draft',True),
 'send-propose':('messages','propose_send',True),
 'delivery-record':('delivery','record_delivery',True),
 'delivery-reconcile':('delivery','reconcile_delivery',True),
 'review-start':('followup','start_review',True),
 'review-apply':('followup','apply_review',True),
 'review-finish':('followup','finish_review',True),
 'review-resolve':('followup','resolve_review',True),
 'schedule-preview':('scheduling','next_runs',False),
 'schedule-record-result':('scheduling','record_schedule_result',True),
 'schedule-request':('scheduling','schedule_request',True),
}

def dispatch(store, command, data):
    from .recovery import bootstrap, checkpoint
    if command == 'status':
        from .results import results_report_status
        from .recovery import context_snapshot
        with store.transaction():
            return {**asdict(context_snapshot(store)), 'results_report': results_report_status(store)}
    if command == 'resume':
        return bootstrap(store)
    if command == 'checkpoint':
        return checkpoint(store)
    if command not in {'portfolio-context','connections-prepare-probe','outcome-context','review-start','review-apply','review-finish','record-result','delivery-record','delivery-reconcile','crm-item-record','crm-reconcile','meetings-record'}:
        bootstrap(store)
    if command == 'icp-analyze':
        from .icp_analysis import analyze_icps
        from uuid import uuid4
        args = dict(data)
        try:
            args['seller_ref'] = ExternalRef(**args['seller_ref'])
            result = analyze_icps(**args)
        except (KeyError, TypeError):
            raise GateError('invalid_arguments') from None
        return store.put('analysis',uuid4().hex,{'profiles':result,'created_at':now_utc()},None)
    if command not in COMMANDS:
        raise GateError('unknown_command')
    module, name, with_store = COMMANDS[command]
    function = getattr(import_module('.'+module, 'aclad'), name)
    args = dict(data)
    try:
        if 'capability' in args:
            args['capability'] = Capability(**args['capability'])
        for field in ('seller_ref','owner_ref','draft_ref'):
            if field in args:
                args[field] = ExternalRef(**args[field])
        if 'result' in args:
            item = dict(args['result'])
            item['external_refs'] = [ExternalRef(**v) for v in item['external_refs']]
            args['result'] = ToolResult(**item)
        positional = [store] if with_store else []
        signature(function).bind(*positional, **args)
    except (TypeError, KeyError, ValueError):
        raise GateError('invalid_arguments') from None
    return function(*positional, **args)
