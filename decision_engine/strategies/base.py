from abc import ABC, abstractmethod
from datetime import timedelta
from decision_engine.engine.scoring import score, confidence, priority
from decision_engine.models.contracts import Evidence, StrategyEvaluation
from decision_engine.services.feedback_service import feedback


class Strategy(ABC):
    kind: str
    service: str
    action: str
    inverse: tuple[str, ...] = ()
    risk = "LOW"

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def evaluate(self, context) -> StrategyEvaluation:
        raise NotImplementedError

    def signals(self, context):
        selected = {}
        oldest = context.evaluated_at - timedelta(days=self.config["max_signal_age_days"])
        for signal in sorted(context.signals, key=lambda s: (s.observed_at, s.id)):
            if oldest <= signal.observed_at <= context.evaluated_at and (signal.expires_at is None or signal.expires_at > context.evaluated_at):
                if signal.metadata.get("subject_key", "organization") == context.subject_key:
                    selected[signal.metric] = signal
        return selected

    def build(self, context, *, reason, service=None):
        service = service or self.service
        settings = self.config["strategies"][self.kind]
        selected = self.signals(context)
        available = [selected[m] for m in settings["metrics"] if m in selected]
        certainty = confidence(available, len(settings["metrics"]), self.config["confidence_coverage_exponent"])
        opportunity = sum((100 - selected[m].value if m in self.inverse else selected[m].value) * weight
                          for m, weight in settings["metrics"].items() if m in selected)
        historical, historical_evidence = feedback(context, service, self.config)
        budget = min(settings["target_budget"], context.available_budget)
        if self.kind in ("GOOGLE_ADS", "META_ADS"):
            budget = min(budget, context.available_ad_budget)
        budget = int(budget * 100) / 100
        components = {"opportunity": opportunity, "evidence_strength": certainty * 100,
                      "historical_performance": historical, "expected_roi": historical,
                      "strategic_fit": 100 if service in context.constraints.service_preferences else 70,
                      "risk": {"LOW": 20, "MEDIUM": 50, "HIGH": 80}[self.risk],
                      "cost": 100 * budget / max(1, context.available_budget), "uncertainty": 100 * (1 - certainty)}
        result = StrategyEvaluation(self.kind, service, self.action,
                                    confidence=certainty, suggested_budget=budget, expected_cost=budget,
                                    reason=reason, risk_level=self.risk, components=components)
        result.evidence = [Evidence("MARKET_SIGNAL", f"{s.metric}: {s.value:g}/100 from {s.source}", signal_id=s.id,
                                    weight=settings["metrics"][s.metric]) for s in available] + historical_evidence
        used_ids = {s.id for s in available}
        result.evidence += [Evidence("INTELLIGENCE_REPORT", "Current report links supporting signals",
                                    intelligence_report_id=r["id"]) for r in context.reports
                            if r.get("status") == "CURRENT" and used_ids.intersection(r.get("signal_ids", []))]
        result.evidence += [Evidence("CLIENT_CONSTRAINT", "Budget, channel, risk and targeting constraints applied"),
                            Evidence("RULE", f"{self.kind} deterministic scoring policy v1")]
        result.parameters = {"budget_limit": budget, "currency": context.constraints.currency,
                             "locations": list(context.constraints.target_locations),
                             "industries": list(context.constraints.target_industries),
                             "brand_restrictions": list(context.constraints.brand_restrictions),
                             "subject_key": context.subject_key}
        if len(available) < len(settings["metrics"]):
            result.concerns.append("Missing metrics: " + ", ".join(m for m in settings["metrics"] if m not in selected))
        for metric in settings["required_metrics"]:
            if metric not in selected:
                result.blocking_reasons.append(f"Required metric missing: {metric}")
        if not available:
            result.blocking_reasons.append("No relevant market evidence")
        if budget < settings["minimum_budget"]:
            result.blocking_reasons.append("Insufficient available budget for minimum viable test")
        if historical < 50:
            result.concerns.append("Comparable historical outcomes are below target")
            result.confidence *= historical / 50
        result.score = score(components, self.config)
        return result

    def finish(self, context, result):
        c = context.constraints
        channel = result.recommendation_type
        if c.allowed_channels and channel not in c.allowed_channels:
            result.blocking_reasons.append("Channel not allowed")
        if channel in c.blocked_channels:
            result.blocking_reasons.append("Channel blocked")
        if {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[result.risk_level] > {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[c.risk_tolerance]:
            result.blocking_reasons.append("Risk exceeds client tolerance")
        if c.saturated:
            result.blocking_reasons.append("Client marked saturated")
        if result.confidence < c.minimum_confidence:
            result.blocking_reasons.append("Confidence below client minimum")
        if result.score < self.config["minimum_score"]:
            result.blocking_reasons.append("Opportunity below scoring threshold")
        result.eligible = not result.blocking_reasons
        result.priority = priority(result, self.config)
        return result
