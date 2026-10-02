"""Canonical service/decision dispatch, separate from execution capabilities."""
from importlib import import_module

SERVICES = {
    'domain_merchant': ('DOMAIN_MARKET', 'domain-evidence-v1', 'ACQUIRE_DOMAIN'),
    'devspace_services': ('SERVICE_DEMAND', 'service-demand-v1', 'TEST_SERVICE'),
    'devspace_clients': ('CLIENT_RESEARCH', 'client-research-v1', 'IDENTIFY_OPPORTUNITY'),
    'scholarship_research': ('SCHOLARSHIP_RESEARCH', 'product-research-v1', 'MATCH_SCHOLARSHIP'),
    'investor_research': ('INVESTOR_RESEARCH', 'product-research-v1', 'MATCH_INVESTOR'),
}
# Only aliases already used by the existing ecosystem are accepted.
ALIASES = {'DOMAIN_ACQUISITION': 'ACQUIRE_DOMAIN', 'CHECK_FIT': 'CHECK_COMPATIBILITY',
           'RANK_SCHOLARSHIP': 'RANK_OPPORTUNITY'}
SERVICE_ALIASES = {'domain': 'domain_merchant', 'scholarship': 'scholarship_research',
                   'scholorship_research': 'scholarship_research', 'devspace-services': 'devspace_services',
                   'crm-companies': 'devspace_clients', 'crm_business': 'devspace_clients'}


def canonical_service(service_id):
    return SERVICE_ALIASES.get(service_id, service_id)


class StrategyRegistry:
    def __init__(self):
        self._strategies = {}

    def register(self, service_id, decision_type, strategy):
        if service_id not in SERVICES or (service_id, decision_type) in self._strategies:
            raise ValueError('Invalid or duplicate strategy registration')
        self._strategies[service_id, decision_type] = strategy

    def get(self, service_id, decision_type):
        try:
            return self._strategies[canonical_service(service_id), ALIASES.get(decision_type, decision_type)]
        except KeyError:
            raise ValueError('Unsupported service or decision type') from None

    @property
    def supported(self):
        return sorted(self._strategies)


def default_registry():
    registry = StrategyRegistry()
    for service in SERVICES:
        module = import_module('decision_engine.services.' + service)
        for decision in module.DECISIONS:
            registry.register(service, decision, module.evaluate)
    return registry
