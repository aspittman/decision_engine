# CRM contract v1

## Ownership

MMonolith → CRM/Supabase intelligence → Decision Engine → CRM human review → execution requests → DevSpace One → execution results.

The CRM repository owns migrations 014 and 015 and the Next.js API. The Python engine depends on HTTP JSON only; no CRM source imports or database credential is required. Configure `CRM_API_URL` with the CRM origin and `CRM_API_SECRET` with the existing CRM `BOT_API_SECRET`. This shared credential is trusted across tenants, as in the CRM's existing bot routes; it must never be given to customers or browsers.

CRM inventory inspection found migrations 001–013, organizations, organization membership/profiles, organization services with `config_json`, domain intelligence derived from leads/sales, and domain-specific recommendations. None were equivalent to normalized intelligence reports or cross-service decision/review records. Reuse `decision_constraints` for client constraints, not a duplicate table. Existing lead outreach approval can send email; the decision review path deliberately uses only its database handoff RPC.

## API

Responses are `{ "success": true, "data": … }`; failures contain a generic error and HTTP status. Reads use 200; creations use 201. Context is non-cacheable. Invalid input uses 400, invalid service credentials 401, absent organization 404, transaction conflicts 409, database read unavailability 503. UUIDs are canonical strings. There are no caller-selected table names, filters, RPC names, review identities or approval statuses.

`GET /api/decision-engine/context?organization_id=<uuid>` returns arrays keyed by:

- `organizations` (exactly one), `organization_services` (including service configuration).
- `decision_constraints` (zero or one), `market_signals`, `intelligence_reports`, `intelligence_report_signals`.
- `execution_results`, `recommendations`, `execution_requests`, `execution_capabilities` (global service catalog only).

The server paginates database reads, including short pages. The engine applies its scoring policy's age/status/expiry windows and includes only completed history and current reports. It excludes null/global intelligence and computes budget reservations without double-counting reviewed recommendations that already have requests. Context reads are not a database snapshot; finalization checks current constraints and database references, and review/queue/claim revalidate mutable execution requirements.

`GET /organizations` returns the trusted service inventory. `GET /intelligence-reports`, `/market-signals`, `/execution-results` all require `organization_id`; they expose that tenant's stored rows for the engine's policy filtering.

Start a run with `POST /runs`:

```json
{"organization_id":"11111111-1111-4111-8111-111111111111","trigger":"MANUAL_REQUEST"}
```

Data is the run UUID. Trigger names match the Decision Engine CLI. Run leasing and duplicate active strategy prevention remain database invariants.

`POST /recommendations` finalizes a whole run in a single transaction:

```json
{
  "organization_id":"11111111-1111-4111-8111-111111111111",
  "run_id":"22222222-2222-4222-8222-222222222222",
  "recommendations":[],
  "snapshot":{"constraints":{}},
  "summary":{"recommendations_created":0},
  "partial":false
}
```

Each nonempty recommendation follows `DecisionService.run()`'s output: UUID, matching organization, type/service, title/summary/reason, priority, score/confidence, budget/currency/risk, expiry, `status: RECOMMENDED`, metadata with action/parameters/rank, evidence array and dependency UUIDs. Initial evidence is required and inserted atomically. Operational recommendations require referenced signal/report/result evidence. `create_recommendation()` is the convenience method for a one-recommendation run; do not call it repeatedly for the same completed run. Use `create_recommendations()` for a batch.

`POST /recommendations/{id}/evidence` accepts `organization_id` and `evidence` array. Each evidence item has `evidence_type`, description, nullable weight and optional nullable `signal_id`, `intelligence_report_id`, `execution_result_id`. Types: MARKET_SIGNAL, INTELLIGENCE_REPORT, HISTORICAL_RESULT, CLIENT_CONSTRAINT, RULE, OTHER. Composite foreign keys reject other tenants' sources. Appending after review is prohibited.

`POST /runs/{id}/fail` takes `organization_id` and a sanitized class name in `error`. Writes are not retried automatically, including after timeout. A caller must inspect the CRM record to resolve an ambiguous outcome before submitting a new run. GET uses bounded exponential backoff for network failures, 429 and transient server errors; redirects are refused to protect credentials.

## Producers and consumers

MMonolith must publish normalized `market_signals`, `intelligence_reports`, and `intelligence_report_signals` with an explicit organization and source provenance through a trusted ingestion adapter or intentionally authorized backend Supabase access. Its current aggregate report client is not automatically mapped to strategy signals: an aggregate demand score must not be invented as subject-specific contactability, readiness, etc. Normalize only metrics with defined semantics (`score_0_100`, confidence 0–1, observation/expiry timestamps). Producer adaptation is outside these two repositories; the storage contract is supplied by the CRM migration.

CRM calls `de_review_and_request` with the logged-in admin's Supabase client. This transaction records the immutable review and request. Service role and customer sessions cannot invoke it. Modified approval supports budget reduction only, with approved parameters stored separately. Rejection creates no request. The original `de_review` RPC is removed from authenticated grants in 015 so review cannot bypass request creation.

Requests initially have `APPROVED` status. CRM's queue validation can advance ready requests to `QUEUED`; blocked requests remain visible in the UI review history. An existing trusted CRM/DevSpace One server gateway may call `de_queue_approved(organization_id)` when adapters or dependencies become ready, then `de_claim_execution(organization_id, service_key)` and `de_record_result(...)`. These RPCs are not exposed through the Decision Engine API. Claims recheck constraints, service enablement, dependencies and readiness. Adapters default to not ready. This change does not start workers or implement paid action adapters. Do not wire the request queue into legacy email/domain execution without an explicit adapter.

## Verification

Decision Engine: `python -m pytest -q`. Install the test extra plus `pgserver` to run the real PostgreSQL tests rather than skipping them.

CRM: `npm run lint`, `npm run typecheck`, `npm run build`, `npm test`; install Python `pytest`, `psycopg[binary]`, `pgserver` and run `python -m pytest -q tests/test_decision_database.py`.

CRM's `tests/smoke_decision_engine.py --engine-root /path/to/decision_engine --postgrest /path/to/postgrest` starts isolated PostgreSQL, actual PostgREST and actual Next.js with a synthetic local auth provider. It uses organization `11111111-1111-4111-8111-111111111111` named Decision Engine Development, generates an outreach recommendation through CRMClient, renders `/admin/recommendations`, posts the real CRM review form and verifies a durable `APPROVED` request. It never enables an adapter, starts a worker or calls external actions. Database and processes are cleaned up. No deployed credentials are loaded into the test configuration. This verifies the local contract, not a deployed Supabase/Auth installation.

For deployed development verification, apply CRM migrations to the designated development Supabase project, deploy the CRM changes, configure the engine API variables, run for a known development organization, and review in CRM while adapters remain disabled. Production migration/deployment is a separate rollout.
