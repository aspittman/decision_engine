"""Transparent policy points; missing measurements earn no invented points."""
from datetime import timedelta
from math import isfinite
from decision_engine.models.contracts import timestamp

WEIGHTS = {'demand':20, 'commercial_intent':20, 'comparable_sales':15,
           'buyer_density':15, 'historical_performance':15, 'trend':10, 'brandability':5}
PENALTIES = {'trademark':100, 'high_acquisition_price':20, 'weak_buyer_pool':15,
             'poor_historical_results':15}


def numeric(value):
    if isinstance(value, bool): return None
    try:
        value = float(value)
        return value if isfinite(value) and value >= 0 else None
    except (TypeError, ValueError): return None


def score_candidate(candidate, context, policy):
    weights = policy.get('score_weights', WEIGHTS)
    values = {key: None for key in weights}
    rows = (candidate.get('keyword_demand') or {}).get('keywords', [])
    volumes = [numeric(r.get('search_volume')) for r in rows]
    volumes = [v for v in volumes if v is not None]
    if volumes: values['demand'] = min(1, max(volumes) / policy.get('full_demand_searches', 1000))
    comps = numeric(candidate.get('comparable_count'))
    if comps is not None: values['comparable_sales'] = min(1, comps / policy['minimum_comparable_sales'])
    buyers = numeric(candidate.get('potential_buyer_count'))
    if buyers is not None: values['buyer_density'] = min(1, buyers / policy.get('full_buyer_count', 3))
    # Optional normalized assessments require provenance and an explicit fresh date.
    # No string-length proxy is silently presented as measured brandability.
    for key in ('commercial_intent','historical_performance','trend','brandability'):
        observation = candidate.get('decision_metrics', {}).get(key, {})
        value = numeric(observation.get('value'))
        try:
            fresh = context.evaluated_at - timedelta(days=30) <= timestamp(observation['observed_at']) <= context.evaluated_at
        except (KeyError, TypeError, ValueError): fresh = False
        if value is not None and value <= 100 and fresh and observation.get('source_reference'):
            values[key] = value / 100
    penalties = {}
    screening = candidate.get('trademark_screening') or {}
    if screening.get('status') == 'CONFLICT': penalties['trademark'] = PENALTIES['trademark']
    price = numeric((candidate.get('availability') or {}).get('acquisition_price'))
    if price is not None and price > context.constraints.max_domain_acquisition_price:
        penalties['high_acquisition_price'] = PENALTIES['high_acquisition_price']
    if buyers is not None and buyers < policy['minimum_potential_buyers']:
        penalties['weak_buyer_pool'] = PENALTIES['weak_buyer_pool']
    performance = candidate.get('internal_performance') or {}
    if (numeric(performance.get('sent')) or 0) >= policy['minimum_feedback_sample'] and (
            numeric(performance.get('negative_responses')) or 0) > (numeric(performance.get('positive_responses')) or 0):
        penalties['poor_historical_results'] = PENALTIES['poor_historical_results']
    points = {key: round(weight * (values[key] or 0), 4) for key, weight in weights.items()}
    return {'policy':'domain-acquisition-v2', 'score':max(0, min(100, sum(points.values())-sum(penalties.values()))),
            'points':points, 'maximum_points':weights, 'penalties':penalties,
            'unknown':[key for key,value in values.items() if value is None],
            'trademark_status':screening.get('status','UNKNOWN'),
            'meaning':'Priority for human investigation, not sale probability, valuation or purchase authorization'}
