from copy import deepcopy
from datetime import timedelta
import pytest
from decision_engine.models.contracts import uid
from decision_engine.services.registry import default_registry, SERVICES
from decision_engine.services.recommendations import recommend
from decision_engine.services.decision_service import DecisionService
from test_engine import MemoryRepository


def report(context, service, opportunities=None):
    kind, contract, _ = SERVICES[service]
    row = {'id': uid(), 'organization_id': context.organization_id, 'report_type': kind,
           'subject_key': service, 'subject_type': 'opportunity', 'is_test': False, 'status': 'CURRENT',
           'confidence_score': .95, 'created_at': context.evaluated_at.isoformat(), 'correlation_id': uid(),
           'metadata': {'service_id': service, 'research_contract': contract, 'opportunities': opportunities or []}}
    context.reports = [row]
    context.profile['organization_services'] = [{'service_key': service, 'is_enabled': True, 'config_json': {}}]
    return row


def domain(context):
    r = report(context, 'domain_merchant')
    date = context.evaluated_at.isoformat()
    r['metadata']['candidates'] = [{'domain': 'example.com', 'comparable_count': 10,
       'buyer_evidence': {'source_url': 'https://buyers.example', 'retrieved_at': date}, 'potential_buyer_count': 5,
       'keyword_demand': {'keywords': [{'search_volume': 1200}]},
       'trademark_screening': {'status': 'CLEAR', 'source_reference': 'authorized-screening', 'observed_at': date},
       'availability': {'checked_at': date, 'status': 'available', 'provider': 'GoDaddy',
                        'price_type': 'checkout_total', 'currency': 'USD', 'acquisition_price': 10},
       'decision_metrics': {k: {'value': 100, 'observed_at': date, 'source_reference': 'intelligence'}
                           for k in ('commercial_intent', 'historical_performance', 'trend', 'brandability')}}]
    return r


def rows(context, config, service, decision=None):
    return recommend(context, config, service, decision)[0]


def test_registry_and_safe_failures(context, config):
    registry = default_registry()
    assert {s for s, _ in registry.supported} == set(SERVICES)
    with pytest.raises(ValueError): registry.get('investors', 'MATCH_INVESTOR')
    with pytest.raises(ValueError): registry.get('domain_merchant', 'BUY_EVERYTHING')
    repo = MemoryRepository(context)
    with pytest.raises(ValueError): DecisionService(repo, config).run(context.organization_id, service_id='unknown')
    assert rows(context, config, 'domain_merchant') == []
    r = domain(context)
    for key, val in [('organization_id', uid()), ('is_test', True), ('created_at', (context.evaluated_at - timedelta(days=40)).isoformat())]:
        original = r[key]; r[key] = val
        assert rows(context, config, 'domain_merchant') == []
        r[key] = original


def test_domain_rules_confidence_and_history(context, config):
    r = domain(context)
    assert rows(context, config, 'domain_merchant')[0]['metadata']['recommendation'] == 'ACQUIRE'
    r['confidence_score'] = .1
    result = rows(context, config, 'domain_merchant')[0]
    assert result['score'] == 100 and result['confidence_score'] == .1
    assert result['metadata']['recommendation'] == 'RESEARCH_FURTHER'
    r['metadata']['candidates'][0]['trademark_screening']['status'] = 'CONFLICT'
    assert rows(context, config, 'domain_merchant')[0]['metadata']['recommendation'] == 'DO_NOT_ACQUIRE'
    r['metadata']['candidates'][0]['trademark_screening']['status'] = 'UNKNOWN'
    assert rows(context, config, 'domain_merchant')[0]['metadata']['recommendation'] == 'RESEARCH_FURTHER'
    assert result['metadata']['details']['historical_evidence']['status'] == 'INSUFFICIENT_DATA'


def demand(context, count=6):
    r = report(context, 'devspace_services', [{'id': 'api', 'opportunity_type': 'SERVICE', 'name': 'API',
        'evidence_ids': [str(i) for i in range(count)],
        'delivery': {'can_deliver': True, 'price': 2000, 'estimated_hours': 10, 'recurring_revenue_potential': True}}])
    domains = ['upwork.com', 'reddit.com', 'github.com']
    r['metadata']['evidence'] = [{'id': str(i), 'url': 'https://' + domains[i % 3] + '/' + str(i),
        'kind': 'buyer_request', 'text': 'API request ' + str(i), 'source': domains[i % 3],
        'buyer': {'name': 'buyer'}, 'observed_at': context.evaluated_at.isoformat()} for i in range(count)]
    return r


def test_service_demand_capability_and_independence(context, config):
    r = demand(context, 1)
    weak = rows(context, config, 'devspace_services')[0]
    r = demand(context)
    strong = rows(context, config, 'devspace_services')[0]
    assert weak['confidence_score'] < strong['confidence_score']
    assert strong['metadata']['recommendation'] == 'TEST_SERVICE'
    r['metadata']['opportunities'][0]['delivery']['can_deliver'] = False
    assert rows(context, config, 'devspace_services')[0]['metadata']['recommendation'] == 'DO_NOT_TEST'
    r['metadata']['opportunities'][0]['delivery'].pop('can_deliver')
    assert rows(context, config, 'devspace_services')[0]['metadata']['recommendation'] == 'RESEARCH_FURTHER'
    assert rows(context, config, 'devspace_services', 'OFFER_SERVICE')[0]['metadata']['recommendation'] == 'NEEDS_INFORMATION'


def test_client_observations_and_missing_evidence(context, config):
    item = {'id': 'client', 'status': 'REVIEW', 'fit_score': 100, 'fit_confidence': .7,
            'evidence': [], 'findings': [{'metric': 'website_http_status', 'value': 503,
            'source_reference': 'https://client.example', 'observed_at': context.evaluated_at.isoformat()}]}
    report(context, 'devspace_clients', [item])
    result = rows(context, config, 'devspace_clients')[0]
    assert result['metadata']['recommendation'] == 'REVIEW_WEBSITE_AVAILABILITY' and result['priority'] == 'HIGH'
    item['findings'][0]['value'] = 200
    minor = rows(context, config, 'devspace_clients')[0]
    assert minor['score'] < result['score'] and minor['priority'] == 'LOW'
    item['findings'] = []
    assert rows(context, config, 'devspace_clients') == []


def product(context, service):
    scholarship = service == 'scholarship_research'
    attrs = {'gpa': 3.5, 'residence_region': 'Utah', 'study_level': 'undergraduate', 'field_of_study': 'CS', 'currency': 'USD'} if scholarship else {'industry': 'SaaS', 'stage': 'Seed', 'country': 'US', 'funding_amount': 500000, 'currency': 'USD'}
    criteria = [('gpa', 'gte', 3), ('residence_region', 'eq', 'Utah'), ('study_level', 'eq', 'undergraduate'), ('field_of_study', 'eq', 'CS')] if scholarship else [('industry', 'eq', 'SaaS'), ('stage', 'eq', 'Seed'), ('country', 'eq', 'US')]
    facts = {'requirements_complete' if scholarship else 'mandate_complete': {'value': True},
             'accepting_applications': {'value': True}, 'currency': {'value': 'USD'}}
    facts.update({'award_min': {'value': 5000}, 'deadline': {'value': (context.evaluated_at + timedelta(days=40)).isoformat()}} if scholarship else {'check_min': {'value': 100000}, 'check_max': {'value': 1000000}, 'current_activity': {'value': 'active'}, 'last_investment_date': {'value': context.evaluated_at.isoformat()}, 'portfolio_companies': {'value': ['a', 'b', 'c', 'd', 'e']}})
    item = {'id': 'product', 'name': 'Opportunity', 'url': 'https://issuer.example', 'status': 'CURRENT',
            'source_status': 'ISSUER_PAGE_VERIFIED', 'normalization_reviewed': True, 'verified_at': context.evaluated_at.isoformat(),
            'facts': facts, 'criteria': [{'field': f, 'operator': op, 'value': v, 'source_url': 'https://issuer.example', 'quote': 'Verified requirement'} for f, op, v in criteria]}
    r = report(context, service, [item])
    context.profile['organization_services'][0]['config_json'] = {'matching_profiles': [{'id': uid(), 'attributes': attrs}]}
    return r, item, attrs


@pytest.mark.parametrize('service,field,invalid,dimension,rejection', [
    ('scholarship_research', 'gpa', 2, 'eligibility', 'INELIGIBLE'),
    ('investor_research', 'stage', 'Series A', 'compatibility', 'INCOMPATIBLE')])
def test_matching_hard_constraints_and_soft_scores(context, config, service, field, invalid, dimension, rejection):
    r, item, attrs = product(context, service)
    result = rows(context, config, service)[0]
    assert result['metadata']['details'][dimension] == 'CONFIRMED'
    assert result['metadata']['details']['match'] == 'STRONG'
    attrs[field] = invalid
    result = rows(context, config, service)[0]
    assert result['metadata']['details'][dimension] == rejection
    assert result['score'] == 100  # A hard rejection is never hidden in the soft score.
    attrs.pop(field)
    assert rows(context, config, service)[0]['metadata']['details'][dimension] == 'NEEDS_INFORMATION'
    item['status'] = 'SOURCE_CONFLICT'
    assert rows(context, config, service)[0]['confidence_score'] == 0


def test_investor_missing_check_size(context, config):
    _, item, _ = product(context, 'investor_research')
    item['facts'].pop('check_max')
    assert rows(context, config, 'investor_research')[0]['metadata']['details']['compatibility'] == 'NEEDS_INFORMATION'


@pytest.mark.parametrize('service', ['scholarship_research', 'investor_research'])
def test_missing_matching_profile_has_an_explicit_evidence_backed_outcome(context, config, service):
    r, _, _ = product(context, service)
    context.profile['organization_services'][0]['config_json']['matching_profiles'] = []
    result = rows(context, config, service)[0]
    assert result['metadata']['recommendation'] == 'NEEDS_INFORMATION'
    assert result['score'] == 0 and result['confidence_score'] == 0
    assert result['evidence'][0]['intelligence_report_id'] == r['id']
    assert 'Supplied matching profile' in result['metadata']['details']['missing_information']


def test_lineage_workflow_persistence_business_rejection(context, config):
    r = domain(context)
    identity = {'organization_id': context.organization_id, 'service_id': 'domain_merchant', 'workflow_run_id': 'existing-workflow',
                'parent_run_id': 'existing-parent', 'correlation_id': r['correlation_id'], 'source_engine': 'mmonolith'}
    r['metadata']['workflow_context'] = identity
    r['metadata']['candidates'][0]['trademark_screening']['status'] = 'CONFLICT'
    repo = MemoryRepository(context)
    outcome = DecisionService(repo, config).run(context.organization_id, service_id='domain_merchant')
    row = outcome['recommendations'][0]
    assert outcome['status'] == 'COMPLETED'
    assert row['metadata']['recommendation'] == 'DO_NOT_ACQUIRE'
    assert row['metadata']['workflow_context']['workflow_run_id'] == 'existing-workflow'
    assert row['metadata']['workflow_context']['parent_run_id'] == 'existing-parent'
    assert row['evidence'][0]['intelligence_report_id'] == r['id']
    assert row['execution_service'] is None and row['metadata']['execution_authorized'] is False
    assert row['metadata']['requires_approval'] is True
    assert repo.saved[2][0]['id'] == row['id']
    with pytest.raises(ValueError): recommend(context, config, 'domain_merchant', workflow_context={**identity, 'workflow_run_id': 'unrelated'})
    context.active = [row]
    assert rows(context, config, 'domain_merchant') == []


def test_transport_failure_does_not_fabricate_recommendation(context, config):
    class Unavailable(MemoryRepository):
        def context(self, org): raise RuntimeError('CRM unavailable')
    repo = Unavailable(context)
    with pytest.raises(RuntimeError): DecisionService(repo, config).run(context.organization_id, service_id='domain_merchant')
    assert repo.saved is None


def test_domain_outreach_feedback_has_a_sample_floor(context, config):
    r = domain(context)
    c = r['metadata']['candidates'][0]
    c['internal_performance'] = {'sent': 2, 'negative_responses': 2, 'positive_responses': 0}
    assert rows(context, config, 'domain_merchant', 'STOP_OUTREACH')[0]['metadata']['recommendation'] == 'NEEDS_INFORMATION'
    c['internal_performance']['sent'] = 40
    assert rows(context, config, 'domain_merchant', 'STOP_OUTREACH')[0]['metadata']['recommendation'] == 'STOP_OUTREACH'


def test_monitor_receipt_contains_decision_lineage(tmp_path, monkeypatch, context, config):
    from decision_engine.monitoring_receipts import recommendation_writes
    import json
    r = domain(context)
    r['workflow_run_id'] = 'upstream'
    destination = tmp_path / 'events.jsonl'
    monkeypatch.setenv('DEVSPACE_CAPABILITY_EVENTS', str(destination))
    recommendation_writes(context.organization_id, rows(context, config, 'domain_merchant'))
    event = json.loads(destination.read_text())
    assert event['status'] == 'COMPLETED' and event['workflow_run_id'] == 'upstream'
    assert event['metadata']['decision_type'] == 'ACQUIRE_DOMAIN'
    assert event['metadata']['intelligence_report_id'] == r['id']
