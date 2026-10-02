from ..base import Strategy


class DomainAcquisitionStrategy(Strategy):
    kind, service, action = "DOMAIN_ACQUISITION", "domain_merchant", "investigate_domain_category"
    risk = "LOW"

    def evaluate(self, context):
        from copy import copy
        reports = context.profile.get('domain_reports', [])
        if reports:
            # Evaluate each market under the same constraints, then choose the best
            # eligible risk-adjusted result. Existing active-strategy budget rules apply.
            candidates = []
            for report in reports:
                scoped = copy(context)
                scoped.profile = {**context.profile, 'subject_key': report['subject_key']}
                scoped.reports = [report]
                ids = set(report.get('signal_ids', []))
                scoped.signals = [s for s in context.signals if s.id in ids]
                if report.get('metadata', {}).get('research_contract') == 'domain-evidence-v1':
                    candidates.append(self._evaluate_facts(scoped, report))
                    continue
                result = self._evaluate_market(scoped)
                result.parameters.update({'is_test': report.get('is_test', False),
                    'intelligence_report_id': report['id'], 'correlation_id': report.get('correlation_id')})
                predictions = [p for p in context.profile.get('predictions', []) if p['intelligence_report_id'] == report['id']]
                certainty = min([report['confidence_score']] + [p['confidence'] for p in predictions])
                result.confidence = min(result.confidence, float(certainty))
                internal = report.get('metadata', {}).get('internal_performance_score')
                certainty = report.get('metadata', {}).get('internal_confidence', 0)
                if internal is not None:
                    result.score = max(0, min(100, result.score + (internal-50)*certainty*.2))
                    result.reason += ' Internal execution performance is considered separately from market opportunity.'
                result = self.finish(scoped, result)
                candidates.append(result)
            return max(candidates, key=lambda r: (r.eligible, r.score, r.confidence))
        return self._evaluate_market(context)

    def _evaluate_market(self, context):
        result = self.build(context, reason="Comparable sales, commercial intent and buyer density justify investigating this domain category.")
        result.parameters.update({"investigation_only": True, "purchase_authorized": False})
        result.concerns.append("Category evidence is not a domain valuation; any purchase requires a separate approval.")
        result.blocking_reasons.append("Current domain candidate facts and GoDaddy quote required")
        return self.finish(context, result)

    def _evaluate_facts(self, context, report):
        """Rank transparent policy checks, not inferred brand/value scores."""
        from datetime import timedelta
        from decision_engine.models.contracts import Evidence, StrategyEvaluation, timestamp
        from .scoring import score_candidate
        from .pricing import evaluate as pricing_assessment
        policy = self.config['domain_research_policy']
        settings = self.config['strategies'][self.kind]
        budget = min(settings['target_budget'], context.constraints.max_domain_acquisition_price)
        findings = []
        for candidate in report['metadata'].get('candidates', []):
            quote = candidate.get('availability', {})
            demand = (candidate.get('keyword_demand') or {}).get('keywords', [])
            volume = max((float(r.get('search_volume') or 0) for r in demand), default=0)
            checked = quote.get('checked_at')
            fresh = bool(checked and context.evaluated_at - timedelta(hours=policy['availability_max_age_hours']) <= timestamp(checked) <= context.evaluated_at)
            price = quote.get('acquisition_price')
            checks = {
                'trademark': (candidate.get('trademark_screening') or {}).get('status') != 'CONFLICT',
                'comparable_sales': candidate.get('comparable_count', 0) >= policy['minimum_comparable_sales'],
                'search_demand': volume >= policy['minimum_monthly_searches'],
                'potential_buyers': (candidate.get('potential_buyer_count') or 0) >= policy['minimum_potential_buyers'],
                'available_with_affordable_quote': fresh and quote.get('status') == 'available' and price is not None
                    and quote.get('provider') == context.constraints.domain_registrar
                    and quote.get('price_type') == 'checkout_total'
                    and quote.get('currency') == context.constraints.currency and 0 < float(price) <= budget,
            }
            outcome = candidate.get('internal_performance') or {}
            sent = int(outcome.get('sent') or 0)
            checks['outreach_feedback'] = not (sent >= policy['minimum_feedback_sample']
                and int(outcome.get('negative_responses') or 0) > int(outcome.get('positive_responses') or 0))
            findings.append((candidate, checks))
        qualifying = [(row, checks) for row, checks in findings if all(checks.values())]
        scores = {row['domain']: score_candidate(row, context, policy) for row, _ in findings}
        best = max(qualifying or findings, key=lambda item: scores[item[0]['domain']]['score'], default=(None, {}))
        ranking = scores[best[0]['domain']] if best[0] else {'score':0,'points':{},'penalties':{},'unknown':[]}
        result = StrategyEvaluation(self.kind, self.service, self.action,
            score=ranking['score'], confidence=float(report['confidence_score']),
            expected_cost=budget, suggested_budget=budget, risk_level=self.risk,
            reason='Review MMonolith domain findings against reported sales, keyword demand, observed potential buyers and a recent acquisition quote. No purchase is authorized.',
            components={**ranking['points'], **{'penalty_'+k:-v for k,v in ranking['penalties'].items()}})
        result.parameters = {'budget_limit':budget,'registrar':context.constraints.domain_registrar,'currency':context.constraints.currency,
            'locations':list(context.constraints.target_locations),'industries':list(context.constraints.target_industries),
            'brand_restrictions':list(context.constraints.brand_restrictions),'subject_key':report['subject_key'],
            'intelligence_report_id':report['id'],'correlation_id':report.get('correlation_id'),
            'is_test':report.get('is_test',False),'investigation_only':True,'purchase_authorized':False,
            'research_candidate_domains':[row['domain'] for row, _ in qualifying],
            'candidate_decisions':[{'domain':row['domain'],
                'decision':'CONSIDER_BUY' if all(checks.values()) else 'PASS',
                'checks':checks,
                'reasons':[name for name, passed in checks.items() if not passed],
                'internal_performance':row.get('internal_performance'), 'scoring':scores[row['domain']], 'pricing':pricing_assessment(row)}
                for row, checks in findings],
            'evidence_policy':policy}
        result.evidence = [Evidence('INTELLIGENCE_REPORT','MMonolith raw facts and candidate provenance',intelligence_report_id=report['id']),
            Evidence('RULE','domain-acquisition-v2 weighted evidence points minus explicit risk penalties; unknown inputs earn no points. Not a resale probability or valuation.'),
            Evidence('CLIENT_CONSTRAINT','Current organization budget, risk and targeting constraints applied')]
        result.concerns.append('Unmeasured scoring dimensions: ' + ', '.join(ranking['unknown']))
        result.concerns.append('Trademark clearance is required before any future purchase; investigation is not clearance.')
        result.concerns.append('Reported sales exclude unsold inventory; neither sell-through probability nor expected profit is established.')
        failures = [f for f in report['metadata'].get('feedback_evaluations', [])
            if f.get('evaluation') == 'NOT_SUPPORTED' and f.get('sample_size', 0) >= policy['minimum_feedback_sample']]
        if failures:
            result.score = max(0, result.score - policy['negative_feedback_penalty'])
            result.components['execution_feedback_penalty'] = policy['negative_feedback_penalty']
            result.concerns.append('Prior execution underperformed its prediction. External market facts remain unchanged; review execution before repeating.')

        if not qualifying:
            result.blocking_reasons.append('No candidate passes every evidence check: ' +
                ', '.join(k for k,v in best[1].items() if not v))
        if any(not checks['outreach_feedback'] for _, checks in findings):
            result.concerns.append('At least one domain has more negative than positive responses after sufficient outreach. Review CRM outcomes before purchase.')
        if budget < settings['minimum_budget']: result.blocking_reasons.append('Insufficient budget for investigation')
        # Restrict the research market to the client target, if configured.
        locations = report['metadata'].get('locations', [])
        if context.constraints.target_locations and not set(map(str.lower,locations)).issubset(set(map(str.lower,context.constraints.target_locations))):
            result.blocking_reasons.append('Research geography does not match client targeting')
        return self.finish(context,result)
