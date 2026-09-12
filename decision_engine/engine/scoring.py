"""Attractiveness and confidence are deliberately separate quantities."""
from decision_engine.models.contracts import number


def score(components, config):
    positive = sum(number(components[k], 0, 100) * w for k, w in config["weights"].items())
    negative = sum(number(components[k], 0, 100) * w for k, w in config["penalties"].items())
    return round(max(0, min(100, positive - negative)), 2)


def confidence(signals, required_count, exponent=0.5):
    if not signals or required_count <= 0:
        return 0.0
    coverage = min(1, len(signals) / required_count)
    return round(sum(s.confidence for s in signals) / len(signals) * coverage ** exponent, 4)


def priority(value, config):
    if value.dependency_types:
        return "MEDIUM"
    if value.score >= config["critical_priority_score"] and value.confidence >= 0.9 and value.parameters.get("urgent"):
        return "CRITICAL"
    if value.score >= config["high_priority_score"] and value.confidence >= 0.65:
        return "HIGH"
    return "MEDIUM" if value.score >= config["minimum_score"] else "LOW"
