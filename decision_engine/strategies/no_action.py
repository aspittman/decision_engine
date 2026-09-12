from decision_engine.models.contracts import Evidence, StrategyEvaluation


def no_action(reasons):
    reason = "; ".join(reasons) or "No clear channel advantage with sufficient evidence"
    return StrategyEvaluation("NO_ACTION", None, None, eligible=True, reason=reason,
                              evidence=[Evidence("RULE", reason)],
                              concerns=["WATCH confidence is zero because there is no supported operational action."])
