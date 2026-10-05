from dataclasses import replace
from decision_engine.engine.planner import rank_and_plan
from decision_engine.models.contracts import StrategyEvaluation


def test_advisory_assessment_does_not_suppress_executable_review(context):
    review = StrategyEvaluation('MARKET_RESEARCH', 'domain_merchant', 'review_domain_evidence', eligible=True, score=60, confidence=1, suggested_budget=0)
    advisory = {'recommendation_type': 'MARKET_RESEARCH', 'execution_service': None,
        'metadata': {'decision_contract': 'service-decision-v1', 'execution_authorized': False, 'action_type': None}}
    context.active = [advisory]
    selected, _ = rank_and_plan([review], context)
    assert selected == [review]
    # Legacy/unknown and real actionable recommendations still suppress duplicates.
    for active in ({'recommendation_type': 'MARKET_RESEARCH'},
                   {**advisory, 'execution_service': 'domain_merchant'},
                   {**advisory, 'metadata': {**advisory['metadata'], 'action_type': 'review_domain_evidence'}}):
        context.active = [active]
        assert rank_and_plan([review], context)[0] == []
