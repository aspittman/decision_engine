# DevSpace Decision Engine

A deterministic Python strategy layer that turns organization intelligence into ranked, evidence-linked recommendations. It submits recommendations through the CRM server API. CRM creates execution requests **only after CRM admin approval**. It has no email, advertising, domain-purchase, website-editing, or LLM execution clients.

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

The engine uses a server API contract and does not import CRM source code or need a Supabase service-role key. CRM owns migrations, admin review, and execution handoff. The shared storage contract defines how MMonolith publishes organization-scoped intelligence and how a DevSpace One gateway consumes approved requests.

## Local setup

Python 3.10+; runtime uses only the standard library.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
cp .env.example .env
# Set CRM_API_URL to the CRM origin and CRM_API_SECRET to its BOT_API_SECRET.
set -a
source .env
set +a
python main.py --organization <development-organization-uuid>
python main.py --all
python main.py --trigger scheduled_review
```

`.env` is not loaded automatically. HTTPS is required except for loopback development URLs. The client uses a 30-second timeout, refuses redirects, validates response envelopes and tenant IDs, and retries transient GET failures up to three attempts. Writes are never automatically retried because their transaction may already have committed. Inspect the CRM run before retrying an ambiguous write. A stale run lease expires after 30 minutes.

`--trigger scheduled_review` defaults to all organizations; other triggers require `--organization` or `--all`. Exit code 1 means at least one failed or partial run. There is no approval or queue command. `LOG_LEVEL` and `DECISION_SCORING_FILE` remain optional.

## CRM installation and contract

Apply the CRM's `supabase/migrations/014_decision_engine.sql` and `015_decision_engine_api.sql` after migrations 001–013. The copy of 014 here remains a database test fixture for the original strategy contract; **CRM owns deployment and subsequent migrations**. Do not apply 014 twice. No migration is applied to a deployed database by this integration.

The existing `organizations` and `organization_services` tables are reused, including service `config_json`. `decision_constraints` implements the client-constraints contract; no parallel `client_constraints` or organization-configuration table is created. The new intelligence tables represent normalized, attributable signals and reports; the CRM's existing domain intelligence view and domain-lead recommendations remain separate domain-specific features.

`decision_engine/clients/crm_client.py` is the only HTTP adapter used by the CLI. `repositories/crm.py` maps the API context into the existing strategy model. The older Supabase transport is retained for compatibility tests, and is not selected by the CLI.

| API under `/api/decision-engine` | Purpose |
| --- | --- |
| `GET /organizations` | Trusted service's organization inventory |
| `GET /context?organization_id=…` | Organization, service configuration, constraints, signals, reports/links, history, active recommendations, requests and capabilities |
| `GET /intelligence-reports`, `/market-signals`, `/execution-results` | Tenant-scoped reads; require `organization_id` |
| `POST /runs` | Start a run with `organization_id` and `trigger` |
| `POST /recommendations` | Atomically finalize a run with recommendations and initial evidence |
| `POST /recommendations/{id}/evidence` | Append same-tenant evidence before review |
| `POST /runs/{id}/fail` | Record a sanitized failure type |

All use `Authorization: Bearer <CRM_API_SECRET>`, validated against the CRM's existing server `BOT_API_SECRET`. This is a trusted cross-organization service credential, not a tenant-user credential. The CRM checks organization existence, filters every tenant read, and uses composite foreign keys for evidence and execution ownership. The engine independently rejects mixed-tenant responses. Supabase credentials remain inside CRM. API errors and engine logs omit response bodies, credentials and customer text.

CRM `/admin/recommendations` displays evidence, scores, budgets, status and review history. Approval/modify/reject require a real admin user session; the bot API exposes none of these actions. Approval atomically creates an execution request; unavailable adapters leave it `APPROVED`, while ready adapters with valid constraints may queue it. Modification permits a reduced positive budget; original parameters remain unchanged. Target/action changes require a new recommendation. Rejection preserves the recommendation and optional reason. `NO_ACTION` can be reviewed/rejected but cannot create an execution request.

See [docs/integration.md](docs/integration.md) for payloads, producer/consumer responsibilities and local end-to-end validation.

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

CRM admins call `de_review_and_request` with APPROVED, MODIFIED or REJECTED. Original recommendation metadata is preserved. MVP modifications permit **budget reductions only**; targeting, service or other material changes require rejecting and re-evaluating with updated constraints. NO_ACTION cannot execute.

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


## Closed-loop domain reference

The four-system domain feedback loop is documented in
[the shared architecture guide](../mmonolith/docs/closed-loop-intelligence.md).
CRM migration `016_feedback_loop.sql` adds immutable predictions, evaluations and
versioned report lineage. The existing approval and execution contracts remain authoritative.
DevSpace One's new gateway supports approved **test investigations only**; no live
purchasing, outreach or paid provider is enabled.

Run the complete disposable PostgreSQL + real CRM + Decision Engine + Domain Merchant test from MMonolith:

```bash
python scripts/smoke_domain_loop.py --engine-root ../decision_engine --postgrest /absolute/path/to/postgrest
```

The shared guide includes environment variables, component CLI commands, source
requirements, local outbox behavior, trace identifiers and deferred production integration.

## MMonolith domain research integration

The domain strategy consumes `domain-evidence-v1` MMonolith reports and checks
raw comparable sales, search demand, buyer observations and current registrar
quotes against `domain_research_policy` in `config/scoring.json`. Its score is
policy coverage, not resale probability; optional legacy scores do not select
recommendations. Existing constraints and report lineage are preserved.

See [research setup and providers](../mmonolith/docs/domain-research.md) and
[the safe integration validation](../mmonolith/docs/closed-loop-validation.md).

The five-service recommendation upgrade is documented in [docs/service-decisions.md](docs/service-decisions.md), including the contract audit, formulas, policies, deployment prerequisites, known intelligence gaps, and manual verification commands. Apply `migrations/025_service_decisions.sql` to the CRM database after its migrations through 024 before enabling this code. Existing strategy planning remains available; explicit requests use `--service-id` and `--decision-type` and create advisory records with no execution adapter.
