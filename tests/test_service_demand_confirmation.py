from copy import deepcopy
from test_service_demand import report
from decision_engine.strategies.devspace_services.demand import evaluate


def test_independent_confirmation_is_recomputed_and_supply_does_not_count(context):
    context.profile['organization_services']=[{'service_key':'devspace_services','is_enabled':True}]
    r=report(context)
    rows=[{'id':'u'+str(i),'kind':'buyer_request','source':'alias'+str(i),'url':'https://upwork.com/jobs/'+str(i),'text':'Need API integration'} for i in range(20)]
    rows += [{'id':'r','kind':'technical_pain','source':'reddit','url':'https://reddit.com/r/business/comments/1','text':'API integration trouble'},
        {'id':'f','kind':'competitor_offer','source':'fiverr','url':'https://fiverr.com/seller/api','text':'API integration services'},
        {'id':'s','kind':'web_mention','source':'public_search','url':'https://github.com/org/repo/issues/1','text':'API integration'}]
    r['metadata']['evidence']=rows
    r['metadata']['opportunities'][0].update(evidence_ids=[e['id'] for e in rows],source_count=999,research_strength_score=999)
    context.reports=[r]
    assessment=evaluate(context)['rankings'][0]
    assert assessment['corroboration']['independent_sources']==['reddit','upwork']
    assert assessment['corroboration']['status']=='CROSS_SOURCE_DEMAND'
    assert assessment['research_strength_score']<100
    assert assessment['offering_approved'] is False
