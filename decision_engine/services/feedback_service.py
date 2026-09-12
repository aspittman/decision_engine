from datetime import timedelta
from decision_engine.models.contracts import Evidence, number


def feedback(context, service, config):
    """Shrink same-tenant, same-subject performance toward neutral, using pooled CPL."""
    rows = [r for r in context.history if r.execution_service == service
            and r.subject_key == context.subject_key and r.currency == context.constraints.currency
            and context.evaluated_at - timedelta(days=config["history_age_days"]) <= r.completed_at <= context.evaluated_at]
    usable, costs, leads, revenues = [], 0.0, 0.0, 0.0
    for row in rows:
        if row.cost is None or row.cost <= 0:
            continue
        try:
            count = number(row.metrics.get("leads", 0))
        except (TypeError, ValueError):
            continue
        if context.constraints.maximum_cost_per_lead is None and row.revenue is None:
            continue
        usable.append(row)
        costs += row.cost
        leads += count
        revenues += row.revenue or 0
    if not usable:
        return 50.0, []
    if context.constraints.maximum_cost_per_lead is not None:
        ratio = leads * context.constraints.maximum_cost_per_lead / costs
    else:
        ratio = revenues / costs
    observed = min(100, 50 * ratio)
    reliability = len(usable) / (len(usable) + config["history_prior_samples"])
    value = 50 + reliability * (observed - 50)
    evidence = [Evidence("HISTORICAL_RESULT", "Comparable completed execution included in pooled CPL/ROI feedback",
                         execution_result_id=r.id, weight=round(reliability / len(usable), 4)) for r in usable]
    return round(value, 2), evidence
