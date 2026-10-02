"""An approved zero-spend review can identify gaps without qualifying a purchase."""
from datetime import timedelta
from decision_engine.models.contracts import Evidence, StrategyEvaluation, timestamp


class DomainResearchReviewStrategy:
    kind = 'MARKET_RESEARCH'
    def __init__(self, config): self.config = config

    def evaluate(self, context):
        result = StrategyEvaluation(self.kind, 'domain_merchant', 'review_domain_evidence',
            expected_cost=0, suggested_budget=0, reason='Review existing domain research, return observed evidence gaps, and feed the result back to MMonolith. No external calls, purchase or outreach.')
        capabilities = context.profile.get('execution_capability_details', [])
        if not any(c.get('service_key')=='domain_merchant' and c.get('adapter_ready') is True and
                   c.get('status')=='AVAILABLE' and 'review_domain_evidence' in c.get('allowed_actions',[]) for c in capabilities):
            result.blocking_reasons.append('Production evidence-review adapter is not registered ready')
        if context.capabilities.get('domain_merchant') != 'AVAILABLE':
            result.blocking_reasons.append('Domain Merchant is not enabled/available')
        c = context.constraints
        if c.saturated or self.kind in c.blocked_channels or (c.allowed_channels and self.kind not in c.allowed_channels):
            result.blocking_reasons.append('Client policy blocks research review')
        reports = []
        for report in context.profile.get('domain_reports', []):
            try: fresh = context.evaluated_at-timedelta(days=self.config['max_signal_age_days']) <= timestamp(report['created_at']) <= context.evaluated_at
            except (KeyError,TypeError,ValueError): fresh = False
            if fresh and report.get('is_test') is False and report.get('metadata',{}).get('candidates') and report.get('status')=='CURRENT': reports.append(report)
        # A completed review of the exact report must not be recommended again.
        reviewed = set(context.profile.get('reviewed_domain_report_ids', []))
        reports = [r for r in reports if r['id'] not in reviewed]
        if not reports:
            result.blocking_reasons.append('No fresh unreviewed report with candidates')
            return result
        report = max(reports,key=lambda r:(r['created_at'],r['id']))
        # Certainty is about the existence of reviewable records, not market upside.
        result.confidence = 1.0
        result.score = 60
        result.priority = 'MEDIUM'
        result.parameters = {'budget_limit':0,'currency':c.currency,'locations':list(c.target_locations),
            'industries':list(c.target_industries),'brand_restrictions':list(c.brand_restrictions),
            'subject_key':report['subject_key'],'intelligence_report_id':report['id'],
            'is_test':report.get('is_test',False),'investigation_only':True,'purchase_authorized':False,
            'external_calls_authorized':False,'correlation_id':report.get('correlation_id'),
            'confidence_scope':'Reviewable source records exist; not acquisition confidence'}
        result.evidence = [Evidence('INTELLIGENCE_REPORT','Exact report to review',intelligence_report_id=report['id']),
                           Evidence('RULE','Zero-spend review; missing market evidence remains unknown')]
        result.eligible = not result.blocking_reasons
        return result
