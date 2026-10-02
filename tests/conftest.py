from dataclasses import replace
from datetime import timedelta
import pytest
from decision_engine.config.settings import scoring_config
from decision_engine.models.contracts import Context, Constraints, Signal, now, uid


@pytest.fixture
def config():
    return scoring_config()


@pytest.fixture
def context():
    org = uid()
    return Context(org, {"id": org, "name": "ABC Roofing"},
                   Constraints.parse({"monthly_marketing_budget": 1500, "max_domain_acquisition_price": 12, "max_ad_spend": 1000,
                      "minimum_confidence": 0.65, "risk_tolerance": "MEDIUM", "target_locations": ["Salt Lake City, UT"],
                      "email_reputation_healthy": True, "maximum_cost_per_lead": 50}), [], [], [], [], {})


def add_signals(context, values, confidence=0.95):
    for metric, value in values.items():
        context.signals.append(Signal(uid(), context.organization_id, metric, value, confidence,
                                      "fixture_research", context.evaluated_at - timedelta(hours=1)))
    return context


ROOFING = {"search_demand": 95, "commercial_intent": 95, "competition": 15, "landing_page_readiness": 90}
SAAS = {"prospect_volume": 95, "contactability": 90, "industry_fit": 95, "offer_clarity": 90}
RESTAURANT = {"organic_demand": 90, "keyword_opportunity": 85, "ranking_difficulty": 20, "content_gaps": 90}
DOMAIN = {"comparable_domain_sales": 95, "commercial_intent": 90, "buyer_density": 95, "domain_market_demand": 90}
