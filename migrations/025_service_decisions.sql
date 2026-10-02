-- Apply to CRM after its migrations through 024. No historical rows or RLS policies change.
begin;
-- Keep the legacy uniqueness rule; add subject/decision scope for advisory records.
drop index public.de_active_strategy;
create unique index de_active_strategy on public.recommendations(organization_id,recommendation_type,
 (case when metadata->>'decision_contract'='service-decision-v1' then metadata->>'decision_key' else '' end))
 where status in ('RECOMMENDED','APPROVED','MODIFIED','QUEUED','EXECUTING');
create or replace function validate_record_context() returns trigger language plpgsql set search_path=public,pg_temp as $$
declare c jsonb; w workflow_runs; canonical text;
begin
 c:=new.metadata->'workflow_context';
 -- Advisory decisions without orchestrated workflows remain tenant scoped.
 if tg_table_name='recommendations' and new.metadata->>'decision_contract'='service-decision-v1' then
   canonical:=new.metadata->>'service_id';
   if canonical not in ('domain_merchant','devspace_services','devspace_clients','investor_research','scholarship_research')
      or canonical is null or new.recommendation_type<>'MARKET_RESEARCH'
      or new.execution_service is not null or new.metadata->>'action_type' is not null
      or new.metadata->>'execution_authorized' is distinct from 'false'
      or new.metadata->>'requires_approval' is distinct from 'true'
      or nullif(new.metadata->>'decision_type','') is null
      or nullif(new.metadata->>'decision_key','') is null
      or not exists(select 1 from organization_services where organization_id=new.organization_id and service_key=canonical and is_enabled)
      then raise exception 'Invalid advisory recommendation'; end if;
   if c is null then
     if new.workflow_run_id is not null or new.metadata->>'workflow_run_id' is not null
        or (new.service_id is not null and new.service_id<>canonical)
        then raise exception 'Explicit upstream workflow context required'; end if;
     new.service_id:=canonical; return new;
   end if;
   if canonical_service_id(c->>'service_id') is distinct from canonical
      or (new.metadata->>'workflow_run_id' is not null and new.metadata->>'workflow_run_id' is distinct from c->>'workflow_run_id')
      then raise exception 'Advisory workflow/service mismatch'; end if;
   -- With a workflow, fall through to the existing authoritative identity checks.
 end if;

 if c is null and new.metadata->>'service_id' in ('scholarship_research','investor_research') then
   canonical:=new.metadata->>'service_id';
   if tg_table_name<>'intelligence_reports' or new.workflow_run_id is not null
      or (new.service_id is not null and new.service_id<>canonical)
      or not exists(select 1 from organization_services where organization_id=new.organization_id and service_key=canonical and is_enabled)
      or new.metadata->>'research_contract' is distinct from 'product-research-v1'
      or new.report_type is distinct from (case canonical when 'scholarship_research' then 'SCHOLARSHIP_RESEARCH' else 'INVESTOR_RESEARCH' end)
      then raise exception 'Invalid product research context'; end if;
   new.service_id:=canonical;return new;
 end if;

 if c is null and new.metadata->>'service_id'='devspace_services' then
   if tg_table_name<>'intelligence_reports' or new.workflow_run_id is not null
      or (new.service_id is not null and new.service_id<>'devspace_services')
      or not exists(select 1 from organization_services where organization_id=new.organization_id and service_key='devspace_services' and is_enabled)
      then raise exception 'Invalid service demand context'; end if;
   if new.report_type<>'SERVICE_DEMAND' or new.metadata->>'research_contract' is distinct from 'service-demand-v1'
      then raise exception 'Invalid service demand report'; end if;
   new.service_id:='devspace_services';return new;
 end if;

 if c is null and new.metadata->>'service_id'='devspace_clients' then
   if new.workflow_run_id is not null or (new.service_id is not null and new.service_id<>'devspace_clients')
      or not exists(select 1 from organization_services where organization_id=new.organization_id and service_key='devspace_clients' and is_enabled)
      then raise exception 'Invalid client service context'; end if;
   if tg_table_name='intelligence_reports' then
      if new.report_type<>'CLIENT_RESEARCH' or new.metadata->>'research_contract' is distinct from 'client-research-v1' then raise exception 'Invalid client report'; end if;
   elsif new.recommendation_type<>'CLIENT_OUTREACH_BRIEF' or new.execution_service<>'devspace_clients' then raise exception 'Invalid client recommendation'; end if;
   new.service_id:='devspace_clients';return new;
 end if;
 if c is null then
   if new.workflow_run_id is not null or new.service_id is not null then raise exception 'Explicit workflow context required'; end if;
   return new;
 end if; -- historical / legacy producers stay supported; no invented lineage
 canonical:=canonical_service_id(c->>'service_id');
 if canonical is null or nullif(c->>'workflow_run_id','') is null
    or c->>'organization_id' is distinct from new.organization_id::text then raise exception 'Invalid workflow context'; end if;
 select * into w from workflow_runs where id=c->>'workflow_run_id';
 if not found or w.organization_id is distinct from new.organization_id::text
    or coalesce(w.service_id,canonical_service_id(w.workflow_type)) is distinct from canonical
    or w.parent_run_id is distinct from c->>'parent_run_id'
    or w.correlation_id is distinct from c->>'correlation_id' then raise exception 'Foreign workflow context'; end if;
 if c->>'source_engine' is distinct from (case when tg_table_name='intelligence_reports' then 'mmonolith' else 'decision_engine' end)
    then raise exception 'Invalid primary writer'; end if;
 new.service_id:=canonical; new.workflow_run_id:=w.id;
 return new;
end $$;

-- Approval of an advisory decision does not provide execution parameters.
create or replace function public.de_review(p_org uuid,p_recommendation uuid,p_decision text,p_parameters jsonb default null,p_reason text default null)
returns uuid language plpgsql security definer set search_path=public,pg_temp as $$
declare r recommendations; v_id uuid; v_parameters jsonb;
begin
  if not exists(select 1 from profiles where id=auth.uid() and role='admin') then raise exception 'Admin identity required'; end if;
  perform 1 from organizations where id=p_org for update;
  select * into r from recommendations where id=p_recommendation and organization_id=p_org for update;
  if not found or r.status <> 'RECOMMENDED' or r.expires_at <= now() then raise exception 'Recommendation not reviewable'; end if;
  if p_decision is null or p_decision not in ('APPROVED','MODIFIED','REJECTED') then raise exception 'Invalid decision'; end if;
  if r.recommendation_type='NO_ACTION' and p_decision <> 'REJECTED' then raise exception 'NO_ACTION cannot execute'; end if;
  if r.metadata->>'decision_contract'='service-decision-v1' and p_decision='MODIFIED' then
    raise exception 'Advisory strategy or policy changes require a fresh decision'; end if;
  v_parameters := r.metadata->'parameters';
  if p_decision='MODIFIED' then
    -- MVP changes only budget; changing targets or action requires a fresh decision run.
    if p_parameters is null or jsonb_typeof(p_parameters)<>'object' or not (p_parameters ? 'budget_limit')
       or (p_parameters - 'budget_limit' - 'monthly_budget') <> '{}'::jsonb then raise exception 'Only budget modifications supported'; end if;
    v_parameters := v_parameters || p_parameters;
    if r.recommendation_type='GOOGLE_ADS' then
      v_parameters := jsonb_set(v_parameters,'{monthly_budget}',v_parameters->'budget_limit');
    end if;
  elsif p_parameters is not null then raise exception 'Parameters require MODIFIED decision'; end if;
  if p_decision <> 'REJECTED' and r.metadata->>'decision_contract' is distinct from 'service-decision-v1' and ((v_parameters->>'budget_limit') is null or ((v_parameters->>'budget_limit')::numeric <= 0 and not coalesce((((r.recommendation_type='MARKET_RESEARCH' and r.execution_service='domain_merchant' and r.metadata->>'action_type'='review_domain_evidence') or (r.recommendation_type='CLIENT_OUTREACH_BRIEF' and r.execution_service='devspace_clients' and r.metadata->>'action_type'='prepare_client_outreach' and v_parameters->'draft_only'='true'::jsonb and v_parameters->'send_authorized'='false'::jsonb and v_parameters->'is_test'='false'::jsonb)) and (v_parameters->>'budget_limit')::numeric=0 and v_parameters->'external_calls_authorized'='false'::jsonb and v_parameters->'purchase_authorized'='false'::jsonb and (v_parameters->'investigation_only'='true'::jsonb or (r.recommendation_type='CLIENT_OUTREACH_BRIEF' and v_parameters->'draft_only'='true'::jsonb))),false)) or
      (v_parameters->>'budget_limit')::numeric > r.suggested_budget or not (v_parameters ? 'budget_limit')) then
    raise exception 'Modification cannot increase original budget'; end if;
  insert into recommendation_reviews(organization_id,recommendation_id,decision,reviewed_by,original_parameters,approved_parameters,rejection_reason)
    values(p_org,p_recommendation,p_decision,auth.uid(),r.metadata->'parameters',v_parameters,p_reason) returning id into v_id;
  update recommendations set status=p_decision,updated_at=now() where id=p_recommendation;
  return v_id;
end $$;



-- Preserve the installed dispatcher, excluding advisory decisions from its queue.
-- There is no execution adapter or action associated with these records.
do $migration$
declare definition text; original text := 'status in (''APPROVED'',''MODIFIED'') order by created_at,id for update loop';
begin
 definition:=pg_get_functiondef('public.de_queue_approved(uuid)'::regprocedure);
 if strpos(definition,original)=0 then raise exception 'Unrecognized dispatcher; review advisory queue exclusion before deploying'; end if;
 definition:=replace(definition,original,
   'status in (''APPROVED'',''MODIFIED'') and metadata->>''decision_contract'' is distinct from ''service-decision-v1'' order by created_at,id for update loop');
 execute definition;
end $migration$;

commit;
