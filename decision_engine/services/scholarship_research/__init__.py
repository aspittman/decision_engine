from decision_engine.services.matching import evaluate_matches

DECISIONS = ('CHECK_ELIGIBILITY', 'MATCH_SCHOLARSHIP', 'RANK_OPPORTUNITY')


def evaluate(context, report, decision_type, config):
    return evaluate_matches(context, report, decision_type, 'scholarship_research')
