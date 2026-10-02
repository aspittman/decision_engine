"""Use current client findings; never invent performance or impact measurements."""
from decision_engine.services.evaluation import Decision, quality, fresh, historical

DECISIONS = ('IDENTIFY_OPPORTUNITY', 'RECOMMEND_SERVICE', 'PRIORITIZE_WORK')


def evaluate(context, report, decision_type, config):
    results = []
    for opportunity in report['metadata'].get('opportunities', []):
        source = [e for e in opportunity.get('evidence', []) if e.get('source_reference') and fresh(e.get('observed_at'), context)]
        findings = [f for f in opportunity.get('findings', []) if f.get('source_reference') and fresh(f.get('observed_at'), context)]
        if not source and not findings:
            continue
        outages = [f for f in findings if f.get('metric') == 'website_http_status' and type(f.get('value')) is int and 500 <= f['value'] <= 599]
        fit = opportunity.get('fit_score', 0)
        confidence = min(quality(report), float(opportunity.get('fit_confidence', 0)))
        score = 80 if outages else min(60, float(fit) * .6)
        recommendation = 'REVIEW_WEBSITE_AVAILABILITY' if outages else 'REVIEW_CLIENT_OPPORTUNITY' if opportunity.get('status') == 'REVIEW' and source else 'NEEDS_INFORMATION'
        if decision_type == 'RECOMMEND_SERVICE' and not outages:
            recommendation = 'NEEDS_INFORMATION'
        results.append(Decision(opportunity['id'], recommendation,
            'Observed HTTP server failure justifies a diagnostic review; revenue impact and remediation scope remain unmeasured.' if outages else 'Client fit evidence supports review; it does not establish a technical problem, buying intent or a service scope.',
            score, confidence, {'priority': 'HIGH' if outages else 'LOW', 'findings': findings,
            'missing_information': opportunity.get('missing_information', []), 'offer': opportunity.get('offer'),
            'historical_evidence': historical(report, 'outcome_history')}, source + findings))
    return results
