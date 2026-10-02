from dataclasses import replace
from datetime import timedelta
from copy import deepcopy
from decision_engine.models.contracts import Signal,uid
from decision_engine.strategies.domain_merchant.scoring import score_candidate,WEIGHTS
from decision_engine.strategies.domain_merchant.review import DomainResearchReviewStrategy
from decision_engine.strategies.scholarship_research.eligibility import evaluate
from decision_engine.strategies.registry import assess_services
from test_domain_raw_evidence import context as domain_context


def test_domain_weights_unknown_and_risk_veto(config):
    c=domain_context();p=config['domain_research_policy']
    row=c.profile['domain_reports'][0]['metadata']['candidates'][0]
    initial=score_candidate(row,c,p)
    assert sum(WEIGHTS.values())==100 and initial['score']==50
    assert 'historical_performance' in initial['unknown']
    row['decision_metrics']={k:{'value':100,'observed_at':c.evaluated_at.isoformat(),'source_reference':'observed-input'} for k in ('commercial_intent','historical_performance','trend','brandability')}
    assert score_candidate(row,c,p)['score']==100
    row['trademark_screening']={'status':'CONFLICT'}
    assert score_candidate(row,c,p)['score']==0
    from decision_engine.strategies.domain_acquisition import DomainAcquisitionStrategy
    assert not DomainAcquisitionStrategy(config).evaluate(c).eligible


def test_future_metrics_do_not_gain_points(config):
    c=domain_context();row=c.profile['domain_reports'][0]['metadata']['candidates'][0]
    row['decision_metrics']={'commercial_intent':{'value':100,'observed_at':(c.evaluated_at+timedelta(days=1)).isoformat(),'source_reference':'future'}}
    assert score_candidate(row,c,config['domain_research_policy'])['points']['commercial_intent']==0


def test_service_scoping_and_hard_eligibility(context):
    context.profile['organization_services']=[{'service_key':'scholarship_research','is_enabled':True}]
    for key in ('academic_fit','location_fit','study_fit','financial_fit','all_required_criteria_met','deadline_open'):
        context.signals.append(Signal(uid(),context.organization_id,key,100,.95,'verified_source',context.evaluated_at,
            metadata={'service_id':'scholarship_research','subject_key':'organization'}))
    assert evaluate(context)['status']=='REVIEW'
    context.signals[-1]=replace(context.signals[-1],value=0)
    assert evaluate(context)['status']=='BLOCKED'
    context.signals=[replace(s,metadata={'service_id':'investor_research','subject_key':'organization'}) for s in context.signals]
    assert evaluate(context)['status']=='UNKNOWN'
    assert all(not r['execution_authorized'] for r in assess_services(context))


def test_production_review_needs_registered_adapter_and_does_not_buy(config):
    c=domain_context();r=c.profile['domain_reports'][0];r['created_at']=c.evaluated_at.isoformat();r['is_test']=False
    strategy=DomainResearchReviewStrategy(config)
    assert not strategy.evaluate(c).eligible
    c.profile['execution_capability_details']=[{'service_key':'domain_merchant','status':'AVAILABLE','adapter_ready':True,'allowed_actions':['review_domain_evidence']}]
    # Market evidence can be incomplete without pretending acquisition is eligible.
    r['confidence_score']=.1
    result=strategy.evaluate(c)
    assert result.eligible and result.suggested_budget==0
    assert result.parameters['purchase_authorized'] is False
    r['is_test']=True
    assert not strategy.evaluate(c).eligible
    r['is_test']=False
    c.profile['reviewed_domain_report_ids']=[r['id']]
    assert not strategy.evaluate(c).eligible
