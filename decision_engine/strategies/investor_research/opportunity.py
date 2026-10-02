"""investor_research: opportunity advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'investor_research', 'opportunity', {'business_quality': 25, 'traction': 25, 'market_evidence': 25, 'diligence_quality': 25}, ('business_quality', 'traction', 'market_evidence', 'diligence_quality'), ('diligence_complete',))
