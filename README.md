# DevSpace Decision Engine

A deterministic Python strategy layer that turns organization intelligence into ranked, evidence-linked recommendations. It writes recommendations to Supabase and creates execution requests **only after CRM admin approval**. It has no email, advertising, domain-purchase, website-editing, or LLM execution clients.

```mermaid
flowchart TD
    M[MMonolith: what is happening?] --> S[Supabase / CRM: what do we know?]
    S --> D[Decision Engine: what should we do?]
    D --> R[Recommendations + evidence]
    R --> C[CRM admin: approve / modify / reject]
    C --> Q[Validated execution requests]
    Q --> O[DevSpace One: execute approved work]
    O --> E[Execution results]
    E --> S
    S --> M
```

The implementation is ready for staging integration. The migration is additive to the inspected CRM schema; it has **not** been applied to a live database. CRM screens, MMonolith publishing, and DevSpace One consumption need the adapters in [docs/integration.md](docs/integration.md). No neighboring repositories were changed.

## Local setup

Python 3.10+; the runtime uses the standard library and has no third-party dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
cp .env.example .env
# Edit .env with backend credentials, then export them:
set -a
source .env
set +a
python main.py --organization 11111111-1111-4111-8111-111111111111
python main.py --all
python main.py --trigger scheduled_review
python main.py --organization 11111111-1111-4111-8111-111111111111 --queue-approved
```

`.env` is not automatically loaded. `SUPABASE_URL` must use HTTPS; `SUPABASE_SERVICE_ROLE_KEY` stays server-side. `LOG_LEVEL` defaults to INFO. `DECISION_SCORING_FILE` optionally selects a complete JSON scoring configuration. `CRM_API_URL` and `CRM_API_SECRET` are reserved for a future gateway adapter; the MVP uses Supabase directly because the existing CRM has no generic decision endpoints.

`--trigger scheduled_review` defaults to all organizations; other triggers require `--organization` or `--all`. Triggers: `NEW_INTELLIGENCE_REPORT`, `SIGNIFICANT_SIGNAL_CHANGE`, `MANUAL_REQUEST`, `EXECUTION_COMPLETED`, `SCHEDULED_REVIEW`, `CLIENT_CONSTRAINT_CHANGED`. Names are case-insensitive. `--queue-approved` performs the approval handoff only. Exit code 1 means at least one failed/partial organization run; other organizations still run.

For cron, provide environment variables through a protected service environment and use the absolute virtualenv Python and script paths. Run evaluation and `--queue-approved` as separate jobs. No persistent scheduler is required.

## Database setup

Apply [migrations/014_decision_engine.sql](migrations/014_decision_engine.sql) once to a staging copy of DevSpace CRM after its migrations 001–013. It requires existing `organizations`, `organization_services`, `profiles`, `auth.uid()`, and Supabase's `anon`, `authenticated`, and `service_role` roles. It intentionally fails on conflicting existing tables instead of silently accepting incompatible schemas. Review and deploy it through the CRM migration process after staging validation.

| Tables | Contract |
| --- | --- |
| `market_signals` | Atomic research observations, provenance, confidence, expiry |
| `intelligence_reports`, `intelligence_report_signals` | Current snapshots and their signal links |
| `decision_constraints` | One validated constraint JSON object per organization |
| `decision_runs` | Trigger, input snapshot, scoring policy, outcomes, safe error types |
| `recommendations`, `recommendation_evidence` | Scores, confidence, budgets, explanations and source references |
| `recommendation_dependencies` | Same-tenant prerequisites; acyclic order enforced on persistence |
| `recommendation_reviews` | Original/approved parameters, append-only review history, reviewer identity |
| `execution_capabilities` | Service availability, action allowlist, adapter readiness, manual opt-in |
| `execution_requests`, `execution_results` | Approved handoff, worker claim, terminal outcome and feedback |

Extra organization IDs and composite foreign keys on evidence, dependencies, report links and executions enforce tenant identity at the database boundary. RLS permits organization reads and CRM admin reads; browser users cannot directly mutate these tables. Input snapshots contain private evidence and constraints and must have the same retention/access controls as CRM data. Global/null-organization intelligence is stored but never loaded by the engine. No cross-tenant benchmarks are enabled.

The shared Supabase service role is privileged and bypasses RLS. It is a trusted backend credential, not a sandbox for untrusted workers. Keep it out of browsers, source control and logs; DevSpace One workers should call a server gateway with explicit organization/service authorization. The engine does not expose any approval method. The review RPC requires the CRM admin's user JWT and rejects service-role calls.

## Decision flow

1. Acquire a per-organization evaluation lease; expire old unqueued recommendations.
2. Load the profile, constraints, current reports, recent non-expired normalized signals, same-subject historical results, active recommendations and capabilities.
3. Evaluate each strategy independently. One exception yields a PARTIAL run; raw exception/customer text is not logged.
4. Calculate attractiveness and separate evidence confidence; enforce channels, budget, risk, targeting, email reputation and time horizon.
5. Rank by score, confidence and stable type order. Place prerequisites first, allocate a shared budget, and suppress active strategy duplicates.
6. Persist recommendations, evidence, dependencies and run completion in one RPC transaction. On failure the transaction rolls back and the run is marked FAILED separately.
7. Return an explicit `NO_ACTION` / WATCH if no new supported action remains. Its confidence is zero, not a fabricated probability that inaction is optimal. An already-active NO_ACTION is not duplicated.

A stale RUNNING lease becomes FAILED on the next evaluation after 30 minutes. Ambiguous write timeouts are not blindly retried; inspect the run ID first. Recommendations expire after at most 14 days by default, capped by the supporting signals’ expiry and maximum age. Queued/executing records are never silently deduplicated away. New runs do not supersede active recommendations automatically; reject or complete them first.

## Strategies and scoring

Each strategy implements `evaluate(context) -> StrategyEvaluation`; typed context and evaluations are in `models/contracts.py`. Strategy logic lives in separate modules. The repository and transport are consolidated while the project is small.

| Strategy | Signals / special rules |
| --- | --- |
| OUTREACH | Prospect volume, contactability, industry fit, offer clarity; healthy email reputation required; routes to preferred Apollo or DevSpace outreach |
| DOMAIN_ACQUISITION | Comparable sales, intent, buyer density, domain market demand; medium risk; investigation only, never purchase authorization |
| GOOGLE_ADS | Search demand, commercial intent, inverse competition, landing-page readiness; geography and ad budget required |
| LANDING_PAGE_OPTIMIZATION | Poor readiness, missing CTA, broken forms, mobile issues; prerequisite for paid search when needed |
| SEO | Organic demand, keyword opportunity, inverse ranking difficulty, content gaps; at least three-month horizon, declared 3–6 month lead time |
| NO_ACTION | Missing evidence, constraints, weak opportunity, duplicate work, unavailable prerequisite or insufficient shared budget |

Meta Ads is intentionally deferred; its capability is PLANNED and no strategy forces a recommendation.

All strategy metric weights, minimum/target budgets, age windows, score thresholds and confidence coverage exponent live in [scoring.json](decision_engine/config/scoring.json). Budgets are policy defaults denominated in each organization's configured currency; calibrate these amounts before enabling another currency. There is no currency conversion. Expected monetary value remains null until a defensible estimate exists. Expected cost is a conservative proposed envelope, not a quoted price.

```
score = clamp(sum(component × positive_weight) - sum(penalty × penalty_weight), 0, 100)
confidence = mean(relevant signal confidences) × coverage^0.5
```

The score uses opportunity, evidence strength, historical performance, strategic fit and an ROI proxy; it subtracts risk, cost and uncertainty. Missing metrics contribute no opportunity. Priority uses score and confidence; dependencies cap it at MEDIUM. CRITICAL additionally requires an urgent condition. Confidence reflects source-provided confidence and completeness; it is not a calibrated probability or a claim that correlated sources are independent.

The signal contract uses **0–100 normalized scores** with `unit = score_0_100`; confidence is **0–1**. Raw prospect counts, CPC, CPL and sales dollars must not be mislabeled as normalized scores. The latest metric per subject is used, not a sum of duplicates. Signals older than 30 days, future signals, expired signals and irrelevant subjects are excluded.

Historical feedback pools same-organization/service/subject/currency completed outcomes over 180 days. If a target CPL exists, the performance ratio is `leads × target_CPL / cost`; otherwise it uses attributed revenue/cost when available. Performance shrinks toward neutral using three prior samples. Poor comparable outcomes reduce score and confidence; referenced result IDs are retained. There is no ML and no sharing of private client history.

Budgets reserve active unqueued recommendations plus current-month execution envelopes and outstanding older requests. `committed_monthly_spend` is for commitments outside these requests, to avoid double counting. Full envelopes remain reserved after completion/failure until month rollover; there is no automatic refund or ongoing-campaign reconciliation. Ad envelopes share a separate `max_ad_spend` cap. Every adapter must enforce `budget_limit` and an explicit renewal policy; an approved monthly campaign must not run indefinitely.

## Approval and execution

CRM admins call `de_review` with APPROVED, MODIFIED or REJECTED. Original recommendation metadata is preserved. MVP modifications permit **budget reductions only**; targeting, service or other material changes require rejecting and re-evaluating with updated constraints. NO_ACTION cannot execute.

`de_queue_approved` rechecks expiry, approval, capability/action allowlist, current constraints, enabled CRM organization service, remaining budget and completed prerequisites inside an organization lock. Google Ads also requires the latest fresh readiness signal; after landing-page work it must be observed after the prerequisite outcome. A blocked approval remains approved for later review/queuing and returns a reason. Requests are unique per recommendation.

The capability seeds reflect locally existing outreach/domain services, but every `adapter_ready` defaults false. Enable this only after the consumer implements the approved request contract. PLANNED/MANUAL services additionally need an explicit `allow_manual = true` and adapter readiness. The engine never auto-enables a service.

Workers claim requests with `de_claim_execution`, execute through DevSpace One, then submit `de_record_result`. Claims are atomic and recheck capability, constraints, expiry, prerequisites and paid-search readiness. A material constraint change cancels stale queued work. Terminal results update request and recommendation states together and are idempotent per request. A failed request is not automatically retried. A worker crash after claiming requires operator reconciliation; never blindly replay a potentially completed external action. Use request UUIDs as downstream idempotency keys.

## Tests and extending

```bash
python -m pytest -q
# Full SQL tests: use an EMPTY disposable PostgreSQL database only.
DE_TEST_DATABASE_URL=postgresql://postgres:test@localhost:5432/decision_engine_test python -m pytest -q
# Alternatively install pgserver for a temporary local PostgreSQL server:
python -m pip install pgserver
python -m pytest -q
```

SQL tests skip if neither a test database nor the optional local server is available. The fixture refuses a database containing `organizations`. CI provisions PostgreSQL 16 and runs the complete suite. Coverage includes realistic roofing, SaaS, restaurant and domain opportunities; tiny/blocked budgets; confidence; ranking; NO_ACTION; feedback; tenant isolation; approval modification; dependencies; transaction rollback; concurrent queuing; and retry idempotency.

To add a strategy, implement the interface in `strategies/`, add an explicit metric/budget policy, register it in `default_strategies`, and add realistic eligible/ineligible tests. Register its execution service/action separately. Do not put database calls, external operations or approval decisions in strategy code. See [integration.md](docs/integration.md) for producer/consumer payloads and rollout requirements.
