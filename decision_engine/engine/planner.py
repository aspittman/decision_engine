from decimal import Decimal


def rank_and_plan(evaluations, context):
    """Allocate one shared budget and resolve dependencies before persistence."""
    # Advisory assessments carry no executable action and have separate database uniqueness.
    active = {r["recommendation_type"] for r in context.active
              if not (r.get('metadata', {}).get('decision_contract') == 'service-decision-v1'
                      and r.get('metadata', {}).get('execution_authorized') is False
                      and r.get('execution_service') is None
                      and r.get('metadata', {}).get('action_type') is None)}
    candidates = {e.recommendation_type: e for e in evaluations if e.eligible and e.recommendation_type not in active}
    rejected = [f"{kind}: an active recommendation already exists" for kind in active if any(e.recommendation_type == kind and e.eligible for e in evaluations)]
    remaining = Decimal(str(context.available_budget))
    selected, visiting = {}, set()

    def add(item):
        nonlocal remaining
        if item.recommendation_type in selected:
            return True
        if item.recommendation_type in visiting:
            raise ValueError("Cyclic strategy dependency")
        visiting.add(item.recommendation_type)
        for kind in item.dependency_types:
            dependency = candidates.get(kind)
            if dependency is None or not add(dependency):
                rejected.append(f"{item.recommendation_type}: prerequisite unavailable; evaluate again after completion")
                visiting.remove(item.recommendation_type)
                return False
        visiting.remove(item.recommendation_type)
        cost = Decimal(str(item.suggested_budget or 0))
        available = Decimal(str(context.constraints.max_domain_acquisition_price)) if item.recommendation_type == "DOMAIN_ACQUISITION" else remaining
        if cost > available:
            rejected.append(f"{item.recommendation_type}: combined recommendations exceed available budget")
            return False
        if item.recommendation_type != "DOMAIN_ACQUISITION":
            remaining -= cost
        selected[item.recommendation_type] = item
        return True

    for item in sorted(candidates.values(), key=lambda e: (-e.score, -e.confidence, e.recommendation_type)):
        add(item)
    return list(selected.values()), rejected
