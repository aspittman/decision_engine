from decision_engine.services.matching import evaluate_matches

DECISIONS = ('CHECK_COMPATIBILITY', 'MATCH_INVESTOR', 'RANK_INVESTOR')


def evaluate(context, report, decision_type, config):
    return evaluate_matches(context, report, decision_type, 'investor_research')
