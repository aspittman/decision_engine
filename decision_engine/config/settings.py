import json
import os
from dataclasses import dataclass, field
from importlib.resources import files
from decision_engine.models.contracts import number


def scoring_config(path=None):
    config = json.loads(open(path).read() if path else files("decision_engine.config").joinpath("scoring.json").read_text())
    for group in (config["weights"], config["penalties"]):
        for value in group.values():
            number(value, 0, 1)
    if abs(sum(config["weights"].values()) - 1) > 1e-6:
        raise ValueError("Scoring weights must sum to one")
    for strategy in config["strategies"].values():
        if abs(sum(strategy["metrics"].values()) - 1) > 1e-6:
            raise ValueError("Metric weights must sum to one")
        for value in strategy["metrics"].values():
            number(value, 0, 1)
        number(strategy["minimum_budget"], 0.01)
        number(strategy["target_budget"], strategy["minimum_budget"])
    for key in ("minimum_score", "high_priority_score", "critical_priority_score", "readiness_threshold"):
        number(config[key], 0, 100)
    for key in ("max_signal_age_days", "history_age_days", "history_prior_samples", "recommendation_ttl_days", "confidence_coverage_exponent"):
        number(config[key], 0.01)
    policy = config.get('domain_research_policy', {})
    if 'score_weights' in policy:
        from decision_engine.strategies.domain_merchant.scoring import WEIGHTS
        if set(policy['score_weights']) != set(WEIGHTS) or abs(sum(policy['score_weights'].values())-100) > 1e-6:
            raise ValueError('Domain score dimensions must sum to 100')
        for value in policy['score_weights'].values(): number(value, 0, 100)
    for key in ('minimum_comparable_sales','minimum_monthly_searches','minimum_potential_buyers','availability_max_age_hours','minimum_feedback_sample','full_demand_searches','full_buyer_count'):
        if key in policy: number(policy[key], .01)
    return config


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    service_role_key: str = field(repr=False)
    log_level: str = "INFO"



@dataclass(frozen=True)
class CRMSettings:
    api_url: str
    api_secret: str = field(repr=False)
    log_level: str = 'INFO'

    @classmethod
    def from_env(cls):
        url, secret = os.getenv('CRM_API_URL', ''), os.getenv('CRM_API_SECRET', '')
        if not url or not secret:
            raise ValueError('CRM_API_URL and CRM_API_SECRET are required')
        return cls(url.rstrip('/'), secret, os.getenv('LOG_LEVEL', 'INFO'))
