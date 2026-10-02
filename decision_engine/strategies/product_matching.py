"""Explainable profile matching from sourced research, never an execution grant."""
from datetime import timedelta
import math
from uuid import UUID
from decision_engine.models.contracts import timestamp

TYPES={'scholarship_research':'SCHOLARSHIP_RESEARCH','investor_research':'INVESTOR_RESEARCH'}


def compare(actual, operator, expected):
    if actual is None:return 'UNKNOWN'
    if operator in ('gte','lte'):
        if type(actual) not in (int,float) or type(expected) not in (int,float) or not all(math.isfinite(v) for v in (actual,expected)):
            return 'UNKNOWN'
        return 'MET' if (actual>=expected if operator=='gte' else actual<=expected) else 'NOT_MET'
    if operator=='eq':
        if type(actual) is not type(expected):return 'UNKNOWN'
        match=actual.casefold().strip()==expected.casefold().strip() if isinstance(actual,str) else actual==expected
        return 'MET' if match else 'NOT_MET'
    if operator=='in':
        if not isinstance(expected,list) or not expected or not isinstance(actual,str) or any(not isinstance(v,str) for v in expected):return 'UNKNOWN'
        return 'MET' if actual.casefold().strip() in {v.casefold().strip() for v in expected} else 'NOT_MET'
    return 'UNKNOWN'


def match(opportunity, profile, service, now):
    reasons=[];facts=opportunity.get('facts',{});criteria=opportunity.get('criteria',[])
    fresh=False
    try:fresh=now-timedelta(days=30)<=timestamp(opportunity['verified_at'])<=now
    except (ValueError,TypeError,KeyError):pass
    verified=opportunity.get('source_status')=='ISSUER_PAGE_VERIFIED' and fresh and opportunity.get('normalization_reviewed') is True
    for criterion in criteria:
        state=compare(profile.get(criterion['field']),criterion.get('operator'),criterion.get('value')) if verified else 'UNKNOWN'
        reasons.append({'field':criterion['field'],'operator':criterion.get('operator'),'required_value':criterion.get('value'),
            'status':state,'source_url':criterion.get('source_url'),'source_quote':criterion.get('quote')})
    unmet=[r['field'] for r in reasons if r['status']=='NOT_MET']
    unknown=[r['field'] for r in reasons if r['status']=='UNKNOWN']
    gates=[]
    if not verified:gates.append('Fresh issuer verification required')
    if opportunity.get('status')=='SOURCE_CONFLICT':gates.append('Conflicting source facts require review')
    if not criteria:gates.append('Eligibility or investment criteria not extracted')
    completeness='requirements_complete' if service=='scholarship_research' else 'mandate_complete'
    if facts.get(completeness,{}).get('value') is not True:gates.append('Full requirements are not confirmed')
    expired=False
    deadline=facts.get('deadline',{}).get('value')
    if deadline:
        try:expired=verified and timestamp(deadline)<=now
        except (ValueError,TypeError):gates.append('Deadline invalid')
    elif facts.get('deadline_type',{}).get('value')!='rolling' and service=='scholarship_research':gates.append('Application deadline is unknown')
    if facts.get('accepting_applications',{}).get('value') is not True:
        gates.append('Current application or investment availability is unknown or closed')
    if unknown:gates.append('Missing profile fields: '+', '.join(unknown))
    status=('EXPIRED' if expired else 'INELIGIBLE' if unmet and service=='scholarship_research' else
        'INCOMPATIBLE' if unmet else 'RESEARCH_FURTHER' if gates else 'CRITERIA_MET' if service=='scholarship_research' else 'POTENTIAL_FIT')
    met=sum(r['status']=='MET' for r in reasons)
    score=round(met/len(reasons)*100,1) if reasons and verified else None
    return {'opportunity_id':opportunity['id'],'name':opportunity['name'],'source_url':opportunity['url'],
        'status':status,'criteria_coverage_score':score,'score_scope':'Share of extracted criteria met; not award or investment probability',
        'criteria':reasons,'unmet_requirements':unmet,'missing_information':gates,
        'next_decision':'RESEARCH_FURTHER' if gates and not unmet and not expired else 'CHECK_ELIGIBILITY' if service=='scholarship_research' else 'CHECK_FIT',
        'execution_authorized':False,
        'scope':'Provider confirmation and a user-approved application or contact remain separate.'}


def evaluate(context, service):
    result={'service_id':service,'strategy':'profile_matching','execution_authorized':False,'profile_results':[],
        'decision_types':['MATCH_SCHOLARSHIP','CHECK_ELIGIBILITY','RANK_SCHOLARSHIP','RESEARCH_FURTHER'] if service=='scholarship_research' else ['MATCH_INVESTOR','CHECK_FIT','RANK_INVESTOR','RESEARCH_FURTHER']}
    settings=[r for r in context.profile.get('organization_services',[]) if r.get('service_key')==service and r.get('is_enabled') is True]
    if not settings:return {**result,'status':'NOT_CONFIGURED','reason':'Service is not enabled for this organization'}
    profiles=[p for row in settings for p in row.get('config_json',{}).get('matching_profiles',[])]
    if not profiles:return {**result,'status':'UNKNOWN','reason':'No student/business matching profiles configured'}
    if len(profiles)>100:raise ValueError('Matching profile limit exceeded')
    reports=[r for r in context.reports if r.get('organization_id')==context.organization_id and r.get('is_test') is False
        and r.get('report_type')==TYPES[service] and r.get('status')=='CURRENT' and r.get('metadata',{}).get('service_id')==service
        and r.get('metadata',{}).get('research_contract')=='product-research-v1'
        and context.evaluated_at-timedelta(days=30)<=timestamp(r['created_at'])<=context.evaluated_at]
    if not reports:return {**result,'status':'UNKNOWN','reason':'No fresh canonical research report'}
    report=max(reports,key=lambda r:(r['created_at'],r['id']))
    for profile in profiles:
        profile_id=str(UUID(profile['id']))
        attributes=dict(profile.get('attributes',{}))
        if service=='scholarship_research':
            for original, canonical in {'country':'residence_country','state':'residence_region','major':'field_of_study','education_level':'study_level'}.items():
                if canonical not in attributes and original in attributes:attributes[canonical]=attributes[original]
        if not isinstance(attributes,dict):raise ValueError('Profile attributes required')
        ranked=[match(o,attributes,service,context.evaluated_at) for o in report['metadata'].get('opportunities',[])]
        order={'CRITERIA_MET':0,'POTENTIAL_FIT':0,'RESEARCH_FURTHER':1,'INELIGIBLE':2,'INCOMPATIBLE':2,'EXPIRED':3}
        ranked.sort(key=lambda r:(order[r['status']],-(r['criteria_coverage_score'] or 0),r['opportunity_id']))
        result['profile_results'].append({'profile_id':profile_id,'rankings':ranked})
    return {**result,'status':'ASSESSED','intelligence_report_id':report['id'],
        'reason':'Explainable matching only; unknowns require research and execution is user-approved separately.'}
