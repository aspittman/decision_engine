"""Prefer bounded tests of independently supported demand with delivery readiness."""
from decision_engine.services.evaluation import Decision, quality, weighted, fresh, historical
from decision_engine.strategies.devspace_services.corroboration import corroboration, research_score

DECISIONS = ('RESEARCH_SERVICE', 'TEST_SERVICE', 'OFFER_SERVICE', 'CONTINUE_SERVICE', 'RETIRE_SERVICE')
WEIGHTS = {'market_demand': 25, 'cross_source': 20, 'economics': 15, 'capability': 25, 'recurring': 10, 'accessibility': 5}


def evaluate(context, report, decision_type, config):
    evidence = {e['id']: e for e in report['metadata'].get('evidence', []) if fresh(e.get('observed_at'), context)}
    results = []
    for opportunity in report['metadata'].get('opportunities', []):
        if opportunity.get('opportunity_type') != 'SERVICE':
            continue
        linked = [evidence[i] for i in opportunity.get('evidence_ids', []) if i in evidence]
        if not linked:
            continue
        confirmation = corroboration(linked)
        delivery = opportunity.get('delivery') or {}
        # These are the actual delivery configuration fields MMonolith propagates.
        capable = delivery.get('can_deliver')
        price = delivery.get('price')
        hours = delivery.get('estimated_hours')
        economics = None
        if type(price) in (int, float) and type(hours) in (int, float) and price >= 0 and hours > 0:
            economics = min(1, price / hours / 100)
        buyers = [e for e in linked if e.get('kind') == 'buyer_request']
        recurring = delivery.get('recurring_revenue_potential')
        values = {'market_demand': research_score(linked) / 100,
                  'cross_source': min(1, confirmation['independent_source_count'] / 3),
                  'economics': economics, 'capability': float(capable) if type(capable) is bool else None,
                  'recurring': float(recurring) if type(recurring) is bool else None,
                  'accessibility': sum(bool(e.get('buyer')) for e in buyers) / len(buyers) if buyers else None}
        score, points, coverage = weighted(values, WEIGHTS)
        confidence = quality(report) * coverage * min(1, confirmation['independent_source_count'] / 3) * min(1, len(linked) / 5)
        qualifies = bool(buyers) and confirmation['independent_source_count'] >= 2 and capable is True and economics is not None and score >= config['minimum_score'] and confidence >= context.constraints.minimum_confidence
        recommendation = 'DO_NOT_TEST' if capable is False else 'TEST_SERVICE' if qualifies else 'RESEARCH_FURTHER'
        if decision_type == 'RESEARCH_SERVICE':
            recommendation = 'RESEARCH_FURTHER'
        if decision_type in ('OFFER_SERVICE', 'CONTINUE_SERVICE', 'RETIRE_SERVICE'):
            recommendation = 'REVIEW_OUTCOMES' if report['metadata'].get('outcomes') else 'NEEDS_INFORMATION'
        results.append(Decision(opportunity['id'], recommendation,
            'Independent demand, observed project economics and configured delivery capability evaluated. A promising signal supports a limited test; commercial rollout requires outcome review.',
            score, round(confidence, 4), {'points': points, 'maximum_points': WEIGHTS, 'missing_factors': [k for k, v in values.items() if v is None],
            'corroboration': confirmation, 'delivery': delivery, 'historical_evidence': historical(report),
            'suggested_test': 'Review a limited prospect group and approve a bounded service experiment.' if qualifies else None},
            [{'evidence_id': e['id'], 'source_url': e.get('url'), 'source': e.get('source'), 'observed_at': e.get('observed_at')} for e in linked]))
    return results
