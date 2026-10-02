"""Recommend a bounded, approved draft from exact client research evidence."""
from datetime import timedelta
from decision_engine.models.contracts import Evidence, StrategyEvaluation, timestamp


class ClientOutreachBriefStrategy:
    kind = 'CLIENT_OUTREACH_BRIEF'
    def __init__(self, config):
        self.config = config

    def evaluate(self, context):
        result = StrategyEvaluation(self.kind, 'devspace_clients', 'prepare_client_outreach',
            expected_cost=0, suggested_budget=0,
            reason='Prepare customer and referral outreach briefs using existing client research. Recipient and message review remain required.')
        if not any(s.get('service_key') == 'devspace_clients' and s.get('is_enabled') is True for s in context.profile.get('organization_services', [])):
            result.blocking_reasons.append('Client service is not enabled')
        capabilities = context.profile.get('execution_capability_details', [])
        if not any(c.get('service_key') == 'devspace_clients' and c.get('status') == 'AVAILABLE' and c.get('adapter_ready') is True and
                   'prepare_client_outreach' in c.get('allowed_actions', []) for c in capabilities):
            result.blocking_reasons.append('Client draft adapter is not ready')
        c = context.constraints
        if c.saturated or self.kind in c.blocked_channels or (c.allowed_channels and self.kind not in c.allowed_channels):
            result.blocking_reasons.append('Client policy blocks outreach preparation')
        if c.minimum_confidence > 1:
            result.blocking_reasons.append('Client confidence policy blocks preparation')
        completed = {x.get('results', {}).get('intelligence_report_id') for x in context.profile.get('client_execution_results', [])
            if x.get('status') == 'COMPLETED' and x.get('results', {}).get('execution_contract') == 'client-outreach-brief-v1'}
        latest = {}
        for r in context.reports:
            if (r.get('report_type') != 'CLIENT_RESEARCH' or r.get('is_test') is not False or
                    r.get('metadata', {}).get('service_id') != 'devspace_clients' or r.get('status') != 'CURRENT'):
                continue
            metadata = r.get('metadata', {})
            if 'profile_config' in metadata and not any(s.get('id') == metadata.get('profile_id') and
                    s.get('is_enabled') is True and s.get('config_json', {}).get('client_research') == metadata['profile_config']
                    for s in context.profile.get('organization_services', [])):
                continue
            old = latest.get(r['subject_key'])
            if old is None or (r['created_at'], r['id']) > (old['created_at'], old['id']):
                latest[r['subject_key']] = r
        reports = []
        for r in latest.values():
            if (r['id'] not in completed and context.evaluated_at - timedelta(days=self.config['max_signal_age_days']) <= timestamp(r['created_at']) <= context.evaluated_at and
                    any(o.get('status') == 'REVIEW' for o in r.get('metadata', {}).get('opportunities', []))):
                reports.append(r)
        if not reports:
            result.blocking_reasons.append('No fresh unprepared client opportunities')
            return result
        report = max(reports, key=lambda r: (r['created_at'], r['id']))
        opportunities = [o for o in report['metadata']['opportunities'] if o.get('status') == 'REVIEW'][:100]
        result.score, result.confidence, result.priority = 70, 1, 'MEDIUM'
        result.parameters = {'budget_limit': 0, 'currency': c.currency, 'locations': list(c.target_locations),
            'industries': list(c.target_industries), 'brand_restrictions': list(c.brand_restrictions),
            'subject_key': report['subject_key'], 'intelligence_report_id': report['id'],
            'opportunity_ids': [o['id'] for o in opportunities], 'is_test': False,
            'draft_only': True, 'send_authorized': False, 'external_calls_authorized': False,
            'purchase_authorized': False, 'correlation_id': report.get('correlation_id'),
            'confidence_scope': 'Existing records can be drafted; no prediction of customer conversion'}
        result.evidence = [Evidence('INTELLIGENCE_REPORT', 'Exact client research for outreach preparation', intelligence_report_id=report['id']),
            Evidence('RULE', 'Existing evidence only; no sending or external calls')]
        result.eligible = not result.blocking_reasons
        return result
