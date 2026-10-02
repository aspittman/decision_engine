"""devspace_clients: optimization advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'devspace_clients', 'optimization', {'measured_gap': 35, 'expected_impact': 25, 'implementation_feasibility': 25, 'measurement_quality': 15}, ('measured_gap', 'implementation_feasibility', 'measurement_quality'), ('within_client_scope',))
