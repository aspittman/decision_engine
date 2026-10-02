"""domain_merchant: outreach advisory policy; never authorizes execution."""
from ..assessment import assess

def evaluate(context):
    return assess(context, 'domain_merchant', 'outreach', {'buyer_fit': 35, 'contact_quality': 25, 'offer_relevance': 25, 'historical_response': 15}, ('buyer_fit', 'contact_quality', 'offer_relevance'), ('domain_owned', 'outreach_authorized', 'contact_permission'))
