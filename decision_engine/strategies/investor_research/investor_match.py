"""investor_research: investor_match advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'investor_research', 'investor_match', {'thesis_fit': 30, 'stage_fit': 25, 'sector_fit': 25, 'geography_fit': 20}, ('thesis_fit', 'stage_fit', 'sector_fit', 'geography_fit'), ('mandate_verified',))
