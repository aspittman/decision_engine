"""Evaluate normalized domain facts with preserved domain policy and scoring."""
from datetime import timedelta
from decision_engine.models.contracts import timestamp
from decision_engine.strategies.domain_merchant.scoring import score_candidate, numeric
from decision_engine.services.evaluation import Decision, quality, fresh, historical

DECISIONS = ('RESEARCH_DOMAIN', 'ACQUIRE_DOMAIN', 'PRICE_DOMAIN', 'START_OUTREACH', 'CONTINUE_OUTREACH', 'STOP_OUTREACH')


def evaluate(context, report, decision_type, config):
    if decision_type in ('START_OUTREACH', 'CONTINUE_OUTREACH', 'STOP_OUTREACH'):
        return evaluate_outreach(context, report, decision_type, config)
    policy = config['domain_research_policy']
    results = []
    for candidate in report['metadata'].get('candidates', []):
        ranking = score_candidate(candidate, context, policy)
        quote = candidate.get('availability') or {}
        price = numeric(quote.get('acquisition_price'))
        screening = candidate.get('trademark_screening') or {}
        trademark = screening.get('status', 'UNKNOWN')
        checks = {
            'trademark_clear': trademark == 'CLEAR' and bool(screening.get('source_reference')) and fresh(screening.get('observed_at'), context),
            'comparable_sales': (numeric(candidate.get('comparable_count')) or 0) >= policy['minimum_comparable_sales'],
            'buyer_sample': (numeric(candidate.get('potential_buyer_count')) or 0) >= policy['minimum_potential_buyers'] and fresh((candidate.get('buyer_evidence') or {}).get('retrieved_at'), context),
            'search_demand': max((numeric(r.get('search_volume')) or 0 for r in (candidate.get('keyword_demand') or {}).get('keywords', [])), default=0) >= policy['minimum_monthly_searches'],
            'quote_fresh': fresh(quote.get('checked_at'), context, policy['availability_max_age_hours'] / 24),
            'quote_contract': quote.get('status') == 'available' and quote.get('provider') == context.constraints.domain_registrar and quote.get('price_type') == 'checkout_total' and quote.get('currency') == context.constraints.currency,
            'within_price_limit': price is not None and 0 < price <= context.constraints.max_domain_acquisition_price,
        }
        target = context.constraints.target_locations
        checks['geography'] = not target or set(map(str.lower, report['metadata'].get('locations', []))).issubset(set(map(str.lower, target)))
        performance = candidate.get('internal_performance') or {}
        checks['historical_risk'] = not ((numeric(performance.get('sent')) or 0) >= policy['minimum_feedback_sample'] and (numeric(performance.get('negative_responses')) or 0) > (numeric(performance.get('positive_responses')) or 0))
        checks['channel_policy'] = not any(k in context.constraints.blocked_channels for k in ('ACQUIRE_DOMAIN', 'DOMAIN_ACQUISITION', 'domain_merchant')) and not context.constraints.saturated
        coverage = sum(ranking['maximum_points'][k] for k in ranking['maximum_points'] if k not in ranking['unknown']) / 100
        confidence = quality(report) * coverage
        blocked = trademark == 'CONFLICT' or (price is not None and price > context.constraints.max_domain_acquisition_price) or not checks['geography'] or not checks['historical_risk'] or not checks['channel_policy']
        approved_candidate = all(checks.values()) and ranking['score'] >= config['minimum_score'] and confidence >= context.constraints.minimum_confidence
        recommendation = 'DO_NOT_ACQUIRE' if blocked else 'ACQUIRE' if approved_candidate else 'RESEARCH_FURTHER'
        details = {'checks': checks, 'scoring': ranking, 'maximum_recommended_price': context.constraints.max_domain_acquisition_price if approved_candidate else None,
                   'historical_evidence': historical(report, 'internal_outcomes'), 'purchase_authorized': False}
        if decision_type == 'RESEARCH_DOMAIN':
            recommendation = 'DO_NOT_ACQUIRE' if blocked else 'RESEARCH_FURTHER'
        if decision_type == 'PRICE_DOMAIN':
            from decision_engine.strategies.domain_merchant.pricing import evaluate as pricing
            details['pricing'] = pricing(candidate)
            recommendation = 'REVIEW_COMPARABLES' if candidate.get('comparable_count') else 'RESEARCH_FURTHER'
        failures = [k for k, value in checks.items() if not value]
        results.append(Decision(candidate['domain'], recommendation,
            'Domain evidence evaluated using explicit acquisition constraints. ' + ('Unmet checks: ' + ', '.join(failures) if failures else 'Demand, buyers, sales and acquisition quote pass; human approval required.'),
            ranking['score'], round(confidence, 4), details,
            [{'candidate_domain': candidate['domain'], 'comparables': candidate.get('comparables', []), 'buyer_evidence': candidate.get('buyer_evidence'), 'quote': quote,
              'keyword_demand': candidate.get('keyword_demand'), 'decision_metrics': candidate.get('decision_metrics'), 'trademark_screening': candidate.get('trademark_screening'), 'internal_performance': performance}],
            strategy_version='domain-acquisition-v2', policy_version='domain-acquisition-v3'))
    return results


def evaluate_outreach(context, report, decision_type, config):
    from copy import copy
    from decision_engine.strategies.domain_merchant.outreach import evaluate as assess_outreach
    scoped = copy(context)
    scoped.profile = {**context.profile, 'subject_key': report['subject_key']}
    linked_ids = set(report.get('signal_ids', []))
    scoped.signals = [s for s in context.signals if s.id in linked_ids]
    assessment = assess_outreach(scoped)
    results = []
    for candidate in report['metadata'].get('candidates', []):
        outcome = candidate.get('internal_performance') or {}
        negative = ((numeric(outcome.get('sent')) or 0) >= config['domain_research_policy']['minimum_feedback_sample']
                    and (numeric(outcome.get('negative_responses')) or 0) > (numeric(outcome.get('positive_responses')) or 0))
        recommendation = 'STOP_OUTREACH' if negative else 'REVIEW_FOR_OUTREACH' if assessment['status'] == 'REVIEW' and decision_type != 'STOP_OUTREACH' else 'NEEDS_INFORMATION'
        results.append(Decision(candidate['domain'], recommendation,
            'Negative responses exceed positive responses after the minimum sample; review stopping outreach.' if negative else
            'Owned-domain, permission, contact quality and buyer-fit checks remain separate from acquisition evidence.',
            assessment['score'], min(quality(report), assessment['confidence']),
            {'assessment': assessment, 'historical_evidence': historical(report, 'internal_outcomes'), 'send_authorized': False},
            [{'signal_id': signal_id} for signal_id in assessment['evidence_ids']] + [{'domain': candidate['domain'], 'internal_performance': outcome}],
            strategy_version='domain-outreach-v1', policy_version='domain-outreach-v1'))
    return results
