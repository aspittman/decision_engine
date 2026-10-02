import json
from io import BytesIO
from urllib.error import HTTPError, URLError
import pytest
from decision_engine.clients.crm_client import CRMClient, CRMError
from decision_engine.config.settings import CRMSettings
from decision_engine.repositories.crm import CRMRepository
from decision_engine.models.contracts import uid

class Response(BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def stub(client, values):
    calls = []
    def open_(request, timeout):
        calls.append((request, timeout))
        value = values.pop(0)
        if isinstance(value, Exception): raise value
        return Response(value if isinstance(value, bytes) else json.dumps({'success': True, 'data': value}).encode())
    client.opener.open = open_
    return calls


def test_auth_and_timeout():
    client = CRMClient('https://crm.example', 'secret', timeout=12)
    org = uid()
    calls = stub(client, [[]])
    assert client.get_execution_results(org) == []
    request, timeout = calls[0]
    assert request.get_header('Authorization') == 'Bearer secret'
    assert timeout == 12 and 'organization_id=' + org in request.full_url
    assert 'apikey' not in request.headers
    assert 'secret' not in repr(CRMSettings('https://crm.example', 'secret'))


@pytest.mark.parametrize('body', [b'not json', b'[]', b'{"success":true}', b'{"success":false,"data":[]}'])
def test_malformed(body):
    client = CRMClient('https://crm.example', 'secret')
    stub(client, [body])
    with pytest.raises(CRMError, match='Malformed'): client.get_organizations()


def test_read_retries_but_write_never_retried(monkeypatch):
    monkeypatch.setattr('decision_engine.clients.crm_client.time.sleep', lambda _: None)
    client = CRMClient('https://crm.example', 'secret')
    calls = stub(client, [URLError('secret'), TimeoutError('secret'), []])
    assert client.get_organizations() == [] and len(calls) == 3
    calls = stub(client, [TimeoutError('secret')])
    with pytest.raises(CRMError, match='connection failed') as caught:
        client.create_decision_run(uid(), 'MANUAL_REQUEST')
    assert len(calls) == 1 and 'secret' not in str(caught.value)


@pytest.mark.parametrize('status', [401,403,404,409])
def test_non_success_not_retried(status):
    client = CRMClient('https://crm.example', 'secret')
    calls = stub(client, [HTTPError('https://crm.example', status, 'secret', {}, BytesIO(b'secret'))])
    with pytest.raises(CRMError, match=str(status)): client.get_organizations()
    assert len(calls) == 1


def test_isolation_and_invalid_org():
    client = CRMClient('https://crm.example', 'secret')
    calls = stub(client, [[{'organization_id': uid()}]])
    with pytest.raises(CRMError, match='Cross-organization'): client.get_market_signals(uid())
    with pytest.raises(ValueError): client.get_market_signals('invalid')
    assert len(calls) == 1
    with pytest.raises(ValueError): client.create_recommendations(uid(), uid(), [{'organization_id': uid()}], {}, {})


def test_creation_and_evidence():
    client = CRMClient('https://crm.example', 'secret')
    org, run, rec = uid(), uid(), uid()
    calls = stub(client, [run, None, None])
    assert client.create_decision_run(org, 'MANUAL_REQUEST') == run
    client.create_recommendation(org, run, {'id':rec, 'organization_id':org, 'evidence':[]}, {}, {})
    client.attach_recommendation_evidence(org, rec, [{'evidence_type':'RULE', 'description':'Test', 'weight':None}])
    assert all(json.loads(c[0].data)['organization_id'] == org for c in calls)
    assert calls[-1][0].full_url.endswith('/' + rec + '/evidence')
    assert not hasattr(client, 'approve') and not hasattr(CRMRepository, 'dispatch')


@pytest.mark.parametrize('url', ['http://example.com','https://user:pass@example.com','https://example.com/path','https://example.com?token=secret'])
def test_reject_unsafe_origin(url):
    with pytest.raises(ValueError): CRMClient(url, 'secret')


@pytest.mark.parametrize('fraction', ['1','12','123','1234','12345','123456'])
def test_postgrest_timestamp_fractional_precision(fraction):
    from decision_engine.models.contracts import timestamp
    parsed = timestamp('2026-09-12T13:05:32.' + fraction + '-06:00')
    assert parsed.microsecond == int(fraction.ljust(6, '0'))


def test_context_validates_every_tenant_table(config):
    client = CRMClient('https://crm.example', 'secret')
    org = uid()
    data = {key: [] for key in ['organizations','organization_services','decision_constraints','market_signals',
        'intelligence_reports','intelligence_report_signals','execution_results','recommendations','execution_requests','execution_capabilities']}
    data['organizations'] = [{'id': org}]
    data['organization_services'] = [{'id': uid(), 'organization_id': org, 'service_key':'seo', 'is_enabled':False, 'config_json':{'niche':'roofing'}}]
    data['execution_capabilities'] = [{'service_key':'seo','status':'AVAILABLE'}]
    stub(client, [data])
    context = CRMRepository(client, config).context(org)
    assert context.capabilities['seo'] == 'UNAVAILABLE'
    assert list(context.profile['organization_configuration'].values()) == [{'niche':'roofing'}]
    data['intelligence_report_signals'] = [{'organization_id':uid()}]
    stub(client, [data])
    with pytest.raises(CRMError,match='Cross-organization'): client.get_organization_context(org)


def test_approved_request_budget_not_counted_twice(config):
    from decision_engine.repositories.crm import ContextRows
    from decision_engine.repositories.store import Repository
    from decision_engine.models.contracts import now
    org, rec = uid(), uid()
    data = {key: [] for key in ['organizations','decision_constraints','market_signals','intelligence_reports',
        'intelligence_report_signals','execution_results','recommendations','execution_requests','execution_capabilities']}
    data['organizations'] = [{'id': org}]
    data['recommendations'] = [{'id':rec,'organization_id':org,'status':'MODIFIED','suggested_budget':100,'recommendation_type':'OUTREACH'}]
    data['execution_requests'] = [{'id':uid(),'organization_id':org,'recommendation_id':rec,'status':'APPROVED',
        'created_at':now().isoformat(),'requested_parameters':{'budget_limit':50},'execution_service':'devspace_outreach'}]
    assert Repository(ContextRows(data),config).context(org).profile['reserved_budget'] == 50
