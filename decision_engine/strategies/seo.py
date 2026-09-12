from .base import Strategy


class SEOStrategy(Strategy):
    kind, service, action = "SEO", "seo", "create_seo_plan"
    inverse = ("ranking_difficulty",)

    def evaluate(self, context):
        result = self.build(context, reason="Organic demand, keyword opportunity and content gaps support a longer-term SEO investment.")
        if context.constraints.time_horizon_months < 3:
            result.blocking_reasons.append("SEO requires a time horizon of at least three months")
        result.parameters["expected_lead_time_months"] = [3, 6]
        result.concerns.append("SEO is not immediate traffic; results typically require multiple months and are uncertain.")
        return self.finish(context, result)
