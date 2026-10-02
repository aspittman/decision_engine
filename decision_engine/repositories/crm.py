"""Translate CRM context into the existing strategy model without CRM source imports."""
from decision_engine.repositories.store import Repository
from decision_engine.models.contracts import timestamp


class ContextRows:
    def __init__(self, data):
        self.data = data

    def rows(self, table, filters=None):
        rows = self.data[table]
        for key, expression in (filters or {}).items():
            op, value = expression.split('.', 1)
            if op == 'eq':
                rows = [r for r in rows if r.get(key) == value]
            elif op == 'gte':
                rows = [r for r in rows if r.get(key) and timestamp(r[key]) >= timestamp(value)]
            elif op == 'in':
                rows = [r for r in rows if r.get(key) in value.strip('()').split(',')]
            else:
                raise ValueError('Unsupported context filter')
        return rows


class CRMRepository:
    def __init__(self, client, config):
        self.client, self.config = client, config

    def organizations(self):
        return self.client.get_organizations()

    def context(self, organization_id):
        data = self.client.get_organization_context(organization_id)
        context = Repository(ContextRows(data), self.config).context(organization_id)
        context.profile['execution_capability_details'] = data['execution_capabilities']
        context.profile['reviewed_domain_report_ids'] = [r.get('results',{}).get('intelligence_report_id') for r in data.get('execution_results',[]) if r.get('status')=='COMPLETED' and r.get('results',{}).get('review_contract')=='domain-evidence-review-v1']
        context.profile['organization_services'] = data['organization_services']
        context.profile['client_execution_results'] = data.get('execution_results', [])
        # Config lives on existing service rows, not a new configuration table.
        context.profile['organization_configuration'] = {r['id']: r.get('config_json', {}) for r in data['organization_services']}
        enabled = {r['service_key'] for r in data['organization_services'] if r['is_enabled']}
        context.capabilities = {key: status if key in enabled else 'UNAVAILABLE' for key, status in context.capabilities.items()}
        # Preserve historical versions; select latest domain report per subject and mode.
        from os import getenv
        test = getenv('DEVSPACE_ENV') == 'test'
        history = [r for r in data['intelligence_reports'] if r.get('is_test', False) == test]
        context.profile['intelligence_history'] = history
        context.profile['feedback_evaluations'] = [f for f in data.get('feedback_evaluations', [])
            if any(r['id'] == f['intelligence_report_id'] for r in history)]
        context.profile['predictions'] = [p for p in data.get('predictions', [])
            if any(r['id'] == p['intelligence_report_id'] for r in history)]
        latest = {}
        for report in sorted(history, key=lambda r: (r['created_at'], r['id'])):
            if report.get('report_type') == 'DOMAIN_MARKET':
                latest[report['subject_key']] = report
        for report in latest.values():
            report['signal_ids'] = [link['signal_id'] for link in data['intelligence_report_signals'] if link['report_id'] == report['id']]
        context.profile['domain_reports'] = list(latest.values())
        context.signals = [s for s in context.signals if s.metadata.get('is_test', False) == test]
        context.history = [x for x in context.history if any(r['id'] == x.id and
            r.get('results', {}).get('is_test', False) == test for r in data['execution_results'])]
        return context

    def start_run(self, organization_id, trigger):
        return self.client.create_decision_run(organization_id, trigger)

    def finish_run(self, run_id, organization_id, recommendations, snapshot, summary, partial):
        return self.client.create_recommendations(organization_id, run_id, recommendations, snapshot, summary, partial)

    def fail_run(self, run_id, organization_id, error):
        return self.client.fail_decision_run(organization_id, run_id, error)
