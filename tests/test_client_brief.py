from datetime import timedelta
from decision_engine.models.contracts import uid
from decision_engine.strategies.devspace_clients.brief import ClientOutreachBriefStrategy

def configure(context):
    context.profile['organization_services'] = [{'service_key': 'devspace_clients', 'is_enabled': True}]
    context.profile['execution_capability_details'] = [{'service_key': 'devspace_clients', 'status': 'AVAILABLE',
        'adapter_ready': True, 'allowed_actions': ['prepare_client_outreach']}]
    context.reports = [{'id': uid(), 'organization_id': context.organization_id, 'report_type': 'CLIENT_RESEARCH',
        'is_test': False, 'status': 'CURRENT', 'created_at': context.evaluated_at.isoformat(), 'subject_key': 'client:one',
        'metadata': {'service_id': 'devspace_clients', 'opportunities': [{'id': 'one', 'status': 'REVIEW'}]}}]
    return context.reports[0]

def test_brief_is_zero_spend_and_does_not_authorize_sending(context, config):
    report = configure(context)
    result = ClientOutreachBriefStrategy(config).evaluate(context)
    assert result.eligible
    assert result.execution_service == 'devspace_clients'
    assert result.parameters['intelligence_report_id'] == report['id']
    assert result.parameters['budget_limit'] == 0
    assert result.parameters['send_authorized'] is False
    assert result.parameters['external_calls_authorized'] is False

def test_disabled_adapter_and_service_block(context, config):
    configure(context)
    context.profile['organization_services'][0]['is_enabled'] = False
    assert not ClientOutreachBriefStrategy(config).evaluate(context).eligible
    context.profile['organization_services'][0]['is_enabled'] = True
    context.profile['execution_capability_details'][0]['adapter_ready'] = False
    assert not ClientOutreachBriefStrategy(config).evaluate(context).eligible

def test_stale_test_and_latest_empty_reports_block(context, config):
    report = configure(context)
    report['created_at'] = (context.evaluated_at - timedelta(days=1000)).isoformat()
    assert not ClientOutreachBriefStrategy(config).evaluate(context).eligible
    report['created_at'] = context.evaluated_at.isoformat(); report['is_test'] = True
    assert not ClientOutreachBriefStrategy(config).evaluate(context).eligible
    report['is_test'] = False
    context.reports.append({**report, 'id': uid(), 'created_at': (context.evaluated_at + timedelta(seconds=1)).isoformat(),
        'metadata': {'service_id': 'devspace_clients', 'opportunities': []}})
    assert not ClientOutreachBriefStrategy(config).evaluate(context).eligible

def test_completed_exact_report_is_not_recommended_again(context, config):
    report = configure(context)
    context.profile['client_execution_results'] = [{'status': 'COMPLETED', 'results': {
        'execution_contract': 'client-outreach-brief-v1', 'intelligence_report_id': report['id']}}]
    assert not ClientOutreachBriefStrategy(config).evaluate(context).eligible
