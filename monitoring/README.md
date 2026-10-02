# Read-only service diagnostics

`python monitoring/capability_probe.py --organization <UUID>` uses this engine's
supplied runtime environment, makes authenticated GET/SELECT checks, and atomically
publishes `logs/capability_health.json`. It never executes a workflow or writes
business data. The environment variable names are in `profile.json`.

For the existing Domain Merchant cron environment, the dsmonitor diagnostic launcher
reuses `scripts.domain_daily.job_environment`; dsorchestrator uses its own `.env`.
The launcher publishes to dsmonitor/data/capabilities every two minutes. A report
expires after 180 seconds; diagnostic process existence never establishes engine
availability. Reports identify their configuration scope, not every remote worker.

The bounded CRM `/api/bot/monitoring-capabilities` endpoint should be deployed with
the CRM application. Until then domain probes use the existing context GET route,
with 5-second request timeouts and a 4 MB response cap. Legacy outreach capability
stays UNKNOWN if the new route is absent. No mutation endpoint is used as a probe.

Reference-only receipts are emitted by real client activity and rotate at 8 MB
(one backup). They contain table/record/service/organization identifiers, source
check time and an existing workflow ID when available. Receipt failures cannot
fail business operations. Missing workflow IDs are not invented. The diagnostic
probe itself never emits business activity or verifies writes merely from a token.
