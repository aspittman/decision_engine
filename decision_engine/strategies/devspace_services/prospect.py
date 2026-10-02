"""devspace_services: prospect advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'devspace_services', 'prospect', {'service_fit': 35, 'need': 30, 'contact_quality': 20, 'commercial_intent': 15}, ('service_fit', 'need', 'contact_quality'), ())
