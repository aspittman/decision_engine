# Shared integration contract v1

This document describes new integration work for the neighboring systems. The engine already implements the database-side contracts and its Supabase client. No CRM routes or external executors are assumed to exist.

## Existing repositories inspected

- `devspace-crm/supabase/migrations/002_multi_tenant.sql`: organizations, profiles, organization services and memberships. Migration 005 defines admin/profile tenant policies; 010 adds domain intelligence. Existing migrations stop at 013.
- `devspace-crm/app/api/bot/*`: bot endpoints use bearer `BOT_API_SECRET` authorization. A shared bot token alone is not a CRM user's approval identity.
- `devspace-one/core/crm_client.py`: `CRM_BASE_URL`, `CRM_BOT_API_SECRET`, and bot API requests. `main.py` dispatches `domain_merchant`, `apollo_outreach`, `afternic_sync`, and `devspace_outreach`; no generic execution-request consumer is present.
- `mmonolith/analysis/reporting.py`: JSON/CSV outputs with service `demand_score`, `opportunity_score`, `confidence` on 0–100, growth and budget fields. These are research outputs, not approved actions.

The new migration does not alter any of these existing tables or dispatch paths. Repository imports are never used for integration.

## MMonolith publisher

A publisher should authenticate to a trusted CRM ingest gateway, which binds and validates organization identity. Insert append-only signals, a CURRENT report, and same-tenant report links. Supersede previous snapshots explicitly. Keep raw source details and normalization rules in metadata; preserve source references and observation times.

```json
{
  "id": "11111111-1111-4111-8111-111111111112",
  "organization_id": "11111111-1111-4111-8111-111111111111",
  "subject_type": "organization",
  "signal_type": "search_demand",
  "metric": "search_demand",
  "value_numeric": 87,
  "unit": "score_0_100",
  "confidence_score": 0.91,
  "source": "google_trends",
  "source_reference": "producer-run-or-source-reference",
  "observed_at": "2026-09-12T12:00:00Z",
  "expires_at": "2026-09-19T12:00:00Z",
  "metadata": {"subject_key": "organization", "keyword": "roof leak repair", "normalization_version": "v1"}
}
```

In this MVP `metric` is a strategy feature name. Put keyword/category names in metadata, rather than using a keyword as the metric. The CLI evaluates organization-level subjects (`subject_key = organization`). A future scoped-opportunity runner can populate `Context.profile.subject_key`; it must also extend active-recommendation uniqueness before supporting simultaneous recommendations of one type for different subjects.

Do not map MMonolith's general service demand directly to Google search demand: those are distinct measurements. Divide its confidence by 100. Publish general `demand_score` under its actual semantics until there is a defensible strategy feature mapping. NameBio/DNJournal dollars likewise need a documented normalization into `comparable_domain_sales`; preserve raw monetary values separately. Unmapped evidence safely produces NO_ACTION.

## Client constraints

Insert one `decision_constraints` row per organization. No row means zero budget and conservative defaults. Channel names use uppercase recommendation types; service preferences use lowercase service keys.

```json
{
  "monthly_marketing_budget": 1000,
  "max_ad_spend": 750,
  "committed_monthly_spend": 0,
  "currency": "USD",
  "allowed_channels": ["GOOGLE_ADS", "LANDING_PAGE_OPTIMIZATION", "OUTREACH", "SEO"],
  "blocked_channels": [],
  "target_locations": ["Salt Lake City, UT"],
  "target_industries": ["roofing"],
  "brand_restrictions": ["No unverified guarantees"],
  "requires_human_approval": true,
  "risk_tolerance": "LOW",
  "minimum_confidence": 0.65,
  "maximum_cost_per_lead": 50,
  "service_preferences": ["devspace_outreach"],
  "email_reputation_healthy": true,
  "time_horizon_months": 6,
  "saturated": false
}
```

Human approval remains mandatory even if `requires_human_approval` is false. Unknown constraint keys are rejected by the engine rather than silently ignored. The CRM constraint editor should validate with the same contract. Its authenticated backend writes constraints; browser writes to the new tables are denied. Queuing and claiming also require a matching enabled `organization_services` row. Constraints should reflect enabled organization services: seed/update allowed channels from the CRM's `organization_services` settings rather than assuming a globally available service is subscribed by every client.

## CRM display and review

Read `recommendations` with organization/status filters; display metadata rank, score, confidence, cost, currency, concerns, capability, dependency IDs, and joined evidence. Show NO_ACTION explicitly. Display the persisted explanation rather than replacing it with an unsupported AI assertion.

Use the signed-in admin's Supabase client:

```typescript
const { data, error } = await supabase.rpc('de_review', {
  p_org: organizationId,
  p_recommendation: recommendationId,
  p_decision: 'MODIFIED', // APPROVED / MODIFIED / REJECTED
  p_parameters: { budget_limit: 250 }, // only for MODIFIED; budget decreases only
  p_reason: null
});
```

The DB derives `reviewed_by` from `auth.uid()` and verifies `profiles.role = admin`. Do not accept a caller-supplied reviewer ID or use the bot secret for approvals. The original metadata remains intact in recommendations and is copied into the audit record. Review is a single transition from RECOMMENDED; repeat/stale review attempts fail.

After review, a backend job calls `de_queue_approved(p_org)`. The CLI's `--queue-approved` does this. Return blocked reasons to the UI: unavailable adapter, incomplete dependency, changed constraints, missing readiness, or exhausted budget. `approved_at` alone never authorizes arbitrary external actions.

## DevSpace One gateway and consumer

Suggested future CRM endpoints (not implemented here):

| Route | Required behavior |
| --- | --- |
| `POST /api/bot/execution-requests/claim` | Authenticate worker; authorize its organization and service; invoke `de_claim_execution` |
| `POST /api/bot/execution-results` | Authenticate worker; verify request ownership/service; invoke `de_record_result` |

The gateway may follow the existing bearer pattern but should use scoped worker credentials/allowlists. Never allow arbitrary organization/service values merely because a shared bot secret is valid. The generic engine service key must not be shipped to workers or browsers.

A claimed request contains:

```json
{
  "id": "22222222-2222-4222-8222-222222222222",
  "organization_id": "11111111-1111-4111-8111-111111111111",
  "recommendation_id": "33333333-3333-4333-8333-333333333333",
  "execution_service": "google_ads",
  "action_type": "create_search_campaign",
  "status": "RUNNING",
  "requested_parameters": {
    "budget_limit": 750,
    "monthly_budget": 750,
    "currency": "USD",
    "locations": ["Salt Lake City, UT"],
    "industries": ["roofing"],
    "brand_restrictions": [],
    "subject_key": "organization"
  },
  "approved_by": "44444444-4444-4444-8444-444444444444",
  "approved_at": "2026-09-12T13:00:00Z"
}
```

The complete database row also includes review ID, constraints snapshot and timestamps. Validate the service/action schema before executing. The MVP does not select keywords, creatives, recipients or domain names; if service-specific material parameters need additional review, DevSpace One must create its own review step before external execution. `prepare_outreach` requires recipient review. `investigate_domain_category` carries `investigation_only=true` and `purchase_authorized=false`; it must never be mapped to a purchase function.

Use the request ID for provider idempotency. A RUNNING request is not automatically reclaimed because the external action may have succeeded before a worker crash. Reconcile provider state manually before any retry. The service must enforce cost ceilings and stop/renew recurring work explicitly; these database contracts cannot enforce external provider spend.

Example terminal result RPC from the authorized gateway:

```json
{
  "p_org": "11111111-1111-4111-8111-111111111111",
  "p_request": "22222222-2222-4222-8222-222222222222",
  "p_status": "COMPLETED",
  "p_cost": 190,
  "p_revenue": null,
  "p_metrics": {"clicks": 61, "leads": 8},
  "p_results": {"provider_reference": "external-id"},
  "p_error": null
}
```

`de_record_result` derives tenant/service/currency/subject from the request, uses server timestamps, and atomically completes both records. First terminal result wins; duplicates return its ID without mutating historical evidence. Corrections require an audited operational process, not an automatic overwrite. Raw provider responses may contain private data; sanitize them before publishing results. Trigger `EXECUTION_COMPLETED` evaluation afterward; the MVP does not run a background event consumer.

## Staging rollout

1. Apply the migration to a staging CRM database; run the SQL suite against a separate empty database.
2. Add the constraint editor and populate real client limits/subscriptions.
3. Publish validated MMonolith signals/reports with correct tenant IDs, units, confidence and expiry.
4. Run one organization and review its explanations, budget assumptions and evidence in CRM.
5. Integrate admin review and gateway endpoints; implement one DevSpace One adapter and test idempotency/cost enforcement.
6. Enable that capability's `adapter_ready`. Leave unimplemented services disabled.
7. Exercise approval, rejection, reduced-budget modification, failure, dependency completion, and historical feedback before enabling cron.

Schema version 014 and contract version v1 are coordinated deployment requirements. No direct Python imports connect the systems, and no live schema or external operational action is performed by this repository's tests.
