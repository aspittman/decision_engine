"""devspace_services: audit advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'devspace_services', 'audit', {'technical_issues': 35, 'conversion_issues': 30, 'business_impact': 25, 'evidence_quality': 10}, ('technical_issues', 'business_impact', 'evidence_quality'), ())
