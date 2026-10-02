"""devspace_clients: opportunity advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'devspace_clients', 'opportunity', {'client_need': 30, 'expected_impact': 30, 'feasibility': 25, 'evidence_quality': 15}, ('client_need', 'expected_impact', 'feasibility'), ('within_client_scope',))
