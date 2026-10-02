"""devspace_services: outreach advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'devspace_services', 'outreach', {'prospect_fit': 30, 'audit_value': 30, 'contact_quality': 25, 'historical_response': 15}, ('prospect_fit', 'audit_value', 'contact_quality'), ('outreach_authorized', 'contact_permission'))
