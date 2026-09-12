from .base import Strategy


class GoogleAdsStrategy(Strategy):
    kind, service, action = "GOOGLE_ADS", "google_ads", "create_search_campaign"
    inverse = ("competition",)

    def evaluate(self, context):
        result = self.build(context, reason="Commercial search demand, intent, competition and historical performance support a capped search campaign test.")
        readiness = self.signals(context).get("landing_page_readiness")
        if readiness is None:
            result.blocking_reasons.append("Landing-page readiness is unknown")
        elif readiness.value < self.config["readiness_threshold"]:
            result.dependency_types.append("LANDING_PAGE_OPTIMIZATION")
            result.concerns.append("Landing-page work and a fresh readiness assessment are required before advertising.")
        if not context.constraints.target_locations:
            result.blocking_reasons.append("Geographic targeting is missing")
        result.parameters["monthly_budget"] = result.suggested_budget
        return self.finish(context, result)
