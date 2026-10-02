"""Isolated PostgreSQL validation of migration 025 and the existing persistence RPC.

Identity scaffolding uses CRM's actual columns; no RLS is disabled. These tests
exercise decision persistence, not MMonolith publication or a live CRM deployment.
"""
import json
from pathlib import Path
from dataclasses import asdict
import pytest
from test_database import database, review, dispatch
from test_service_decisions import domain, demand, product, report
from decision_engine.models.contracts import uid
from decision_engine.services.recommendations import recommend


@pytest.fixture(scope='module')
def service_db(database):
    db = database
    db.execute('''
      create table service_registry(service_id text primary key);
      insert into service_registry values ('domain_merchant'),('devspace_services'),('devspace_clients'),('scholarship_research'),('investor_research');
      create function canonical_service_id(value text) returns text language sql as $$ select service_id from service_registry where service_id=value $$;
      create table workflow_runs(id text primary key,organization_id text,service_id text,workflow_type text,parent_run_id text,correlation_id text);
      alter table recommendations add column service_id text references service_registry(service_id), add column workflow_run_id text references workflow_runs(id);
      alter table intelligence_reports add column service_id text references service_registry(service_id), add column workflow_run_id text references workflow_runs(id);
      grant select on service_registry,workflow_runs to service_role;
    ''')
    db.execute(Path('migrations/025_service_decisions.sql').read_text())
    db.execute('''create trigger recommendation_workflow_context before insert on recommendations for each row execute function validate_record_context()''')
    return db


def setup(db, context):
    org = context.organization_id
    admin = uid()
    db.execute('reset role')
    db.execute("insert into organizations values(%s,'Service test')", (org,))
    db.execute("insert into profiles values(%s,'admin',%s)", (admin, org))
    db.execute('insert into decision_constraints(organization_id,constraints) values(%s,%s::jsonb)', (org, json.dumps(asdict(context.constraints))))
    for s in context.profile['organization_services']:
        db.execute('insert into organization_services(organization_id,service_key) values(%s,%s)', (org, s['service_key']))
    for r in context.reports:
        db.execute('insert into intelligence_reports(id,organization_id,subject_type,report_type,summary,confidence_score,status) values(%s,%s,%s,%s,%s,%s,%s)',
                   (r['id'], org, r['subject_type'], r['report_type'], 'Fixture normalized research', r['confidence_score'], 'CURRENT'))
    return admin


def persist(db, context, rows):
    db.execute('set role service_role')
    try:
        run = db.execute("select de_start_run(%s,'MANUAL_REQUEST')", (context.organization_id,)).fetchone()[0]
        db.execute('select de_finish_run(%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,false)',
                   (run, context.organization_id, json.dumps(rows), json.dumps({'constraints': asdict(context.constraints)}), json.dumps({'execution_status': 'COMPLETED'})))
        return run
    finally:
        db.execute('reset role')


@pytest.mark.parametrize('service', ['domain_merchant', 'devspace_services', 'devspace_clients', 'scholarship_research', 'investor_research'])
def test_all_five_persist_references_and_approval_never_executes(service_db, context, config, service):
    db = service_db
    if service == 'domain_merchant': domain(context)
    elif service == 'devspace_services': demand(context)
    elif service in ('scholarship_research', 'investor_research'): product(context, service)
    else:
        report(context, service, [{'id': 'client', 'status': 'REVIEW', 'fit_score': 80, 'fit_confidence': .7,
               'evidence': [{'source_reference': 'https://client.example', 'observed_at': context.evaluated_at.isoformat()}]}])
    admin = setup(db, context)
    rows, _ = recommend(context, config, service)
    run = persist(db, context, rows)
    stored = db.execute('select service_id,score,confidence_score,execution_service,workflow_run_id from recommendations where id=%s', (rows[0]['id'],)).fetchone()
    assert stored[0] == service and stored[3:] == (None, None)
    assert db.execute('select intelligence_report_id from recommendation_evidence where recommendation_id=%s and evidence_type=\'INTELLIGENCE_REPORT\'', (rows[0]['id'],)).fetchone()[0] == __import__('uuid').UUID(context.reports[0]['id'])
    assert db.execute('select status from decision_runs where id=%s', (run,)).fetchone()[0] == 'COMPLETED'
    assert dispatch(db, context.organization_id) == []
    review(db, context.organization_id, admin, rows[0]['id'])
    assert dispatch(db, context.organization_id) == []
    assert db.execute('select count(*) from execution_requests where organization_id=%s', (context.organization_id,)).fetchone()[0] == 0


def test_scoped_uniqueness_and_foreign_workflow_rejection(service_db, context, config):
    db = service_db
    r = domain(context)
    second = __import__('copy').deepcopy(r['metadata']['candidates'][0]); second['domain'] = 'another.com'
    r['metadata']['candidates'].append(second)
    setup(db, context)
    identity = {'organization_id': context.organization_id, 'service_id': 'domain_merchant', 'workflow_run_id': uid(), 'parent_run_id': None,
                'correlation_id': r['correlation_id'], 'source_engine': 'mmonolith'}
    r['metadata']['workflow_context'] = identity
    db.execute('insert into workflow_runs(id,organization_id,service_id,workflow_type,correlation_id) values(%s,%s,%s,%s,%s)',
               (identity['workflow_run_id'], context.organization_id, 'domain_merchant', 'domain', r['correlation_id']))
    rows, _ = recommend(context, config, 'domain_merchant')
    assert len(rows) == 2
    persist(db, context, rows)
    assert db.execute('select workflow_run_id from recommendations where id=%s', (rows[0]['id'],)).fetchone()[0] == identity['workflow_run_id']
    # Duplicate active decision is rejected atomically by the scoped index.
    with pytest.raises(Exception): persist(db, context, rows)
    db.execute("update decision_runs set status='FAILED' where organization_id=%s and status='RUNNING'", (context.organization_id,))
    rows[0]['id'] = uid(); rows[0]['metadata']['decision_key'] += ':foreign'
    rows[0]['metadata']['workflow_context']['correlation_id'] = 'wrong-correlation'
    with pytest.raises(Exception): persist(db, context, rows[:1])
    assert db.execute('select count(*) from recommendations where id=%s', (rows[0]['id'],)).fetchone()[0] == 0
