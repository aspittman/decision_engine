import json
import sqlite3
from pathlib import Path
import pytest
from monitoring import capability_probe as probe
from monitoring import receipts

ORG='11111111-1111-4111-8111-111111111111'
PROFILE={'engine_id':'mmonolith','url_env':'URL','secret_env':'SECRET','fallback_route':'/context','services':{'domain_merchant':{'inputs':['intelligence_reports']}}}
ENV={'URL':'https://example.invalid','SECRET':'never-print-this'}


def test_empty_scoped_read_is_valid(monkeypatch):
    monkeypatch.setattr(probe,'get',lambda *a:{'organization_id':ORG,'engine_id':'mmonolith','service_id':'domain_merchant','connectivity_status':'CONNECTED','reads':{'intelligence_reports':{'status':'VERIFIED','reason':'0 rows'}}})
    result=probe.probe(PROFILE,[ORG],ENV)['service_capabilities']['domain_merchant']
    assert result['connectivity_status']=='CONNECTED' and result['reads']['intelligence_reports']['status']=='VERIFIED'
    assert result['write_status']=='UNVERIFIED' and 'work_expected' not in result


def test_legacy_read_fallback(monkeypatch):
    calls=[]
    def get(url,*args):
        calls.append(url)
        if 'monitoring-capabilities' in url:raise probe.ProbeFailure('UNKNOWN','CRM HTTP 404')
        return {'intelligence_reports':[]}
    monkeypatch.setattr(probe,'get',get)
    result=probe.probe(PROFILE,[ORG],ENV)['service_capabilities']['domain_merchant']
    assert len(calls)==2 and result['reads']['intelligence_reports']['status']=='VERIFIED'


@pytest.mark.parametrize('status', ['DISCONNECTED','DEGRADED','UNKNOWN'])
def test_failures_are_scoped_and_secrets_absent(monkeypatch,status):
    def fail(*a):raise probe.ProbeFailure(status,'Safe diagnostic reason')
    monkeypatch.setattr(probe,'get',fail)
    result=probe.probe(PROFILE,[ORG],ENV)
    assert result['service_capabilities']['domain_merchant']['connectivity_status']==status
    assert ENV['SECRET'] not in json.dumps(result)


def test_scope_mismatch_rejected(monkeypatch):
    monkeypatch.setattr(probe,'get',lambda *a:{'organization_id':'other','engine_id':'mmonolith','service_id':'domain_merchant'})
    assert probe.probe(PROFILE,[ORG],ENV)['service_capabilities']['domain_merchant']['connectivity_status']=='UNKNOWN'


def test_no_credentials_or_org_does_not_request(monkeypatch):
    monkeypatch.setattr(probe,'get',lambda *a:pytest.fail('must not request'))
    assert probe.probe(PROFILE,[ORG],{})['service_capabilities']['domain_merchant']['connectivity_status']=='UNKNOWN'
    assert probe.probe(PROFILE,[],ENV)['service_capabilities']['domain_merchant']['connectivity_status']=='UNKNOWN'


def test_missing_state_not_created(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'ROOT',tmp_path)
    with pytest.raises(probe.ProbeFailure):probe.state_reads(ORG,{})
    assert not (tmp_path/'data/orchestrator.sqlite3').exists()


def test_state_read_only_and_zero_rows(tmp_path):
    path=tmp_path/'state.db'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE workflow_runs(id TEXT, organization_id TEXT); CREATE TABLE stage_runs(id TEXT, workflow_run_id TEXT);')
    before=path.read_bytes()
    result=probe.state_reads(ORG,{'ORCHESTRATOR_SQLITE_PATH':str(path)})
    assert all(r['status']=='VERIFIED' for r in result.values())
    assert path.read_bytes()==before


def test_receipt_has_no_invented_workflow_or_payload(tmp_path,monkeypatch):
    path=tmp_path/'receipt.jsonl';monkeypatch.setenv('DEVSPACE_CAPABILITY_EVENTS',str(path))
    assert receipts.record('mmonolith','domain_merchant',ORG,'intelligence_reports','report-id','write_persisted')
    row=json.loads(path.read_text())
    assert row['workflow_run_id'] is None and row['metadata']=={'table':'intelligence_reports','record_id':'report-id'}


def test_receipt_failure_nonfatal(monkeypatch,tmp_path):
    monkeypatch.setenv('DEVSPACE_CAPABILITY_EVENTS',str(tmp_path))
    assert receipts.record('mmonolith','domain_merchant',ORG,'intelligence_reports','id','write_persisted') is False
    receipts.recommendation_writes(ORG,[{'parameters':None}])
