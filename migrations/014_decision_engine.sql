-- Additive migration for DevSpace CRM after 013. Requires organizations, profiles and auth.uid().
-- No policies grant direct writes to authenticated CRM users; review goes through audited RPC.
begin;
create table public.decision_constraints (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null unique references public.organizations(id),
  constraints jsonb not null default '{}' check (jsonb_typeof(constraints) = 'object'),
  updated_at timestamptz not null default now()
);
create table public.market_signals (
  id uuid primary key default gen_random_uuid(), organization_id uuid references public.organizations(id),
  business_group_id uuid, subject_type text not null, subject_id uuid,
  signal_type text not null, metric text not null, value_numeric numeric, value_text text, unit text,
  severity text, confidence_score numeric not null check (confidence_score between 0 and 1),
  source text not null, source_reference text, observed_at timestamptz not null, expires_at timestamptz,
  metadata jsonb not null default '{}', created_at timestamptz not null default now(),
  unique (organization_id, id), check (expires_at is null or expires_at > observed_at)
);
create table public.intelligence_reports (
  id uuid primary key default gen_random_uuid(), organization_id uuid references public.organizations(id),
  business_group_id uuid, subject_type text not null, subject_id uuid, report_type text not null,
  summary text not null, overall_score numeric, confidence_score numeric not null check (confidence_score between 0 and 1),
  period_start timestamptz, period_end timestamptz,
  status text not null check (status in ('CURRENT','STALE','SUPERSEDED','ARCHIVED')),
  metadata jsonb not null default '{}', created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique (organization_id, id)
);
create table public.intelligence_report_signals (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id),
  report_id uuid not null, signal_id uuid not null, unique (report_id, signal_id),
  foreign key (organization_id, report_id) references public.intelligence_reports(organization_id, id),
  foreign key (organization_id, signal_id) references public.market_signals(organization_id, id)
);
create table public.decision_runs (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id),
  trigger_type text not null check (trigger_type in ('NEW_INTELLIGENCE_REPORT','SIGNIFICANT_SIGNAL_CHANGE','MANUAL_REQUEST','EXECUTION_COMPLETED','SCHEDULED_REVIEW','CLIENT_CONSTRAINT_CHANGED')),
  started_at timestamptz not null default now(), completed_at timestamptz,
  status text not null check (status in ('RUNNING','COMPLETED','PARTIAL','FAILED')),
  input_snapshot jsonb not null default '{}', output_summary jsonb not null default '{}',
  engine_version text not null, error_message text, unique (organization_id, id)
);
create unique index de_one_running on public.decision_runs(organization_id) where status = 'RUNNING';
create table public.recommendations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id),
  decision_run_id uuid not null, recommendation_type text not null check (recommendation_type in ('OUTREACH','GOOGLE_ADS','META_ADS','SEO','LANDING_PAGE_OPTIMIZATION','WEBSITE_FIX','DOMAIN_ACQUISITION','DOMAIN_OUTREACH','CONTENT','MARKET_RESEARCH','NO_ACTION')),
  execution_service text, title text not null, summary text not null, reason text not null check (length(reason)>0),
  priority text not null check (priority in ('CRITICAL','HIGH','MEDIUM','LOW','WATCH')),
  score numeric not null check (score between 0 and 100), confidence_score numeric not null check (confidence_score between 0 and 1),
  expected_value numeric, expected_cost numeric check (expected_cost >= 0), suggested_budget numeric check (suggested_budget >= 0),
  currency text, risk_level text not null check (risk_level in ('LOW','MEDIUM','HIGH')),
  status text not null check (status in ('DRAFT','RECOMMENDED','APPROVED','MODIFIED','REJECTED','QUEUED','EXECUTING','COMPLETED','FAILED','EXPIRED')),
  created_by text not null default 'decision_engine', created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(), expires_at timestamptz, metadata jsonb not null default '{}',
  unique (organization_id, id), foreign key (organization_id, decision_run_id) references public.decision_runs(organization_id, id)
);
create unique index de_active_strategy on public.recommendations(organization_id, recommendation_type)
  where status in ('RECOMMENDED','APPROVED','MODIFIED','QUEUED','EXECUTING');
create table public.recommendation_dependencies (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id),
  recommendation_id uuid not null, depends_on_recommendation_id uuid not null,
  unique (recommendation_id, depends_on_recommendation_id), check (recommendation_id <> depends_on_recommendation_id),
  foreign key (organization_id, recommendation_id) references public.recommendations(organization_id, id),
  foreign key (organization_id, depends_on_recommendation_id) references public.recommendations(organization_id, id)
);
create table public.execution_capabilities (
  id uuid primary key default gen_random_uuid(), service_key text not null unique,
  status text not null check (status in ('AVAILABLE','PLANNED','UNAVAILABLE','MANUAL')),
  allowed_actions text[] not null default '{}', adapter_ready boolean not null default false,
  allow_manual boolean not null default false, updated_at timestamptz not null default now()
);
insert into public.execution_capabilities(service_key, status, allowed_actions) values
 ('devspace_outreach','AVAILABLE',array['prepare_outreach']),
 ('apollo_outreach','AVAILABLE',array['prepare_outreach']),
 ('domain_merchant','AVAILABLE',array['investigate_domain_category']),
 ('google_ads','PLANNED',array['create_search_campaign']),
 ('meta_ads','PLANNED',array['create_meta_campaign']),
 ('seo','PLANNED',array['create_seo_plan']),
 ('landing_page','PLANNED',array['optimize_landing_page']);
create table public.recommendation_reviews (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id),
  recommendation_id uuid not null, decision text not null check (decision in ('APPROVED','MODIFIED','REJECTED')),
  reviewed_by uuid not null references public.profiles(id), reviewed_at timestamptz not null default now(),
  original_parameters jsonb not null, approved_parameters jsonb, rejection_reason text,
  unique (organization_id, id), foreign key (organization_id, recommendation_id) references public.recommendations(organization_id, id)
);
create table public.execution_requests (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id),
  recommendation_id uuid not null unique, review_id uuid not null,
  execution_service text not null, action_type text not null,
  status text not null check (status in ('PENDING_APPROVAL','APPROVED','QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')),
  requested_parameters jsonb not null, constraints_snapshot jsonb not null, approved_by uuid not null references public.profiles(id), approved_at timestamptz not null,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique (organization_id, id), foreign key (organization_id, recommendation_id) references public.recommendations(organization_id, id),
  foreign key (organization_id, review_id) references public.recommendation_reviews(organization_id, id)
);
create table public.execution_results (
  id uuid primary key default gen_random_uuid(), execution_request_id uuid not null unique,
  organization_id uuid not null references public.organizations(id), execution_service text not null,
  status text not null check (status in ('COMPLETED','FAILED')), started_at timestamptz, completed_at timestamptz not null,
  cost numeric check (cost >= 0), revenue_attributed numeric check (revenue_attributed >= 0),
  currency text not null, subject_key text not null, results jsonb not null default '{}', metrics jsonb not null default '{}',
  error_message text, created_at timestamptz not null default now(), unique (organization_id, id),
  foreign key (organization_id, execution_request_id) references public.execution_requests(organization_id, id)
);
create table public.recommendation_evidence (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id),
  recommendation_id uuid not null, evidence_type text not null check (evidence_type in ('MARKET_SIGNAL','INTELLIGENCE_REPORT','HISTORICAL_RESULT','CLIENT_CONSTRAINT','RULE','OTHER')),
  signal_id uuid, intelligence_report_id uuid, execution_result_id uuid, description text not null check(length(description)>0),
  weight numeric, created_at timestamptz not null default now(),
  check ((evidence_type <> 'MARKET_SIGNAL' or signal_id is not null) and
         (evidence_type <> 'INTELLIGENCE_REPORT' or intelligence_report_id is not null) and
         (evidence_type <> 'HISTORICAL_RESULT' or execution_result_id is not null)),
  foreign key (organization_id, recommendation_id) references public.recommendations(organization_id, id),
  foreign key (organization_id, signal_id) references public.market_signals(organization_id, id),
  foreign key (organization_id, intelligence_report_id) references public.intelligence_reports(organization_id, id),
  foreign key (organization_id, execution_result_id) references public.execution_results(organization_id, id)
);
create index de_signal_lookup on public.market_signals(organization_id, observed_at desc);
create index de_report_lookup on public.intelligence_reports(organization_id, status);
create index de_result_lookup on public.execution_results(organization_id, execution_service, completed_at desc);
create index de_request_poll on public.execution_requests(organization_id, status, created_at);

-- Evidence is a commit-time invariant, including writes from backend integrations.
create function public.de_require_evidence() returns trigger
language plpgsql set search_path=public,pg_temp as $$
declare rec_id uuid;
begin
  if tg_table_name='recommendations' then rec_id:=new.id;
  elsif tg_op='DELETE' then rec_id:=old.recommendation_id;
  else rec_id:=new.recommendation_id; end if;
  if exists(select 1 from recommendations where id=rec_id) and not exists(select 1 from recommendation_evidence where recommendation_id=rec_id)
    then raise exception 'Recommendation must retain evidence'; end if;
  if tg_table_name='recommendation_evidence' and tg_op='UPDATE' then
   if old.recommendation_id<>new.recommendation_id
    and exists(select 1 from recommendations where id=old.recommendation_id)
    and not exists(select 1 from recommendation_evidence where recommendation_id=old.recommendation_id)
    then raise exception 'Recommendation must retain evidence'; end if;
  end if;
  return null;
end $$;
create constraint trigger de_recommendation_has_evidence after insert or update on public.recommendations
  deferrable initially deferred for each row execute function public.de_require_evidence();
create constraint trigger de_evidence_retained after update or delete on public.recommendation_evidence
  deferrable initially deferred for each row execute function public.de_require_evidence();
create function public.de_preserve_review() returns trigger
language plpgsql set search_path=public,pg_temp as $$
begin raise exception 'Review history is append-only'; end $$;
create trigger de_review_append_only before update or delete on public.recommendation_reviews
  for each row execute function public.de_preserve_review();

-- Lock the organization for each state-changing transaction. New runs have a bounded lease.
create function public.de_start_run(p_org uuid, p_trigger text) returns uuid
language plpgsql security definer set search_path = public, pg_temp as $$
declare v_id uuid;
begin
  perform 1 from organizations where id=p_org for update;
  if not found then raise exception 'Unknown organization'; end if;
  update decision_runs set status='FAILED', completed_at=now(), error_message='Run lease expired'
    where organization_id=p_org and status='RUNNING' and started_at < now()-interval '30 minutes';
  update recommendations set status='EXPIRED', updated_at=now()
    where organization_id=p_org and status in ('RECOMMENDED','APPROVED','MODIFIED') and expires_at <= now();
  insert into decision_runs(organization_id,trigger_type,status,engine_version)
    values(p_org,p_trigger,'RUNNING','0.1.0') returning id into v_id;
  return v_id;
end $$;

create function public.de_finish_run(p_run uuid,p_org uuid,p_recommendations jsonb,p_snapshot jsonb,p_summary jsonb,p_partial boolean)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare r jsonb; e jsonb; dep jsonb;
begin
  perform 1 from organizations where id=p_org for update;
  perform 1 from decision_runs where id=p_run and organization_id=p_org and status='RUNNING' for update;
  if not found then raise exception 'Run not active'; end if;
  if not coalesce(p_snapshot->'constraints' @> coalesce((select constraints from decision_constraints where organization_id=p_org),'{}'),false)
    then raise exception 'Constraints changed during evaluation'; end if;
  for r in select * from jsonb_array_elements(p_recommendations) loop
    if (r->>'organization_id')::uuid is distinct from p_org or coalesce(jsonb_array_length(r->'evidence'),0) < 1 then
      raise exception 'Invalid tenant or missing evidence'; end if;
    if r->>'recommendation_type'<>'NO_ACTION' and not exists(select 1 from jsonb_array_elements(r->'evidence') evidence_item
      where evidence_item->>'evidence_type' in ('MARKET_SIGNAL','INTELLIGENCE_REPORT','HISTORICAL_RESULT')) then
      raise exception 'Operational recommendation requires referenced evidence'; end if;
    insert into recommendations(id,organization_id,decision_run_id,recommendation_type,execution_service,title,summary,reason,priority,score,
      confidence_score,expected_value,expected_cost,suggested_budget,currency,risk_level,status,expires_at,metadata)
    values((r->>'id')::uuid,p_org,p_run,r->>'recommendation_type',r->>'execution_service',r->>'title',r->>'summary',r->>'reason',r->>'priority',
      (r->>'score')::numeric,(r->>'confidence_score')::numeric,(r->>'expected_value')::numeric,(r->>'expected_cost')::numeric,
      (r->>'suggested_budget')::numeric,r->>'currency',r->>'risk_level','RECOMMENDED',(r->>'expires_at')::timestamptz,r->'metadata');
    for e in select * from jsonb_array_elements(r->'evidence') loop
      insert into recommendation_evidence(organization_id,recommendation_id,evidence_type,signal_id,intelligence_report_id,execution_result_id,description,weight)
      values(p_org,(r->>'id')::uuid,e->>'evidence_type',(e->>'signal_id')::uuid,(e->>'intelligence_report_id')::uuid,
        (e->>'execution_result_id')::uuid,e->>'description',(e->>'weight')::numeric);
    end loop;
  end loop;
  for r in select * from jsonb_array_elements(p_recommendations) loop
    for dep in select * from jsonb_array_elements(r->'dependencies') loop
      -- The planner only references this run; rejecting backwards/cyclic graphs is a DB invariant.
      if not exists(select 1 from recommendations where id=(dep #>> '{}')::uuid and organization_id=p_org and decision_run_id=p_run
        and (metadata->>'rank')::int < (r#>>'{metadata,rank}')::int) then raise exception 'Invalid dependency order'; end if;
      insert into recommendation_dependencies(organization_id,recommendation_id,depends_on_recommendation_id)
        values(p_org,(r->>'id')::uuid,(dep #>> '{}')::uuid);
    end loop;
  end loop;
  update decision_runs set status=case when p_partial then 'PARTIAL' else 'COMPLETED' end,
    completed_at=now(),input_snapshot=p_snapshot,output_summary=p_summary where id=p_run;
end $$;
create function public.de_fail_run(p_run uuid,p_org uuid,p_error text) returns void
language sql security definer set search_path=public,pg_temp as $$
  update decision_runs set status='FAILED',completed_at=now(),error_message=left(p_error,100)
    where id=p_run and organization_id=p_org and status='RUNNING';
$$;

-- CRM calls this with its admin user's JWT, never with the engine service key.
create function public.de_review(p_org uuid,p_recommendation uuid,p_decision text,p_parameters jsonb default null,p_reason text default null)
returns uuid language plpgsql security definer set search_path=public,pg_temp as $$
declare r recommendations; v_id uuid; v_parameters jsonb;
begin
  if not exists(select 1 from profiles where id=auth.uid() and role='admin') then raise exception 'Admin identity required'; end if;
  perform 1 from organizations where id=p_org for update;
  select * into r from recommendations where id=p_recommendation and organization_id=p_org for update;
  if not found or r.status <> 'RECOMMENDED' or r.expires_at <= now() then raise exception 'Recommendation not reviewable'; end if;
  if p_decision is null or p_decision not in ('APPROVED','MODIFIED','REJECTED') then raise exception 'Invalid decision'; end if;
  if r.recommendation_type='NO_ACTION' and p_decision <> 'REJECTED' then raise exception 'NO_ACTION cannot execute'; end if;
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
  if p_decision <> 'REJECTED' and ((v_parameters->>'budget_limit') is null or (v_parameters->>'budget_limit')::numeric <= 0 or
      (v_parameters->>'budget_limit')::numeric > r.suggested_budget or not (v_parameters ? 'budget_limit')) then
    raise exception 'Modification cannot increase original budget'; end if;
  insert into recommendation_reviews(organization_id,recommendation_id,decision,reviewed_by,original_parameters,approved_parameters,rejection_reason)
    values(p_org,p_recommendation,p_decision,auth.uid(),r.metadata->'parameters',v_parameters,p_reason) returning id into v_id;
  update recommendations set status=p_decision,updated_at=now() where id=p_recommendation;
  return v_id;
end $$;

-- The latest subject-specific readiness signal wins; older positive evidence cannot override a newer failure.
create function public.de_readiness_ready(p_org uuid,p_recommendation uuid,p_after timestamptz default null)
returns boolean language sql stable security definer set search_path=public,pg_temp as $$
 select coalesce((select s.value_numeric >= coalesce((run.input_snapshot#>>'{scoring_config,readiness_threshold}')::numeric,60)
   and s.confidence_score >= r.confidence_score
   and s.observed_at > coalesce(p_after, '-infinity'::timestamptz)
   and s.observed_at > now()-make_interval(days=>coalesce((run.input_snapshot#>>'{scoring_config,max_signal_age_days}')::int,30))
   and (s.expires_at is null or s.expires_at>now())
 from recommendations r join decision_runs run on run.id=r.decision_run_id
 join lateral (select * from market_signals where organization_id=p_org and metric='landing_page_readiness'
   and unit='score_0_100' and observed_at<=now()
   and coalesce(metadata->>'subject_key','organization')=coalesce(r.metadata#>>'{parameters,subject_key}','organization')
   order by observed_at desc,id desc limit 1) s on true
 where r.id=p_recommendation and r.organization_id=p_org),false);
$$;

-- Revalidate live constraints and reserve budget under a tenant lock before any request is created.
create function public.de_queue_approved(p_org uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r recommendations; review recommendation_reviews; c jsonb; cap execution_capabilities;
  used numeric; ad_used numeric; amount numeric; v_id uuid; output jsonb := '[]'; problem text; params jsonb;
begin
  perform 1 from organizations where id=p_org for update;
  select constraints into c from decision_constraints where organization_id=p_org for share;
  c:=coalesce(c,'{}');
  select coalesce(sum((requested_parameters->>'budget_limit')::numeric),0),
         coalesce(sum((requested_parameters->>'budget_limit')::numeric) filter(where execution_service in ('google_ads','meta_ads')),0)
    into used,ad_used from execution_requests where organization_id=p_org and status <> 'CANCELLED'
      and (created_at >= date_trunc('month',now()) or status in ('QUEUED','RUNNING','APPROVED'));
  used:=used+coalesce((c->>'committed_monthly_spend')::numeric,0);
  for r in select * from recommendations where organization_id=p_org and status in ('APPROVED','MODIFIED') order by created_at,id for update loop
    problem:=null;
    if r.expires_at <= now() then
      update recommendations set status='EXPIRED',updated_at=now() where id=r.id;
      continue;
    end if;
    select * into review from recommendation_reviews where organization_id=p_org and recommendation_id=r.id and decision in ('APPROVED','MODIFIED') order by reviewed_at desc limit 1;
    select * into cap from execution_capabilities where service_key=r.execution_service for share;
    params:=review.approved_parameters;
    amount:=(params->>'budget_limit')::numeric;
    if review.id is null or amount is null or amount <= 0 or amount > r.suggested_budget then problem:='Invalid approval budget';
    elsif cap.id is null or not cap.adapter_ready or not (cap.status='AVAILABLE' or (cap.status in ('PLANNED','MANUAL') and cap.allow_manual))
      or not (r.metadata->>'action_type'=any(cap.allowed_actions)) then problem:='Execution adapter unavailable';
    elsif not exists(select 1 from organization_services where organization_id=p_org and service_key=r.execution_service and is_enabled) then problem:='Service not enabled for organization';
    elsif exists(select 1 from recommendation_dependencies d join recommendations prerequisite on prerequisite.id=d.depends_on_recommendation_id
        where d.organization_id=p_org and d.recommendation_id=r.id and prerequisite.status<>'COMPLETED') then problem:='Dependency incomplete';
    elsif c->'blocked_channels' ? r.recommendation_type or (jsonb_array_length(coalesce(c->'allowed_channels','[]'))>0 and not (c->'allowed_channels' ? r.recommendation_type)) then problem:='Channel constraints changed';
    elsif not coalesce((select input_snapshot->'constraints' @> c from decision_runs where id=r.decision_run_id),false) then problem:='Client constraints changed; evaluate again';
    elsif coalesce((c->>'saturated')::boolean,false) then problem:='Client saturated';
    elsif r.confidence_score < coalesce((c->>'minimum_confidence')::numeric,0.65) then problem:='Confidence below current threshold';
    elsif array_position(array['LOW','MEDIUM','HIGH'],r.risk_level)>array_position(array['LOW','MEDIUM','HIGH'],coalesce(c->>'risk_tolerance','LOW')) then problem:='Risk exceeds current tolerance';
    elsif params->>'currency' is distinct from coalesce(c->>'currency','USD') then problem:='Currency changed';
    elsif params->'locations' is distinct from coalesce(c->'target_locations','[]') or params->'industries' is distinct from coalesce(c->'target_industries','[]')
       or params->'brand_restrictions' is distinct from coalesce(c->'brand_restrictions','[]') then problem:='Targeting or brand constraints changed';
    elsif r.recommendation_type='OUTREACH' and not coalesce((c->>'email_reputation_healthy')::boolean,false) then problem:='Email reputation not healthy';
    elsif r.recommendation_type='SEO' and coalesce((c->>'time_horizon_months')::int,3)<3 then problem:='SEO horizon too short';
    elsif used+amount > coalesce((c->>'monthly_marketing_budget')::numeric,0) then problem:='Monthly budget exhausted';
    elsif r.recommendation_type in ('GOOGLE_ADS','META_ADS') and ad_used+amount > coalesce((c->>'max_ad_spend')::numeric,0) then problem:='Ad budget exhausted';
    end if;
    if problem is null and r.recommendation_type='GOOGLE_ADS' then
      if not de_readiness_ready(p_org,r.id,(select max(x.completed_at) from recommendation_dependencies d
        join execution_requests q on q.recommendation_id=d.depends_on_recommendation_id
        join execution_results x on x.execution_request_id=q.id where d.recommendation_id=r.id))
        then problem:='Fresh landing-page readiness evidence required'; end if;
    end if;
    if problem is not null then
      output:=output||jsonb_build_array(jsonb_build_object('recommendation_id',r.id,'blocked',problem)); continue;
    end if;
    insert into execution_requests(organization_id,recommendation_id,review_id,execution_service,action_type,status,requested_parameters,constraints_snapshot,approved_by,approved_at)
      values(p_org,r.id,review.id,r.execution_service,r.metadata->>'action_type','QUEUED',params,c,review.reviewed_by,review.reviewed_at)
      on conflict(recommendation_id) do nothing returning id into v_id;
    if v_id is not null then
      used:=used+amount;
      if r.recommendation_type in ('GOOGLE_ADS','META_ADS') then ad_used:=ad_used+amount; end if;
      update recommendations set status='QUEUED',updated_at=now() where id=r.id;
      output:=output||jsonb_build_array(jsonb_build_object('recommendation_id',r.id,'execution_request_id',v_id));
    end if;
  end loop;
  return output;
end $$;

-- DevSpace One's authenticated server gateway claims one tenant/service request atomically.
create function public.de_claim_execution(p_org uuid,p_service text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r execution_requests; c jsonb;
begin
  perform 1 from organizations where id=p_org for update;
  if not exists(select 1 from execution_capabilities where service_key=p_service and adapter_ready
    and (status='AVAILABLE' or (status in ('PLANNED','MANUAL') and allow_manual))) then return null; end if;
  select * into r from execution_requests where organization_id=p_org and execution_service=p_service and status='QUEUED'
    order by created_at,id for update skip locked limit 1;
  if not found then return null; end if;
  select coalesce(constraints,'{}') into c from decision_constraints where organization_id=p_org for share;
  if not exists(select 1 from organization_services where organization_id=p_org and service_key=r.execution_service and is_enabled)
    or (r.execution_service='google_ads' and not de_readiness_ready(p_org,r.recommendation_id)) or coalesce(c,'{}') <> r.constraints_snapshot or exists(select 1 from recommendations where id=r.recommendation_id and expires_at<=now())
    or exists(select 1 from recommendation_dependencies d join recommendations p on p.id=d.depends_on_recommendation_id
      where d.recommendation_id=r.recommendation_id and p.status<>'COMPLETED') then
    update execution_requests set status='CANCELLED',updated_at=now() where id=r.id;
    update recommendations set status='EXPIRED',updated_at=now() where id=r.recommendation_id;
    return null;
  end if;
  update execution_requests set status='RUNNING',updated_at=now() where id=r.id;
  update recommendations set status='EXECUTING',updated_at=now() where id=r.recommendation_id;
  r.status:='RUNNING';
  return to_jsonb(r);
end $$;
create function public.de_record_result(p_org uuid,p_request uuid,p_status text,p_cost numeric,p_revenue numeric,p_metrics jsonb,p_results jsonb,p_error text default null)
returns uuid language plpgsql security definer set search_path=public,pg_temp as $$
declare r execution_requests; v_id uuid;
begin
  perform 1 from organizations where id=p_org for update;
  select * into r from execution_requests where id=p_request and organization_id=p_org for update;
  if not found then raise exception 'Unknown request'; end if;
  select id into v_id from execution_results where execution_request_id=p_request;
  if found then return v_id; end if;
  if r.status<>'RUNNING' or p_status is null or p_status not in ('COMPLETED','FAILED') then raise exception 'Invalid execution transition'; end if;
  insert into execution_results(execution_request_id,organization_id,execution_service,status,started_at,completed_at,cost,revenue_attributed,currency,subject_key,metrics,results,error_message)
    values(p_request,p_org,r.execution_service,p_status,r.updated_at,now(),p_cost,p_revenue,r.requested_parameters->>'currency',
      coalesce(r.requested_parameters->>'subject_key','organization'),p_metrics,p_results,p_error) returning id into v_id;
  update execution_requests set status=p_status,updated_at=now() where id=p_request;
  update recommendations set status=p_status,updated_at=now() where id=r.recommendation_id;
  return v_id;
end $$;

-- Tenant-scoped read policies. Global/null intelligence is intentionally not exposed or consumed.
do $$
declare t text;
begin
  foreach t in array array['decision_constraints','market_signals','intelligence_reports','intelligence_report_signals','decision_runs',
    'recommendations','recommendation_dependencies','recommendation_reviews','recommendation_evidence','execution_requests','execution_results'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('revoke all on public.%I from anon, authenticated',t);
    execute format('grant select on public.%I to authenticated',t);
    execute format('create policy de_read on public.%I for select to authenticated using (exists(select 1 from public.profiles where id=auth.uid() and (role=''admin'' or organization_id=%I.organization_id)))',t,t);
    execute format('grant all on public.%I to service_role',t);
  end loop;
end $$;
alter table public.execution_capabilities enable row level security;
revoke all on public.execution_capabilities from anon,authenticated;
grant select on public.execution_capabilities to authenticated;
grant all on public.execution_capabilities to service_role;
create policy de_capability_read on public.execution_capabilities for select to authenticated using (true);
-- All functions are denied by default; service-role never receives the review function.
do $$
declare f record;
begin
  for f in select oid::regprocedure as signature, proname from pg_proc where pronamespace='public'::regnamespace and proname like 'de_%' loop
    execute format('revoke all on function %s from public, anon, authenticated, service_role',f.signature);
    if f.proname='de_review' then execute format('grant execute on function %s to authenticated',f.signature);
    else execute format('grant execute on function %s to service_role',f.signature); end if;
  end loop;
end $$;
commit;
