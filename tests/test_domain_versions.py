from copy import deepcopy
from decision_engine.config.settings import scoring_config
from decision_engine.models.contracts import Context, Constraints, Signal, now
from decision_engine.strategies.domain_acquisition import DomainAcquisitionStrategy

ORG='11111111-1111-4111-8111-111111111111'

def test_domain_report_and_prediction_confidence_are_applied(monkeypatch):
    at=now()
    signals=[Signal(str(i),ORG,metric,95,.95,'test',at,metadata={'subject_key':'hvac'}) for i,metric in enumerate(scoring_config()['strategies']['DOMAIN_ACQUISITION']['metrics'])]
    report={'id':'new','organization_id':ORG,'status':'CURRENT','subject_key':'hvac','confidence_score':.9,'is_test':True,
      'signal_ids':[s.id for s in signals],'metadata':{'internal_performance_score':30,'internal_confidence':.8}}
    context=Context(ORG,{'id':ORG,'domain_reports':[report],'predictions':[{'intelligence_report_id':'new','confidence':.7}]},
      Constraints(monthly_marketing_budget=1000,risk_tolerance='MEDIUM'),signals,[report],[],[],{'domain_merchant':'AVAILABLE'},at)
    result=DomainAcquisitionStrategy(scoring_config()).evaluate(context)
    assert result.confidence==.7
    assert result.parameters['subject_key']=='hvac' and result.parameters['is_test']
    assert result.parameters['purchase_authorized'] is False
    assert any(e.intelligence_report_id=='new' for e in result.evidence)
    before=result.score
    context=deepcopy(context)
    context.profile['domain_reports'][0]['metadata']['internal_performance_score']=90
    assert DomainAcquisitionStrategy(scoring_config()).evaluate(context).score>before
