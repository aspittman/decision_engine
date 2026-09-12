"""Real PostgreSQL contract tests, opt in with DE_TEST_DATABASE_URL or install pgserver.

Never point DE_TEST_DATABASE_URL at a populated database: fixture creates public contract tables.
"""
import os
from pathlib import Path
from dataclasses import asdict
import pytest
from conftest import add_signals, SAAS, ROOFING
from test_engine import MemoryRepository
from decision_engine.models.contracts import uid
from decision_engine.services.decision_service import DecisionService


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    psycopg = pytest.importorskip("psycopg")
    uri = os.getenv("DE_TEST_DATABASE_URL")
    server = None
    if not uri:
        pgserver = pytest.importorskip("pgserver")
        server = pgserver.get_server(tmp_path_factory.mktemp("postgres") / "data")
        uri = server.get_uri()
    with psycopg.connect(uri, autocommit=True) as db:
        if db.execute("select to_regclass('public.organizations')").fetchone()[0]:
            pytest.fail("Database must be empty; refusing to modify existing CRM")
        db.execute("""
          create role anon; create role authenticated; create role service_role bypassrls;
          create schema auth;
          create function auth.uid() returns uuid language sql as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
          grant usage on schema auth to authenticated,service_role;
          create table organizations(id uuid primary key, name text);
          create table organization_services(id uuid primary key default gen_random_uuid(), organization_id uuid references organizations(id), service_key text, is_enabled boolean default true);
          create table profiles(id uuid primary key, role text, organization_id uuid references organizations(id));
          grant select on profiles to authenticated;
        """)
        db.execute(Path("migrations/014_decision_engine.sql").read_text())
        yield db
    if server:
        server.cleanup()


@pytest.fixture
def persisted(database, context, config):
    db = database
    db.execute("reset role")
    org, admin = context.organization_id, uid()
    db.execute("insert into organizations values(%s,'ABC Roofing')",(org,))
    db.execute("insert into profiles values(%s,'admin',%s)",(admin,org))
    db.execute("insert into decision_constraints(organization_id,constraints) values(%s,%s::jsonb)",(org,__import__('json').dumps(asdict(context.constraints))))
    db.execute("insert into organization_services(organization_id,service_key) values(%s,'devspace_outreach')",(org,))
    add_signals(context, SAAS)
    for s in context.signals:
        db.execute("insert into market_signals(id,organization_id,subject_type,signal_type,metric,value_numeric,unit,confidence_score,source,observed_at) values(%s,%s,'organization','opportunity',%s,%s,'score_0_100',%s,%s,%s)",
                   (s.id,org,s.metric,s.value,s.confidence,s.source,s.observed_at))
    repo = MemoryRepository(context)
    result = DecisionService(repo,config).run(org)
    _,_,rows,snapshot,summary,partial = repo.saved
    db.execute("set role service_role")
    run = db.execute("select de_start_run(%s,'MANUAL_REQUEST')",(org,)).fetchone()[0]
    import json
    db.execute("select de_finish_run(%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s)", (run,org,json.dumps(rows),json.dumps(snapshot),json.dumps(summary),partial))
    db.execute("reset role")
    yield db,org,admin,rows[0]["id"]
    db.execute("reset role")


def review(db,org,admin,rec,decision="APPROVED",params=None):
    import json
    db.execute("select set_config('request.jwt.claim.sub',%s,false)",(admin,))
    db.execute("set role authenticated")
    try:
        return db.execute("select de_review(%s,%s,%s,%s::jsonb)",(org,rec,decision,json.dumps(params) if params is not None else None)).fetchone()[0]
    finally:
        db.execute("reset role")


def dispatch(db,org):
    db.execute("set role service_role")
    try:
        return db.execute("select de_queue_approved(%s)",(org,)).fetchone()[0]
    finally:
        db.execute("reset role")


def test_approval_claim_feedback_idempotency(persisted):
    db,org,admin,rec = persisted
    assert dispatch(db,org)==[]
    review(db,org,admin,rec)
    db.execute("update execution_capabilities set adapter_ready=false where service_key='devspace_outreach'")
    assert dispatch(db,org)[0]["blocked"] == "Execution adapter unavailable"
    db.execute("update execution_capabilities set adapter_ready=true where service_key='devspace_outreach'")
    request=dispatch(db,org)[0]["execution_request_id"]
    assert dispatch(db,org)==[]
    db.execute("set role service_role")
    claimed=db.execute("select de_claim_execution(%s,'devspace_outreach')",(org,)).fetchone()[0]
    assert claimed["id"]==request and claimed["status"]=="RUNNING"
    assert db.execute("select de_claim_execution(%s,'devspace_outreach')",(org,)).fetchone()[0] is None
    first=db.execute("select de_record_result(%s,%s,'COMPLETED',100,500,'{\"leads\":8}','{}')",(org,request)).fetchone()[0]
    assert first==db.execute("select de_record_result(%s,%s,'COMPLETED',100,500,'{\"leads\":8}','{}')",(org,request)).fetchone()[0]
    assert db.execute("select status from recommendations where id=%s",(rec,)).fetchone()[0]=="COMPLETED"


def test_review_authentication_and_immutable_original(persisted):
    import psycopg
    db,org,admin,rec=persisted
    db.execute("set role service_role")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select de_review(%s,%s,'APPROVED')",(org,rec))
    db.execute("reset role")
    for params in ({"budget_limit":2000},{"budget_limit":None},{"budget_limit":-1},{"locations":["Anywhere"]}):
        with pytest.raises(psycopg.Error):
            review(db,org,admin,rec,"MODIFIED",params)
    review(db,org,admin,rec,"MODIFIED",{"budget_limit":75})
    assert db.execute("select metadata#>>'{parameters,budget_limit}' from recommendations where id=%s",(rec,)).fetchone()[0]=='150.0'
    row=db.execute("select original_parameters,approved_parameters,reviewed_by from recommendation_reviews where recommendation_id=%s",(rec,)).fetchone()
    assert row[0]["budget_limit"]==150 and row[1]["budget_limit"]==75 and str(row[2])==admin
    with pytest.raises(psycopg.Error):
        review(db,org,admin,rec)


def test_rls_and_cross_tenant_foreign_keys(persisted):
    import psycopg
    db,org,admin,rec=persisted
    other,user=uid(),uid()
    db.execute("insert into organizations values(%s,'Other customer')",(other,))
    db.execute("insert into profiles values(%s,'customer',%s)",(user,other))
    db.execute("select set_config('request.jwt.claim.sub',%s,false)",(user,))
    db.execute("set role authenticated")
    assert db.execute("select count(*) from recommendations where organization_id=%s",(org,)).fetchone()[0]==0
    with pytest.raises(psycopg.Error):
        db.execute("select de_review(%s,%s,'APPROVED')",(org,rec))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update recommendations set status='APPROVED' where id=%s",(rec,))
    db.execute("reset role")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute("insert into recommendation_evidence(organization_id,recommendation_id,evidence_type,description) values(%s,%s,'RULE','bad tenant')",(other,rec))


def test_constraints_changed_after_queue(persisted):
    db,org,admin,rec=persisted
    db.execute("update execution_capabilities set adapter_ready=true where service_key='devspace_outreach'")
    review(db,org,admin,rec)
    request=dispatch(db,org)[0]["execution_request_id"]
    db.execute("update decision_constraints set constraints=jsonb_set(constraints,'{monthly_marketing_budget}','0') where organization_id=%s",(org,))
    assert db.execute("select de_claim_execution(%s,'devspace_outreach')",(org,)).fetchone()[0] is None
    assert db.execute("select status from execution_requests where id=%s",(request,)).fetchone()[0]=='CANCELLED'


def test_run_lock_and_atomic_rollback(persisted):
    import psycopg, json
    db,org,admin,rec=persisted
    run=db.execute("select de_start_run(%s,'MANUAL_REQUEST')",(org,)).fetchone()[0]
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("select de_start_run(%s,'MANUAL_REQUEST')",(org,))
    with pytest.raises(psycopg.Error):
        db.execute("select de_finish_run(%s,%s,%s::jsonb,'{}','{}',false)",(run,org,json.dumps([{"id":uid(),"organization_id":org,"evidence":[]}])) )
    assert db.execute("select count(*) from recommendations where decision_run_id=%s",(run,)).fetchone()[0]==0
    db.execute("select de_fail_run(%s,%s,'test_failure')",(run,org))


def test_concurrent_queue_attempts(persisted):
    import psycopg
    from concurrent.futures import ThreadPoolExecutor
    db,org,admin,rec=persisted
    db.execute("update execution_capabilities set adapter_ready=true where service_key='devspace_outreach'")
    review(db,org,admin,rec)
    def queue():
        with psycopg.connect(db.info.dsn,autocommit=True) as other:
            other.execute("set role service_role")
            return other.execute("select de_queue_approved(%s)",(org,)).fetchone()[0]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda _:queue(),range(2)))
    assert sum(len(r) for r in results)==1
    assert db.execute("select count(*) from execution_requests where recommendation_id=%s",(rec,)).fetchone()[0]==1


def test_dependency_gates_and_latest_readiness(database,context,config):
    import json
    from conftest import ROOFING
    from decision_engine.models.contracts import now
    from datetime import timedelta
    db=database
    org,admin=context.organization_id,uid()
    db.execute("reset role")
    db.execute("insert into organizations values(%s,'Roofing dependencies')",(org,))
    db.execute("insert into profiles values(%s,'admin',%s)",(admin,org))
    db.execute("insert into decision_constraints(organization_id,constraints) values(%s,%s::jsonb)",(org,json.dumps(asdict(context.constraints))))
    db.execute("insert into organization_services(organization_id,service_key) values(%s,'google_ads'),(%s,'landing_page')",(org,org))
    add_signals(context,ROOFING|{"landing_page_readiness":15,"missing_cta":95,"broken_forms":95,"mobile_issues":90})
    for s in context.signals:
        db.execute("insert into market_signals(id,organization_id,subject_type,signal_type,metric,value_numeric,unit,confidence_score,source,observed_at) values(%s,%s,'organization','opportunity',%s,%s,'score_0_100',%s,%s,%s)",
                   (s.id,org,s.metric,s.value,s.confidence,s.source,s.observed_at))
    repo=MemoryRepository(context)
    DecisionService(repo,config).run(org)
    _,_,rows,snapshot,summary,partial=repo.saved
    run=db.execute("select de_start_run(%s,'MANUAL_REQUEST')",(org,)).fetchone()[0]
    db.execute("select de_finish_run(%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,false)",(run,org,json.dumps(rows),json.dumps(snapshot),json.dumps(summary)))
    by_kind={r["recommendation_type"]:r["id"] for r in rows}
    for rec in by_kind.values():
        review(db,org,admin,rec)
    db.execute("update execution_capabilities set status='AVAILABLE',adapter_ready=true where service_key in ('google_ads','landing_page')")
    queued=dispatch(db,org)
    assert any(r.get("blocked")=="Dependency incomplete" for r in queued)
    page_request=next(r["execution_request_id"] for r in queued if "execution_request_id" in r)
    db.execute("select de_claim_execution(%s,'landing_page')",(org,))
    db.execute("select de_record_result(%s,%s,'COMPLETED',200,null,'{}','{}')",(org,page_request))
    assert dispatch(db,org)[0]["blocked"]=="Fresh landing-page readiness evidence required"
    db.execute("insert into market_signals(organization_id,subject_type,signal_type,metric,value_numeric,unit,confidence_score,source,observed_at) values(%s,'organization','audit','landing_page_readiness',90,'score_0_100',0.99,'website_audit',clock_timestamp())",(org,))
    assert dispatch(db,org)[0].get("execution_request_id")
    db.execute("insert into market_signals(organization_id,subject_type,signal_type,metric,value_numeric,unit,confidence_score,source,observed_at) values(%s,'organization','audit','landing_page_readiness',10,'score_0_100',0.99,'website_audit',clock_timestamp())",(org,))
    assert db.execute("select de_claim_execution(%s,'google_ads')",(org,)).fetchone()[0] is None


def test_service_disabled_for_tenant(persisted):
    db,org,admin,rec=persisted
    db.execute("update execution_capabilities set adapter_ready=true where service_key='devspace_outreach'")
    db.execute("update organization_services set is_enabled=false where organization_id=%s",(org,))
    review(db,org,admin,rec)
    assert dispatch(db,org)[0]["blocked"]=='Service not enabled for organization'


def test_rejected_recommendation_never_queues(persisted):
    db,org,admin,rec=persisted
    review(db,org,admin,rec,'REJECTED')
    assert dispatch(db,org)==[]
    assert db.execute("select status from recommendations where id=%s",(rec,)).fetchone()[0]=='REJECTED'


def test_planned_service_needs_explicit_manual_opt_in(persisted):
    db,org,admin,rec=persisted
    review(db,org,admin,rec)
    db.execute("update execution_capabilities set status='PLANNED',adapter_ready=true,allow_manual=false where service_key='devspace_outreach'")
    assert dispatch(db,org)[0]["blocked"]=='Execution adapter unavailable'
    db.execute("update execution_capabilities set allow_manual=true where service_key='devspace_outreach'")
    assert dispatch(db,org)[0].get('execution_request_id')
    db.execute("update execution_capabilities set status='AVAILABLE',allow_manual=false where service_key='devspace_outreach'")


def test_existing_request_budget_reservation(persisted):
    db,org,admin,rec=persisted
    db.execute("update execution_capabilities set status='AVAILABLE',adapter_ready=true where service_key='devspace_outreach'")
    review(db,org,admin,rec)
    request=dispatch(db,org)[0]['execution_request_id']
    # An existing approved envelope occupies most of the monthly budget.
    db.execute("update execution_requests set requested_parameters=jsonb_set(requested_parameters,'{budget_limit}','1450') where id=%s",(request,))
    db.execute("update recommendations set status='COMPLETED' where id=%s",(rec,))
    new=uid()
    with db.transaction():
        db.execute("""insert into recommendations(id,organization_id,decision_run_id,recommendation_type,execution_service,title,summary,reason,priority,score,
          confidence_score,expected_cost,suggested_budget,currency,risk_level,status,expires_at,metadata)
          select %s,organization_id,decision_run_id,recommendation_type,execution_service,title,summary,reason,priority,score,
          confidence_score,expected_cost,suggested_budget,currency,risk_level,'RECOMMENDED',expires_at,metadata from recommendations where id=%s""",(new,rec))
        db.execute("insert into recommendation_evidence(organization_id,recommendation_id,evidence_type,description) values(%s,%s,'RULE','Budget reservation regression fixture')",(org,new))
    review(db,org,admin,new)
    assert dispatch(db,org)[0]['blocked']=='Monthly budget exhausted'


def test_evidence_and_review_history_retained(persisted):
    import psycopg
    db,org,admin,rec=persisted
    with pytest.raises(psycopg.Error,match='retain evidence'):
        db.execute('delete from recommendation_evidence where recommendation_id=%s',(rec,))
    review(db,org,admin,rec)
    with pytest.raises(psycopg.Error,match='append-only'):
        db.execute('delete from recommendation_reviews where recommendation_id=%s',(rec,))
