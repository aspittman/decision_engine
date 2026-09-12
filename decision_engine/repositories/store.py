"""All tenant-sensitive reads carry an explicit organization filter."""
from datetime import timedelta
from uuid import UUID
from decision_engine.models.contracts import Context, Constraints, Signal, ExecutionResult, now, timestamp


class Repository:
    def __init__(self, client, config):
        self.client, self.config = client, config

    def organizations(self):
        return self.client.rows("organizations")

    def scoped(self, table, organization_id, filters=None):
        UUID(organization_id)
        rows = self.client.rows(table, {**(filters or {}), "organization_id": "eq." + organization_id})
        if any(row.get("organization_id") != organization_id for row in rows):
            raise ValueError("Cross-organization response rejected")
        return rows

    def context(self, organization_id):
        UUID(organization_id)
        profiles = self.client.rows("organizations", {"id": "eq." + organization_id})
        if len(profiles) != 1 or profiles[0]["id"] != organization_id:
            raise ValueError("Organization not found")
        constraints = self.scoped("decision_constraints", organization_id)
        policy = Constraints.parse(constraints[0]["constraints"]) if constraints else Constraints()
        at = now()
        signals = self.scoped("market_signals", organization_id, {"observed_at": "gte." + (at - timedelta(days=self.config["max_signal_age_days"])).isoformat()})
        # Only normalized score signals are accepted; raw monetary/count values remain in storage.
        parsed = [Signal.parse(s) for s in signals if s.get("unit") == "score_0_100" and s.get("value_numeric") is not None
                  and timestamp(s["observed_at"]) <= at and (not s.get("expires_at") or timestamp(s["expires_at"]) > at)]
        reports = self.scoped("intelligence_reports", organization_id, {"status": "eq.CURRENT"})
        links = self.scoped("intelligence_report_signals", organization_id)
        for report in reports:
            report["signal_ids"] = [r["signal_id"] for r in links if r["report_id"] == report["id"]]
        history = self.scoped("execution_results", organization_id, {"status": "eq.COMPLETED", "completed_at": "gte." + (at - timedelta(days=self.config["history_age_days"])).isoformat()})
        active = self.scoped("recommendations", organization_id, {"status": "in.(RECOMMENDED,APPROVED,MODIFIED,QUEUED,EXECUTING)"})
        active = [r for r in active if r["status"] in ("QUEUED", "EXECUTING") or not r.get("expires_at") or timestamp(r["expires_at"]) > at]
        requests = self.scoped("execution_requests", organization_id)
        month_start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        reserved = [r for r in requests if r["status"] != "CANCELLED" and
                    (r["status"] in ("APPROVED", "QUEUED", "RUNNING") or timestamp(r["created_at"]) >= month_start)]
        pending = [r for r in active if r["status"] in ("RECOMMENDED", "APPROVED", "MODIFIED")]
        profiles[0]["reserved_budget"] = sum(float(r["requested_parameters"]["budget_limit"]) for r in reserved) + sum(float(r.get("suggested_budget") or 0) for r in pending)
        profiles[0]["reserved_ad_budget"] = sum(float(r["requested_parameters"]["budget_limit"]) for r in reserved if r["execution_service"] in ("google_ads", "meta_ads")) + sum(float(r.get("suggested_budget") or 0) for r in pending if r["recommendation_type"] in ("GOOGLE_ADS", "META_ADS"))
        capabilities = {r["service_key"]: r["status"] for r in self.client.rows("execution_capabilities")}
        return Context(organization_id, profiles[0], policy, parsed, reports,
                       [ExecutionResult.parse(r) for r in history], active, capabilities, at)

    def start_run(self, organization_id, trigger):
        return self.client.rpc("de_start_run", {"p_org": organization_id, "p_trigger": trigger})

    def finish_run(self, run_id, organization_id, recommendations, snapshot, summary, partial):
        return self.client.rpc("de_finish_run", {"p_run": run_id, "p_org": organization_id,
                               "p_recommendations": recommendations, "p_snapshot": snapshot,
                               "p_summary": summary, "p_partial": partial})

    def fail_run(self, run_id, organization_id, error):
        return self.client.rpc("de_fail_run", {"p_run": run_id, "p_org": organization_id, "p_error": error})

    def dispatch(self, organization_id):
        return self.client.rpc("de_queue_approved", {"p_org": organization_id})
