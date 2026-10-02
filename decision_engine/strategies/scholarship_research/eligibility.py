"""scholarship_research: eligibility advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'scholarship_research', 'eligibility', {'academic_fit': 30, 'location_fit': 25, 'study_fit': 25, 'financial_fit': 20}, ('academic_fit', 'location_fit', 'study_fit', 'financial_fit'), ('all_required_criteria_met', 'deadline_open'))
