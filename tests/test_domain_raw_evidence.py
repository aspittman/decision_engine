from copy import deepcopy
from datetime import datetime,timezone
from decision_engine.config.settings import scoring_config
from decision_engine.models.contracts import Context,Constraints,now
from decision_engine.strategies.domain_acquisition import DomainAcquisitionStrategy

ORG='11111111-1111-4111-8111-111111111111'

def context():
    at=now()
    report={'id':'report','organization_id':ORG,'status':'CURRENT','subject_key':'hvac','is_test':True,'confidence_score':.8,
      'metadata':{'research_contract':'domain-evidence-v1','locations':[], 'candidates':[{'domain':'hvacexample.com',
        'comparable_count':12,'potential_buyer_count':3,'keyword_demand':{'keywords':[{'search_volume':1200}]},
        'availability':{'checked_at':at.isoformat(),'status':'available','acquisition_price':12,'currency':'USD','provider':'GoDaddy','price_type':'checkout_total'}}]}}
    return Context(ORG,{'id':ORG,'domain_reports':[report]},Constraints(max_domain_acquisition_price=12,risk_tolerance='LOW'),
      [],[report],[],[],{'domain_merchant':'AVAILABLE'},at)

def test_facts_qualify_and_legacy_scores_do_not_control_decision():
    ctx=context();strategy=DomainAcquisitionStrategy(scoring_config())
    first=strategy.evaluate(ctx)
    assert first.eligible and first.parameters['research_candidate_domains']==['hvacexample.com']
    assert first.score==50 and first.expected_value is None
    assert first.parameters['candidate_decisions'][0]['decision']=='CONSIDER_BUY'
    ctx.profile['domain_reports'][0]['metadata']['candidates'][0]['legacy_comparison']={'score':0,'target_price':1}
    assert strategy.evaluate(ctx).score==first.score

def test_missing_or_stale_quotes_block_instead_of_fabricating_value():
    ctx=context();strategy=DomainAcquisitionStrategy(scoring_config())
    candidate=ctx.profile['domain_reports'][0]['metadata']['candidates'][0]
    candidate['availability']['acquisition_price']=None
    result=strategy.evaluate(ctx)
    assert not result.eligible
    assert result.parameters['candidate_decisions'][0]['decision']=='PASS'
    assert 'available_with_affordable_quote' in result.parameters['candidate_decisions'][0]['reasons']
    candidate['availability']['acquisition_price']=12
    candidate['availability']['checked_at']='2000-01-01T00:00:00Z'
    assert not strategy.evaluate(ctx).eligible

def test_failed_execution_changes_priority_without_rewriting_market_facts():
    ctx=context();strategy=DomainAcquisitionStrategy(scoring_config())
    report=ctx.profile['domain_reports'][0]
    before=deepcopy(report['metadata']['candidates'])
    report['metadata']['feedback_evaluations']=[{'evaluation':'NOT_SUPPORTED','sample_size':480}]
    assert strategy.evaluate(ctx).score==40
    assert report['metadata']['candidates']==before

def test_negative_outreach_feedback_passes_on_candidate():
    ctx=context()
    candidate=ctx.profile['domain_reports'][0]['metadata']['candidates'][0]
    candidate['internal_performance']={'source':'crm_outreach_performance','sent':40,
        'positive_responses':2,'negative_responses':10,'sale_price':None}
    result=DomainAcquisitionStrategy(scoring_config()).evaluate(ctx)
    assert not result.eligible
    assert result.parameters['candidate_decisions'][0]['decision']=='PASS'
    assert 'outreach_feedback' in result.parameters['candidate_decisions'][0]['reasons']


def test_only_godaddy_quotes_at_or_below_cap_qualify():
    ctx=context(); candidate=ctx.profile['domain_reports'][0]['metadata']['candidates'][0]
    strategy=DomainAcquisitionStrategy(scoring_config())
    candidate['availability']['provider']='Namecheap'
    assert strategy.evaluate(ctx).parameters['candidate_decisions'][0]['decision']=='PASS'
    candidate['availability']['provider']='GoDaddy'
    candidate['availability']['acquisition_price']=12.01
    assert strategy.evaluate(ctx).parameters['candidate_decisions'][0]['decision']=='PASS'
    candidate['availability']['acquisition_price']=11
    assert strategy.evaluate(ctx).parameters['candidate_decisions'][0]['decision']=='CONSIDER_BUY'
