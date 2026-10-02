"""All service assessments are recorded even when evidence is insufficient."""
from importlib import import_module

POLICIES = ['scholarship_research/matching', 'investor_research/matching', 'devspace_services/demand', 'domain_merchant/outreach', 'devspace_services/prospect', 'devspace_services/audit', 'devspace_services/outreach', 'scholarship_research/quality', 'scholarship_research/eligibility', 'devspace_clients/opportunity', 'devspace_clients/optimization', 'investor_research/investor_match', 'investor_research/opportunity']

def assess_services(context):
    results=[]
    for path in POLICIES:
        try:
            results.append(import_module("decision_engine.strategies."+path.replace("/",".")).evaluate(context))
        except (ValueError, TypeError, KeyError):
            service,name=path.split("/")
            results.append({"service_id":service,"strategy":name,"status":"UNKNOWN","reason":"Invalid or incomplete assessment input","execution_authorized":False})
    return results
