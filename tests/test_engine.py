from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import pytest
from conftest import add_signals, ROOFING, SAAS, RESTAURANT, DOMAIN
from decision_engine.engine.scoring import score, confidence
from decision_engine.engine.planner import rank_and_plan
from decision_engine.models.contracts import Constraints, Context, ExecutionResult, uid
from decision_engine.services.feedback_service import feedback
from decision_engine.services.decision_service import DecisionService
from decision_engine.strategies import default_strategies
from decision_engine.strategies.google_ads import GoogleAdsStrategy
from decision_engine.strategies.outreach import OutreachStrategy
from decision_engine.strategies.landing_pages import LandingPageStrategy


class MemoryRepository:
    def __init__(self, context):
        self.loaded = context
        self.saved = None
        self.failed = False
    def start_run(self, org, trigger):
        return uid()
    def context(self, org):
        return self.loaded
    def finish_run(self, *args):
        self.saved = args
    def fail_run(self, *args):
        self.failed = True


def test_scoring_and_confidence_separate(config, context):
    components = dict.fromkeys(config["weights"], 100) | dict.fromkeys(config["penalties"], 0)
    assert score(components, config) == 100
    components.update(dict.fromkeys(config["weights"], 0), **dict.fromkeys(config["penalties"], 100))
    assert score(components, config) == 0
    add_signals(context, ROOFING)
    assert confidence(context.signals, 4) == 0.95
    assert confidence(context.signals[:1], 4) < 0.5
    assert confidence([], 4) == 0


@pytest.mark.parametrize("values,kind", [(ROOFING,"GOOGLE_ADS"),(SAAS,"OUTREACH"),(RESTAURANT,"SEO"),(DOMAIN,"DOMAIN_ACQUISITION")])
def test_realistic_profiles(config, context, values, kind):
    add_signals(context, values)
    target = next(s for s in default_strategies(config) if s.kind == kind)
    result = target.evaluate(context)
    assert result.eligible, result.blocking_reasons
    assert result.score >= 65
    assert any(e.signal_id for e in result.evidence)
    assert result.parameters["budget_limit"] <= context.constraints.monthly_marketing_budget
    if kind == "DOMAIN_ACQUISITION":
        assert result.parameters["purchase_authorized"] is False


@pytest.mark.parametrize("budget", [0, 10, 99, 300])
def test_budget(config, context, budget):
    add_signals(context, ROOFING)
    context.constraints = replace(context.constraints, monthly_marketing_budget=budget)
    result = GoogleAdsStrategy(config).evaluate(context)
    assert result.suggested_budget <= budget
    assert result.eligible == (budget >= 100)


def test_blocked_ads(config, context):
    add_signals(context, ROOFING)
    context.constraints = replace(context.constraints, blocked_channels=["GOOGLE_ADS"])
    assert not GoogleAdsStrategy(config).evaluate(context).eligible


def test_missing_and_stale_evidence(config, context):
    add_signals(context, ROOFING)
    context.signals = [replace(s, observed_at=context.evaluated_at-timedelta(days=40)) for s in context.signals]
    assert not GoogleAdsStrategy(config).evaluate(context).eligible
    context.signals = [replace(s, observed_at=context.evaluated_at+timedelta(days=1)) for s in context.signals]
    assert not GoogleAdsStrategy(config).evaluate(context).eligible


def test_dependency_and_shared_budget(config, context):
    add_signals(context, ROOFING | {"landing_page_readiness": 15, "missing_cta": 95,"broken_forms":95,"mobile_issues":90})
    evaluations = [GoogleAdsStrategy(config).evaluate(context), LandingPageStrategy(config).evaluate(context)]
    selected, _ = rank_and_plan(evaluations, context)
    assert [e.recommendation_type for e in selected] == ["LANDING_PAGE_OPTIMIZATION","GOOGLE_ADS"]
    assert selected[1].priority == "MEDIUM"
    context.constraints = replace(context.constraints, monthly_marketing_budget=300)
    selected, reasons = rank_and_plan(evaluations, context)
    assert sum(e.suggested_budget for e in selected) <= 300
    assert reasons
    selected, reasons = rank_and_plan(evaluations[:1], context)
    assert not selected and reasons


def test_no_action_and_run_evidence(config, context):
    repository = MemoryRepository(context)
    result = DecisionService(repository, config).run(context.organization_id)
    assert result["status"] == "COMPLETED"
    assert result["recommendations"][0]["recommendation_type"] == "NO_ACTION"
    assert result["recommendations"][0]["reason"]
    assert result["recommendations"][0]["evidence"]
    assert repository.saved


def test_partial_failure(config, context):
    class Broken:
        kind = "BROKEN"
        def evaluate(self, context):
            raise RuntimeError("private customer text")
    add_signals(context, SAAS)
    repo = MemoryRepository(context)
    result = DecisionService(repo, config, [Broken(), OutreachStrategy(config)]).run(context.organization_id)
    assert result["status"] == "PARTIAL"
    assert result["recommendations"][0]["recommendation_type"] == "OUTREACH"
    assert "private customer text" not in str(repo.saved)


def test_feedback(config, context):
    def history(cost, leads):
        return ExecutionResult(uid(),context.organization_id,"google_ads",cost,None,{"leads":leads},context.evaluated_at,"USD","organization")
    context.history = [history(190,8)]
    good, evidence = feedback(context,"google_ads",config)
    context.history = [history(220,1)]
    bad, _ = feedback(context,"google_ads",config)
    assert good > 50 > bad and evidence[0].execution_result_id
    add_signals(context, ROOFING)
    assert GoogleAdsStrategy(config).evaluate(context).confidence < 0.95
    context.history = [replace(history(190,8), subject_key="different-keyword")]
    assert feedback(context,"google_ads",config) == (50, [])


def test_tenant_isolation(context):
    add_signals(context, ROOFING)
    with pytest.raises(ValueError, match="Cross-organization"):
        replace(context, signals=[replace(context.signals[0],organization_id=uid())])


@pytest.mark.parametrize("data", [{"monthly_marketing_budget":-1},{"minimum_confidence":float("nan")}, {"allowed_channels":"GOOGLE_ADS"}, {"made_up_limit":12}, {"saturated":"false"}])
def test_invalid_constraints(data):
    with pytest.raises(ValueError):
        Constraints.parse(data)


def test_duplicate_suppression_and_ranking(config, context):
    add_signals(context, ROOFING | SAAS)
    evaluations = [s.evaluate(context) for s in default_strategies(config)]
    selected,_ = rank_and_plan(evaluations,context)
    assert [s.score for s in selected] == sorted([s.score for s in selected],reverse=True)
    context.active = [{"organization_id":context.organization_id,"recommendation_type":"OUTREACH"}]
    selected,_ = rank_and_plan(evaluations,context)
    assert not any(s.recommendation_type == "OUTREACH" for s in selected)


def test_seo_short_horizon_and_risk(config, context):
    add_signals(context, RESTAURANT | DOMAIN)
    context.constraints = replace(context.constraints, time_horizon_months=1, risk_tolerance="LOW")
    results = {s.kind:s.evaluate(context) for s in default_strategies(config)}
    assert not results["SEO"].eligible
    assert not results["DOMAIN_ACQUISITION"].eligible


def test_recommendation_expires_with_evidence(config, context):
    add_signals(context, SAAS)
    expiration = context.evaluated_at + timedelta(hours=2)
    context.signals = [replace(s,expires_at=expiration) for s in context.signals]
    result = DecisionService(MemoryRepository(context),config).run(context.organization_id)
    assert result['recommendations'][0]['expires_at'] == expiration.isoformat()


def test_active_reservations_reduce_budget(config, context):
    add_signals(context, ROOFING)
    context.profile['reserved_budget'] = 1450
    assert not GoogleAdsStrategy(config).evaluate(context).eligible


def test_missing_required_metric_blocks_ads(config, context):
    add_signals(context,{k:v for k,v in ROOFING.items() if k!='search_demand'})
    assert not GoogleAdsStrategy(config).evaluate(context).eligible
