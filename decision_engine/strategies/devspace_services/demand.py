"""Evaluate service demand independently of pricing or execution readiness."""
from datetime import timedelta
from .corroboration import corroboration, research_score
from .corroboration import corroboration, research_score
from decision_engine.models.contracts import timestamp


def evaluate(context):
    base={'service_id':'devspace_services','strategy':'demand','execution_authorized':False,
        'opportunity_type':'SERVICE','phase':'RESEARCH_SERVICE','rankings':[]}
    if not any(s.get('service_key')=='devspace_services' and s.get('is_enabled') is True
               for s in context.profile.get('organization_services',[])):
        return {**base,'status':'BLOCKED','reason':'Service demand research is not enabled for this organization'}
    reports=[r for r in context.reports if r.get('organization_id')==context.organization_id
        and r.get('report_type')=='SERVICE_DEMAND' and r.get('is_test') is False and r.get('status')=='CURRENT'
        and r.get('metadata',{}).get('service_id')=='devspace_services'
        and r.get('metadata',{}).get('research_contract')=='service-demand-v1'
        and context.evaluated_at-timedelta(days=30)<=timestamp(r['created_at'])<=context.evaluated_at]
    if not reports:
        return {**base,'status':'UNKNOWN','reason':'No fresh attributed service-demand report'}
    report=max(reports,key=lambda r:(r['created_at'],r['id']))
    evidence={e['id']:e for e in report['metadata'].get('evidence',[])}
    rankings=[]
    for o in report['metadata'].get('opportunities',[]):
        if o.get('opportunity_type')!='SERVICE': continue
        linked=[evidence[i] for i in o.get('evidence_ids',[]) if i in evidence]
        if not linked: continue
        direct=sum(e.get('kind')=='buyer_request' for e in linked)
        rankings.append({'service_id':o['id'],'name':o['name'],'buyer_requests':direct,
            'job_postings':sum(e.get('kind')=='job_posting' for e in linked),
            'app_pain_mentions':sum(e.get('kind')=='review_pain' for e in linked),
            'web_mentions':sum(e.get('kind')=='web_mention' for e in linked),
            'research_strength_score':research_score(linked),
            'corroboration':corroboration(linked),
            'technical_pain_mentions':sum(e.get('kind')=='technical_pain' for e in linked),
            'status':'DEMAND_OBSERVED' if direct else 'INDIRECT_EVIDENCE_ONLY',
            'evidence_ids':[e['id'] for e in linked],
            'recommendation':'Investigate buyer demand for '+o['name'],
            'offering_approved':False})
    rankings.sort(key=lambda r:(-r['research_strength_score'],-r['buyer_requests'],r['service_id']))
    return {**base,'status':'DEMAND_OBSERVED' if any(r['buyer_requests'] for r in rankings) else 'INDIRECT_EVIDENCE_ONLY',
        'rankings':rankings,'intelligence_report_id':report['id'],
        'reason':'Demand research only. Pricing does not block assessment; testing, offering, sending and retiring require separate decisions.'}
