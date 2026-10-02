# Service strategies and production evidence review

The engine uses deterministic policies, not an LLM or an autonomous purchasing agent. Existing marketing strategies and the `strategies.domain_acquisition` import remain compatible. Domain acquisition implementation is now in `strategies/domain_merchant/acquisition.py`.

Acquisition priority uses demand 20, commercial intent 20, comparable sales 15, buyer density 15, historical performance 15, trend 10 and brandability 5. Configuration lives in `decision_engine/config/scoring.json`. Demand reaches 20 points at 1,000 monthly searches; comparable sales reach 15 at three observations; buyer density reaches 15 at three observed buyers. Optional dimensions use attributed 0–100 `decision_metrics` with source references and observation dates. Missing dimensions earn zero points and are listed as unknown; confidence is separate from score. This is an investigation-priority score, not a resale probability or valuation.

Penalties are trademark conflict 100, above-cap acquisition price 20, observed weak buyer pool 15, and poor outreach history with sufficient samples 15. Trademark conflict and existing evidence/price/client constraints remain vetoes regardless of score. Unknown trademark status is not clearance. Every recommendation still has `purchase_authorized:false`.

Service modules:

- Domain Merchant: acquisition, observed comparable pricing statistics, outreach readiness, and zero-spend evidence review.
- DevSpace Services: prospect fit, audit importance, outreach readiness.
- Scholarship Research: source quality and eligibility, including explicit criteria/deadline gates.
- DevSpace Clients: opportunity and optimization within the client's scope.
- Investor Research: mandate matching and opportunity diligence.

The non-acquisition assessments are stored in `decision_runs.output_summary.service_assessments`. They are advisory; creating a strategy file does not register an execution adapter or mark an unimplemented service operational. Inputs must be normalized `market_signals` with `unit:score_0_100`, matching `organization_id`, metadata `service_id` and `subject_key`, a source and a fresh date. The module defines its metric weights and mandatory gates. Missing input is UNKNOWN, and a service not enabled for the organization is NOT_CONFIGURED. Investor scores are research prioritization, not investment instructions.

Domain candidate score breakdowns, unknowns, penalties and comparable price summaries are included in `domain_candidate_decisions`. General strategy eligibility/reasons are in `strategy_decisions`. The existing decision-run input snapshot retains actual report IDs.

A separate `MARKET_RESEARCH` / `review_domain_evidence` strategy enables a useful first loop even when acquisition evidence is incomplete. It recommends review of a fresh report with candidates only when CRM explicitly advertises the adapter as ready. It sets zero budget and prohibits external calls, purchases and outreach. Its confidence describes the existence of reviewable records, not acquisition confidence. Completed reviews of the same exact report are deduplicated; existing active recommendations are respected.

See dsmonitor `docs/DECISION_STRATEGY_UPGRADE.md` for migration, rollout and verification steps. No production readiness flag is changed by installing this code.
