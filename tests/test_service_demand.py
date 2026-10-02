from datetime import timedelta
from copy import deepcopy
from decision_engine.strategies.devspace_services.demand import evaluate


def report(context):
    return {'id':'report','organization_id':context.organization_id,'report_type':'SERVICE_DEMAND','is_test':False,
        'created_at':context.evaluated_at.isoformat(),'status':'CURRENT','metadata':{'service_id':'devspace_services',
        'research_contract':'service-demand-v1','evidence':[{'id':'e','kind':'buyer_request'}],
        'opportunities':[{'id':'api_integrations','name':'API integrations','opportunity_type':'SERVICE','evidence_ids':['e']}]}}


def test_demand_does_not_need_prices_or_authorize_execution(context):
    context.profile['organization_services']=[{'service_key':'devspace_services','is_enabled':True}]
    context.reports=[report(context)]
    result=evaluate(context)
    assert result['status']=='DEMAND_OBSERVED'
    assert result['rankings'][0]['buyer_requests']==1
    assert result['execution_authorized'] is False


def test_scope_test_mode_staleness_and_missing_evidence(context):
    context.profile['organization_services']=[{'service_key':'devspace_services','is_enabled':True}]
    r=report(context)
    for field,value in [('organization_id','other'),('is_test',True),('created_at',(context.evaluated_at-timedelta(days=31)).isoformat())]:
        modified=deepcopy(r);modified[field]=value;context.reports=[modified]
        assert evaluate(context)['status']=='UNKNOWN'
    r['metadata']['evidence'][0]['kind']='web_mention';context.reports=[r]
    assert evaluate(context)['status']=='INDIRECT_EVIDENCE_ONLY'
