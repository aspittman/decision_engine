from .base import Strategy


class DomainAcquisitionStrategy(Strategy):
    kind, service, action = "DOMAIN_ACQUISITION", "domain_merchant", "investigate_domain_category"
    risk = "MEDIUM"

    def evaluate(self, context):
        result = self.build(context, reason="Comparable sales, commercial intent and buyer density justify investigating this domain category.")
        result.parameters.update({"investigation_only": True, "purchase_authorized": False})
        result.concerns.append("Category evidence is not a domain valuation; any purchase requires a separate approval.")
        return self.finish(context, result)
