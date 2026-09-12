from .base import Strategy


class OutreachStrategy(Strategy):
    kind, service, action = "OUTREACH", "devspace_outreach", "prepare_outreach"

    def evaluate(self, context):
        result = self.build(context, service="apollo_outreach" if "apollo_outreach" in context.constraints.service_preferences else self.service, reason="Prospect availability, contactability, industry fit and offer clarity support an outreach test.")
        if not context.constraints.email_reputation_healthy:
            result.blocking_reasons.append("Email reputation not confirmed healthy")
        if "apollo_outreach" in context.constraints.service_preferences:
            result.execution_service = "apollo_outreach"
        result.parameters["requires_recipient_review"] = True
        return self.finish(context, result)
