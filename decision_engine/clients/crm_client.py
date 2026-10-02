"""Versioned server contract; no Supabase credentials or execution operations."""
import json
import logging
from http.client import HTTPException
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import UUID
from decision_engine.monitoring_receipts import recommendation_writes, context_reads

log = logging.getLogger(__name__)


class CRMError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CRMClient:
    def __init__(self, url, secret, timeout=30):
        parsed = urlparse(url)
        local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
        if (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('CRM_API_URL must be an HTTPS origin (HTTP allowed on loopback only)')
        if not secret or timeout <= 0:
            raise ValueError('CRM secret and positive timeout required')
        self.url, self._secret, self.timeout = url.rstrip('/') + '/api/decision-engine/', secret, timeout
        self.opener = build_opener(NoRedirect())

    def _request(self, method, path, payload=None, params=None):
        request = Request(self.url + path + ('?' + urlencode(params) if params else ''),
                          data=json.dumps(payload, allow_nan=False).encode() if payload is not None else None,
                          method=method, headers={'Authorization': 'Bearer ' + self._secret, 'Content-Type': 'application/json'})
        for attempt in range(3 if method == 'GET' else 1):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    if not 200 <= response.status < 300:
                        raise CRMError('Unexpected CRM HTTP status')
                    try:
                        envelope = json.loads(response.read())
                    except (ValueError, UnicodeError):
                        raise CRMError('Malformed CRM response') from None
                    if not isinstance(envelope, dict) or envelope.get('success') is not True or 'data' not in envelope:
                        raise CRMError('Malformed CRM response')
                    return envelope['data']
            except HTTPError as error:
                retry = method == 'GET' and error.code in (429, 500, 502, 503, 504) and attempt < 2
                log.warning('crm_http_failure', extra={'context': {'status': error.code, 'retry': retry}})
                error.close()
                if not retry:
                    raise CRMError(f'CRM request failed with HTTP {error.code}') from None
            except (URLError, TimeoutError, OSError, HTTPException):
                if method != 'GET' or attempt == 2:
                    raise CRMError('CRM connection failed') from None
                log.warning('crm_read_retry')
            time.sleep(0.25 * 2 ** attempt)

    @staticmethod
    def _org(organization_id):
        return str(UUID(organization_id))

    @staticmethod
    def _rows(data, org=None, organizations=False):
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise CRMError('Malformed CRM rows')
        if org and any(row.get('id' if organizations else 'organization_id') != org for row in data):
            raise CRMError('Cross-organization response rejected')
        return data

    def get_organizations(self):
        data = self._rows(self._request('GET', 'organizations'))
        for row in data:
            self._org(row.get('id'))
        return data

    def get_organization_context(self, organization_id):
        org = self._org(organization_id)
        data = self._request('GET', 'context', params={'organization_id': org})
        if not isinstance(data, dict):
            raise CRMError('Malformed CRM context')
        for table in ('organizations', 'organization_services', 'decision_constraints', 'market_signals',
                      'intelligence_reports', 'intelligence_report_signals', 'execution_results', 'recommendations', 'execution_requests'):
            self._rows(data.get(table), org, table == 'organizations')
        for table in ('predictions', 'feedback_evaluations', 'intelligence_report_feedback'):
            if table in data: self._rows(data[table], org)
        if len(data['organizations']) != 1:
            raise CRMError('Organization not found')
        self._rows(data.get('execution_capabilities'))
        context_reads('decision_engine', org, data)
        return data

    def _read(self, resource, organization_id):
        org = self._org(organization_id)
        return self._rows(self._request('GET', resource, params={'organization_id': org}), org)

    def get_intelligence_reports(self, organization_id):
        return self._read('intelligence-reports', organization_id)

    def get_market_signals(self, organization_id):
        return self._read('market-signals', organization_id)

    def get_execution_results(self, organization_id):
        return self._read('execution-results', organization_id)

    def create_decision_run(self, organization_id, trigger):
        result = self._request('POST', 'runs', {'organization_id': self._org(organization_id), 'trigger': trigger})
        try:
            return str(UUID(result))
        except (ValueError, TypeError, AttributeError):
            raise CRMError('Malformed CRM run ID') from None

    def create_recommendations(self, organization_id, run_id, recommendations, snapshot, summary, partial=False):
        org = self._org(organization_id)
        if any(r.get('organization_id') != org for r in recommendations):
            raise ValueError('Cross-organization recommendation rejected')
        result = self._request('POST', 'recommendations', {'organization_id': org, 'run_id': str(UUID(run_id)),
                             'recommendations': recommendations, 'snapshot': snapshot, 'summary': summary, 'partial': partial})
        recommendation_writes(org, recommendations)
        return result

    def create_recommendation(self, organization_id, run_id, recommendation, snapshot, summary):
        """Finalize a single-recommendation run, atomically with its initial evidence."""
        return self.create_recommendations(organization_id, run_id, [recommendation], snapshot, summary)

    def attach_recommendation_evidence(self, organization_id, recommendation_id, evidence):
        return self._request('POST', f'recommendations/{UUID(recommendation_id)}/evidence',
                             {'organization_id': self._org(organization_id), 'evidence': evidence})

    def fail_decision_run(self, organization_id, run_id, error):
        return self._request('POST', f'runs/{UUID(run_id)}/fail', {'organization_id': self._org(organization_id), 'error': error})
