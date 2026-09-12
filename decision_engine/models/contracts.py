from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from uuid import UUID, uuid4


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid4())


def timestamp(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise ValueError("Timestamp must have a timezone")
    return result


def number(value: Any, minimum: float = 0, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a numeric measurement")
    result = float(value)
    if not isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise ValueError("Numeric value outside allowed range")
    return result


@dataclass(frozen=True)
class Constraints:
    monthly_marketing_budget: float = 0
    max_ad_spend: float = 0
    committed_monthly_spend: float = 0
    currency: str = "USD"
    allowed_channels: tuple[str, ...] = ()
    blocked_channels: tuple[str, ...] = ()
    target_locations: tuple[str, ...] = ()
    target_industries: tuple[str, ...] = ()
    brand_restrictions: tuple[str, ...] = ()
    requires_human_approval: bool = True
    risk_tolerance: str = "LOW"
    minimum_confidence: float = 0.65
    maximum_cost_per_lead: float | None = None
    service_preferences: tuple[str, ...] = ()
    email_reputation_healthy: bool = False
    time_horizon_months: int = 3
    saturated: bool = False

    @classmethod
    def parse(cls, data: dict) -> Constraints:
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError("Unsupported constraint fields: " + ", ".join(sorted(unknown)))
        result = cls(**data)
        for name in ("monthly_marketing_budget", "max_ad_spend", "committed_monthly_spend"):
            number(getattr(result, name))
        number(result.minimum_confidence, 0, 1)
        if result.maximum_cost_per_lead is not None:
            number(result.maximum_cost_per_lead, 0.01)
        number(result.time_horizon_months, 0)
        if result.risk_tolerance not in ("LOW", "MEDIUM", "HIGH"):
            raise ValueError("Invalid risk tolerance")
        if len(result.currency) != 3 or not result.currency.isupper():
            raise ValueError("Currency must be a three-letter uppercase code")
        for name in ("allowed_channels", "blocked_channels", "target_locations", "target_industries",
                     "brand_restrictions", "service_preferences"):
            value = getattr(result, name)
            if not isinstance(value, (list, tuple)) or not all(isinstance(x, str) for x in value):
                raise ValueError("Constraint lists must contain strings")
        for name in ("requires_human_approval", "email_reputation_healthy", "saturated"):
            if not isinstance(getattr(result, name), bool):
                raise ValueError("Constraint flag must be boolean")
        return result

    @property
    def remaining_budget(self) -> float:
        return max(0, float(self.monthly_marketing_budget) - float(self.committed_monthly_spend))


@dataclass(frozen=True)
class Signal:
    id: str
    organization_id: str
    metric: str
    value: float
    confidence: float
    source: str
    observed_at: datetime
    expires_at: datetime | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, row: dict) -> Signal:
        return cls(row["id"], row["organization_id"], row["metric"],
                   number(row["value_numeric"], 0, 100), number(row["confidence_score"], 0, 1),
                   row["source"], timestamp(row["observed_at"]),
                   timestamp(row["expires_at"]) if row.get("expires_at") else None,
                   row.get("metadata", {}))


@dataclass(frozen=True)
class ExecutionResult:
    id: str
    organization_id: str
    execution_service: str
    cost: float | None
    revenue: float | None
    metrics: dict
    completed_at: datetime
    currency: str
    subject_key: str

    @classmethod
    def parse(cls, row: dict) -> ExecutionResult:
        return cls(row["id"], row["organization_id"], row["execution_service"],
                   number(row["cost"]) if row.get("cost") is not None else None,
                   number(row["revenue_attributed"]) if row.get("revenue_attributed") is not None else None,
                   row.get("metrics", {}), timestamp(row["completed_at"]), row["currency"], row["subject_key"])


@dataclass(frozen=True)
class Evidence:
    evidence_type: str
    description: str
    signal_id: str | None = None
    intelligence_report_id: str | None = None
    execution_result_id: str | None = None
    weight: float | None = None


@dataclass
class Context:
    organization_id: str
    profile: dict
    constraints: Constraints
    signals: list[Signal]
    reports: list[dict]
    history: list[ExecutionResult]
    active: list[dict]
    capabilities: dict[str, str]
    evaluated_at: datetime = field(default_factory=now)

    def __post_init__(self):
        UUID(self.organization_id)
        if self.profile["id"] != self.organization_id:
            raise ValueError("Organization profile mismatch")
        records = [*self.signals, *self.history]
        if any(r.organization_id != self.organization_id for r in records):
            raise ValueError("Cross-organization context rejected")
        if any(r.get("organization_id") != self.organization_id for r in self.reports + self.active):
            raise ValueError("Cross-organization context rejected")

    @property
    def available_budget(self) -> float:
        return max(0, self.constraints.remaining_budget - self.profile.get("reserved_budget", 0))

    @property
    def available_ad_budget(self) -> float:
        return max(0, self.constraints.max_ad_spend - self.profile.get("reserved_ad_budget", 0))

    @property
    def subject_key(self) -> str:
        return self.profile.get("subject_key", "organization")


@dataclass
class StrategyEvaluation:
    recommendation_type: str
    execution_service: str | None
    action_type: str | None
    eligible: bool = False
    score: float = 0
    confidence: float = 0
    priority: str = "WATCH"
    expected_value: float | None = None
    expected_cost: float | None = None
    suggested_budget: float | None = None
    reason: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    risk_level: str = "LOW"
    parameters: dict = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    dependency_types: list[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)
    id: str = field(default_factory=uid)
