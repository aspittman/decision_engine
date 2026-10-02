"""scholarship_research: quality advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'scholarship_research', 'quality', {'source_authority': 35, 'award_verifiability': 25, 'freshness': 25, 'application_clarity': 15}, ('source_authority', 'award_verifiability', 'freshness'), ('source_verified',))
