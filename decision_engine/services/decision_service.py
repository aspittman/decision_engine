from dataclasses import asdict
import json
from datetime import timedelta
import logging
import time
from decision_engine.engine.planner import rank_and_plan
from decision_engine.strategies import default_strategies
from decision_engine.strategies.no_action import no_action

TRIGGERS = ("NEW_INTELLIGENCE_REPORT", "SIGNIFICANT_SIGNAL_CHANGE", "MANUAL_REQUEST", "EXECUTION_COMPLETED", "SCHEDULED_REVIEW", "CLIENT_CONSTRAINT_CHANGED")
log = logging.getLogger(__name__)


class DecisionService:
    def __init__(self, repository, config, strategies=None):
        self.repository, self.config = repository, config
        self.strategies = strategies if strategies is not None else default_strategies(config)

    def run(self, organization_id, trigger="MANUAL_REQUEST"):
        trigger = trigger.upper()
        if trigger not in TRIGGERS:
            raise ValueError("Unknown decision trigger")
        run_id = self.repository.start_run(organization_id, trigger)
        started = time.monotonic()
        details = {"decision_run_id": run_id, "organization_id": organization_id}
        log.info("decision_started", extra={"context": details})
        try:
            context = self.repository.context(organization_id)
            evaluations, errors = [], []
            for strategy in self.strategies:
                try:
                    evaluations.append(strategy.evaluate(context))
                except Exception as error:
                    errors.append({"strategy": strategy.kind, "error_type": type(error).__name__})
            chosen, planning_reasons = rank_and_plan(evaluations, context)
            reasons = [f"{e.recommendation_type}: {', '.join(e.blocking_reasons)}" for e in evaluations if not e.eligible] + planning_reasons
            if not chosen and not any(r["recommendation_type"] == "NO_ACTION" for r in context.active):
                chosen = [no_action(reasons + (["Some strategies failed; review decision run"] if errors else []))]
            by_type = {e.recommendation_type: e.id for e in chosen}
            rows = []
            for rank, item in enumerate(chosen, 1):
                if not item.evidence:
                    raise ValueError("Recommendation lacks evidence")
                expiry = context.evaluated_at + timedelta(days=self.config["recommendation_ttl_days"])
                evidence_ids = {e.signal_id for e in item.evidence if e.signal_id}
                for signal in context.signals:
                    if signal.id in evidence_ids:
                        expiry = min(expiry, signal.observed_at + timedelta(days=self.config["max_signal_age_days"]))
                        if signal.expires_at is not None:
                            expiry = min(expiry, signal.expires_at)
                rows.append({"id": item.id, "organization_id": organization_id,
                             "recommendation_type": item.recommendation_type, "execution_service": item.execution_service,
                             "title": item.recommendation_type.replace("_", " ").title(),
                             "summary": item.reason, "reason": item.reason, "priority": item.priority,
                             "confidence_score": round(item.confidence, 4), "score": item.score,
                             "expected_value": item.expected_value, "expected_cost": item.expected_cost,
                             "suggested_budget": item.suggested_budget, "currency": context.constraints.currency,
                             "risk_level": item.risk_level, "status": "RECOMMENDED",
                             "expires_at": expiry.isoformat(),
                             "metadata": {"rank": rank, "action_type": item.action_type, "parameters": item.parameters,
                                          "concerns": item.concerns, "score_components": item.components,
                                          "execution_capability": context.capabilities.get(item.execution_service, "UNAVAILABLE")},
                             "evidence": [asdict(e) for e in item.evidence],
                             "dependencies": [by_type[t] for t in item.dependency_types]})
            summary = {"strategies_evaluated": len(self.strategies), "strategies_rejected": reasons,
                       "recommendations_created": len(rows), "errors": errors,
                       "confidence": [r["confidence_score"] for r in rows],
                       "duration_seconds": round(time.monotonic() - started, 3)}
            snapshot = {"signal_ids": [s.id for s in context.signals], "report_ids": [r["id"] for r in context.reports],
                        "execution_result_ids": [r.id for r in context.history], "constraints": asdict(context.constraints),
                        "active_recommendation_ids": [r["id"] for r in context.active], "scoring_config": self.config,
                        "evaluated_at": context.evaluated_at.isoformat(),
                        "signals": json.loads(json.dumps([asdict(s) for s in context.signals], default=str)),
                        "history": json.loads(json.dumps([asdict(r) for r in context.history], default=str)),
                        "reserved_budget": context.profile.get("reserved_budget", 0)}
            self.repository.finish_run(run_id, organization_id, rows, snapshot, summary, bool(errors))
            log.info("decision_completed", extra={"context": {**details, **summary}})
            return {"run_id": run_id, "status": "PARTIAL" if errors else "COMPLETED", "recommendations": rows}
        except Exception as error:
            # No raw exception messages: transports or custom strategies may contain private data.
            try:
                self.repository.fail_run(run_id, organization_id, type(error).__name__)
            except Exception:
                log.error("decision_run_failure_update_failed", extra={"context": details})
            log.error("decision_failed", extra={"context": {**details, "error_type": type(error).__name__}})
            raise
