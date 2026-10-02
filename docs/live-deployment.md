Live rollout verification — October 2, 2026

Migration025 was applied transactionally to Supabase project hzamzmametxbqerlukfi after validating the installed CRM functions. Recommendation RLS remains enabled. All51 existing intelligence reports and two historical recommendations were preserved.

| Service | New recommendations | Live result |
|---|---:|---|
| domain_merchant |50|RESEARCH_FURTHER|
| devspace_services |7|RESEARCH_FURTHER|
| devspace_clients |164|82 REVIEW_CLIENT_OPPORTUNITY;82 NEEDS_INFORMATION|
| scholarship_research |17|NEEDS_INFORMATION: supplied matching profiles absent|
| investor_research |9|NEEDS_INFORMATION: supplied matching profiles absent|

All247 new recommendations reference upstream evidence and require approval. All ten organization-scoped engine runs completed. Zero execution requests were created. Missing evidence remains explicit; these outcomes do not establish that an opportunity qualifies for acquisition, offering, application or outreach.

Evidence: [run IDs and recommendation IDs](live-deployment-runs.json), [database verification](live-deployment-verification.json). Full Decision Engine suite:117 passed in3.81 seconds. CRM monitoring tests and production build passed in an isolated checkout of deployed master.

The deployed CRM monitoring endpoint still needs the tested four-file update. GitHub integration rejected writes with403 Resource not accessible by integration. This is separate from the successful live database and engine work. The exact patch is [crm-monitoring-deployment.patch](crm-monitoring-deployment.patch). The staged checkout is /tmp/decision-crm-deploy, based on master commit a739f6c3c317bb014ce3367f0353cc8ed1f8bcb3. Only these files are staged:

- app/api/bot/monitoring-capabilities/route.ts
- app/api/bot/monitoring-context/route.ts
- tests/monitoring-capabilities.test.cjs
- supabase/migrations/025_service_decisions.sql

From a terminal with repository write access, review `git diff --cached` in that checkout, commit the staged files, and push master. Vercel must successfully deploy the resulting commit. If master advances, rebase before pushing. Never force push. Migration025 is already applied and registered in the live migration history; the committed migration records that change for other environments.

After deployment, refresh dsmonitor probes and verify each canonical Decision Engine service accepts its bounded monitoring scope and references the persisted recommendation evidence. No downstream execution is required to demonstrate recommendation participation.
