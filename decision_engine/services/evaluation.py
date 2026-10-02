"""Small deterministic recommendation primitives; no research or execution."""
from dataclasses import dataclass, field
from datetime import timedelta
from decision_engine.models.contracts import number, timestamp


def fresh(value, context, days=30):
    try:
        return context.evaluated_at - timedelta(days=days) <= timestamp(value) <= context.evaluated_at
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def quality(report):
    return number(report.get('confidence_score', 0), 0, 1)


@dataclass
class Decision:
    subject_id: str
    recommendation: str
    reason: str
    score: float = 0
    confidence: float = 0
    details: dict = field(default_factory=dict)
    evidence_refs: list = field(default_factory=list)
    strategy_version: str = 'v1'
    policy_version: str = 'v1'
    requires_approval: bool = True


def weighted(values, weights):
    """Missing factors earn no points and reduce coverage, never become negatives."""
    points = {k: round(number(values[k], 0, 1) * w, 4) if values.get(k) is not None else 0
              for k, w in weights.items()}
    return round(sum(points.values()), 4), points, sum(w for k, w in weights.items() if values.get(k) is not None) / 100


def historical(report, key='outcomes'):
    rows = report.get('metadata', {}).get(key, [])
    return {'status': 'OBSERVED' if rows else 'INSUFFICIENT_DATA',
            'sample_size': len(rows), 'execution_result_ids': [r.get('execution_result_id', r.get('id')) for r in rows],
            'score_adjustment': 0, 'scope': 'Recorded observations; no causal or success-rate inference'}
