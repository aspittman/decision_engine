from ..base import Strategy


class LandingPageStrategy(Strategy):
    kind, service, action = "LANDING_PAGE_OPTIMIZATION", "landing_page", "optimize_landing_page"
    inverse = ("landing_page_readiness",)

    def evaluate(self, context):
        result = self.build(context, reason="Measured conversion and usability problems justify improving the landing page before scaling traffic.")
        selected = self.signals(context)
        readiness = selected.get("landing_page_readiness")
        if readiness and readiness.value >= self.config["readiness_threshold"] and not any(selected.get(m) and selected[m].value >= self.config["readiness_threshold"] for m in ("missing_cta", "broken_forms", "mobile_issues")):
            result.blocking_reasons.append("No material landing-page problem")
        result.parameters["urgent"] = bool(selected.get("broken_forms") and selected["broken_forms"].value >= 90)
        return self.finish(context, result)
