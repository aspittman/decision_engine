"""Mandatory rules are independent from sourced, modest soft opportunity scores."""
from decision_engine.models.contracts import timestamp, number
from decision_engine.strategies.product_matching import match, compare
from decision_engine.services.evaluation import Decision, weighted, quality, fresh

SCHOLARSHIP_WEIGHTS = {'award': 60, 'time_remaining': 40}
INVESTOR_WEIGHTS = {'current_activity': 50, 'recent_investment': 30, 'portfolio_evidence': 20}


def evaluate_matches(context, report, decision_type, service):
    results = []
    settings = [s for s in context.profile.get('organization_services', []) if s.get('service_key') == service and s.get('is_enabled') is True]
    profiles = [p for s in settings for p in s.get('config_json', {}).get('matching_profiles', [])]
    if len(profiles) > 100:
        raise ValueError('Matching profile limit exceeded')
    if not profiles:
        dimension = 'eligibility' if service == 'scholarship_research' else 'compatibility'
        return [Decision(opportunity['id'], 'NEEDS_INFORMATION',
                         'MMonolith researched this opportunity, but no student/business profile is configured. Supply a profile before evaluating mandatory requirements or ranking personal fit.',
                         details={dimension: 'NEEDS_INFORMATION', 'match': 'UNKNOWN',
                                  'opportunity_id': opportunity['id'], 'missing_information': ['Supplied matching profile'],
                                  'historical_evidence': {'status': 'INSUFFICIENT_DATA', 'score_adjustment': 0}},
                         evidence_refs=[{'opportunity_id': opportunity['id'], 'source_url': opportunity['url'],
                                         'facts': opportunity.get('facts', {}), 'criteria': opportunity.get('criteria', [])}])
                for opportunity in report['metadata'].get('opportunities', [])]
    for profile in profiles:
        attributes = dict(profile.get('attributes', {}))
        if service == 'scholarship_research':
            for old, canonical in {'country': 'residence_country', 'state': 'residence_region', 'major': 'field_of_study', 'education_level': 'study_level'}.items():
                if canonical not in attributes and old in attributes:
                    attributes[canonical] = attributes[old]
        for opportunity in report['metadata'].get('opportunities', []):
            hard = match(opportunity, attributes, service, context.evaluated_at)
            facts = opportunity.get('facts', {})
            values = {}
            state = hard['status']
            verified = (opportunity.get('source_status') == 'ISSUER_PAGE_VERIFIED' and opportunity.get('normalization_reviewed') is True
                        and fresh(opportunity.get('verified_at'), context) and opportunity.get('status') != 'SOURCE_CONFLICT')
            if not verified:
                state = 'RESEARCH_FURTHER'
            if service == 'scholarship_research':
                weights = SCHOLARSHIP_WEIGHTS
                amount = facts.get('award_min', {}).get('value')
                # Monetary amounts are compared only in the user's declared currency.
                if verified and amount is not None and attributes.get('currency') == facts.get('currency', {}).get('value'):
                    values['award'] = min(1, number(amount) / 5000)
                deadline = facts.get('deadline', {}).get('value')
                if verified and deadline:
                    try:
                        values['time_remaining'] = max(0, min(1, (timestamp(deadline) - context.evaluated_at).total_seconds() / (30 * 86400)))
                    except (ValueError, TypeError):
                        pass
                eligibility = 'CONFIRMED' if state == 'CRITERIA_MET' else 'INELIGIBLE' if state in ('INELIGIBLE', 'EXPIRED') else 'NEEDS_INFORMATION'
                recommendation = 'APPLY' if eligibility == 'CONFIRMED' else 'DO_NOT_APPLY' if eligibility == 'INELIGIBLE' else 'NEEDS_INFORMATION'
                dimensions = {'eligibility': eligibility}
            else:
                weights = INVESTOR_WEIGHTS
                # A complete mandate still needs explicit evidence for all four key dimensions.
                fields = {c['field'] for c in opportunity.get('criteria', [])}
                missing = [f for f in ('industry', 'stage') if f not in fields]
                if not ({'country', 'region'} & fields):
                    missing.append('geography')
                monetary_checks = []
                for field, op in (('check_min', 'gte'), ('check_max', 'lte')):
                    bound = facts.get(field, {}).get('value')
                    status = compare(attributes.get('funding_amount'), op, bound) if verified and bound is not None else 'UNKNOWN'
                    if attributes.get('currency') != facts.get('currency', {}).get('value') or attributes.get('currency') is None:
                        status = 'UNKNOWN'
                    monetary_checks.append({'field': field, 'status': status, 'required_value': bound,
                                            'source_url': facts.get(field, {}).get('source_url')})
                hard['criteria'].extend(monetary_checks)
                if state == 'POTENTIAL_FIT':
                    state = 'INCOMPATIBLE' if any(c['status'] == 'NOT_MET' for c in monetary_checks) else 'RESEARCH_FURTHER' if missing or any(c['status'] == 'UNKNOWN' for c in monetary_checks) else state
                hard['missing_information'].extend('Missing mandate dimension: ' + f for f in missing)
                compatibility = 'CONFIRMED' if state == 'POTENTIAL_FIT' else 'INCOMPATIBLE' if state in ('INCOMPATIBLE', 'EXPIRED') else 'NEEDS_INFORMATION'
                recommendation = 'REVIEW_FOR_OUTREACH' if compatibility == 'CONFIRMED' else 'DO_NOT_CONTACT' if compatibility == 'INCOMPATIBLE' else 'NEEDS_INFORMATION'
                dimensions = {'compatibility': compatibility}
                activity = facts.get('current_activity', {}).get('value')
                if verified and activity is not None:
                    # Only unambiguous normalized labels establish activity.
                    values['current_activity'] = {'active': 1, 'inactive': 0}.get(str(activity).lower())
                last = facts.get('last_investment_date', {}).get('value')
                if verified and last:
                    try:
                        age = (context.evaluated_at - timestamp(last)).total_seconds() / 86400
                        if age >= 0:
                            values['recent_investment'] = max(0, 1 - age / 365)
                    except (TypeError, ValueError):
                        pass
                portfolio = facts.get('portfolio_companies', {}).get('value')
                if verified and isinstance(portfolio, list):
                    values['portfolio_evidence'] = min(1, len(portfolio) / 5)
            hard['status'] = state
            score, points, coverage = weighted(values, weights)
            known = sum(c['status'] != 'UNKNOWN' for c in hard['criteria']) / len(hard['criteria']) if hard['criteria'] else 0
            completeness = len(hard['criteria']) / (len(hard['criteria']) + len(hard['missing_information'])) if hard['criteria'] else 0
            confidence = quality(report) * known * completeness if verified else 0
            # Soft score does not turn a failing hard rule into a match.
            strong = state in ('CRITERIA_MET', 'POTENTIAL_FIT') and score >= 70 and coverage >= .8
            results.append(Decision(str(profile['id']) + ':' + opportunity['id'], recommendation,
                'Mandatory requirements evaluated individually against the supplied profile. Soft ranking uses only sourced opportunity facts; provider confirmation and human review remain required.',
                score, round(confidence, 4), {**dimensions, 'match': 'STRONG' if strong else 'MODERATE' if state in ('CRITERIA_MET', 'POTENTIAL_FIT') else 'UNKNOWN',
                'profile_id': str(profile['id']), 'opportunity_id': opportunity['id'], 'hard_rules': hard,
                'supplied_profile': attributes,
                'points': points, 'maximum_points': weights, 'soft_evidence_coverage': coverage,
                'historical_evidence': {'status': 'INSUFFICIENT_DATA', 'score_adjustment': 0},
                'recommended_next_action': 'Human review before submission or outreach.'},
                [{'opportunity_id': opportunity['id'], 'source_url': opportunity['url'], 'criteria': hard['criteria'], 'facts': facts}]))
    return results
