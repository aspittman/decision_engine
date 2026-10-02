from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
from decision_engine.strategies.product_matching import evaluate


def setup(context,service='scholarship_research'):
    p1,p2=str(uuid4()),str(uuid4())
    attrs={'gpa':3.6} if service=='scholarship_research' else {'stage':'Seed','industry':'SaaS'}
    context.profile['organization_services']=[{'service_key':service,'is_enabled':True,
        'config_json':{'matching_profiles':[{'id':p1,'attributes':attrs},{'id':p2,'attributes':{}}]}}]
    field='gpa' if service=='scholarship_research' else 'stage'
    value=3.4 if service=='scholarship_research' else ['Seed']
    completeness='requirements_complete' if service=='scholarship_research' else 'mandate_complete'
    opportunity={'id':'one','name':'First party opportunity','url':'https://issuer.example/program',
        'source_status':'ISSUER_PAGE_VERIFIED','normalization_reviewed':True,'verified_at':context.evaluated_at.isoformat(),'status':'CURRENT',
        'facts':{completeness:{'value':True},'deadline':{'value':(context.evaluated_at+timedelta(days=10)).isoformat()},'accepting_applications':{'value':True}},
        'criteria':[{'field':field,'operator':'gte' if service=='scholarship_research' else 'in','value':value,'source_url':'https://issuer.example/program','quote':'Official verified requirements'}]}
    report={'id':'report','organization_id':context.organization_id,'is_test':False,'status':'CURRENT',
        'report_type':'SCHOLARSHIP_RESEARCH' if service=='scholarship_research' else 'INVESTOR_RESEARCH','created_at':context.evaluated_at.isoformat(),
        'metadata':{'service_id':service,'research_contract':'product-research-v1','opportunities':[opportunity]}}
    context.reports=[report]
    return report,opportunity


def test_profiles_are_independent_and_unknowns_do_not_pass(context):
    setup(context)
    result=evaluate(context,'scholarship_research')
    assert result['profile_results'][0]['rankings'][0]['status']=='CRITERIA_MET'
    assert result['profile_results'][1]['rankings'][0]['status']=='RESEARCH_FURTHER'
    assert result['profile_results'][1]['rankings'][0]['criteria_coverage_score']==0
    assert result['execution_authorized'] is False


def test_expired_missing_completeness_and_conflicting_sources(context):
    report,item=setup(context)
    item['facts']['requirements_complete']['value']=False
    assert evaluate(context,'scholarship_research')['profile_results'][0]['rankings'][0]['status']=='RESEARCH_FURTHER'
    item['facts']['deadline']['value']=(context.evaluated_at-timedelta(days=1)).isoformat()
    assert evaluate(context,'scholarship_research')['profile_results'][0]['rankings'][0]['status']=='EXPIRED'
    item['facts']['deadline']['value']=(context.evaluated_at+timedelta(days=1)).isoformat()
    item['status']='SOURCE_CONFLICT'
    assert evaluate(context,'scholarship_research')['profile_results'][0]['rankings'][0]['status']=='RESEARCH_FURTHER'


def test_source_age_review_and_tenant_are_required(context):
    report,item=setup(context)
    item['normalization_reviewed']=False
    assert evaluate(context,'scholarship_research')['profile_results'][0]['rankings'][0]['status']=='RESEARCH_FURTHER'
    item['normalization_reviewed']=True
    item['verified_at']=(context.evaluated_at-timedelta(days=31)).isoformat()
    assert evaluate(context,'scholarship_research')['profile_results'][0]['rankings'][0]['status']=='RESEARCH_FURTHER'
    for key,value in [('organization_id','other'),('is_test',True),('created_at',(context.evaluated_at-timedelta(days=31)).isoformat())]:
        wrong=deepcopy(report);wrong[key]=value;context.reports=[wrong]
        assert evaluate(context,'scholarship_research')['status']=='UNKNOWN'


def test_investor_match_is_fit_not_guaranteed_funding(context):
    _,item=setup(context,'investor_research')
    result=evaluate(context,'investor_research')
    assert result['profile_results'][0]['rankings'][0]['status']=='POTENTIAL_FIT'
    assert 'probability' in result['profile_results'][0]['rankings'][0]['score_scope']
    item['criteria'][0]['value']=['Series A']
    assert evaluate(context,'investor_research')['profile_results'][0]['rankings'][0]['status']=='INCOMPATIBLE'


def test_invalid_numeric_profile_remains_unknown(context):
    setup(context)
    context.profile['organization_services'][0]['config_json']['matching_profiles'][0]['attributes']['gpa']='3.6'
    assert evaluate(context,'scholarship_research')['profile_results'][0]['rankings'][0]['status']=='RESEARCH_FURTHER'
