"""Durable advisory recommendations using the existing CRM recommendation contract."""
from datetime import timedelta
from decision_engine.models.contracts import uid, number, timestamp
from decision_engine.services.evaluation import fresh
from decision_engine.services.registry import SERVICES, ALIASES, default_registry, canonical_service

CONTRACT = 'service-decision-v1'


def workflow_identity(report, context, service, supplied=None):
    upstream = dict(report.get('metadata', {}).get('workflow_context') or {})
    if upstream.get('service_id'):
        upstream['service_id'] = canonical_service(upstream['service_id'])
    for key in ('workflow_run_id', 'parent_run_id', 'correlation_id'):
        value = report.get(key)
        if value is not None:
            if upstream.get(key) is not None and upstream[key] != value:
                raise ValueError('Conflicting upstream workflow identity')
            upstream[key] = value
    for key, value in (supplied or {}).items():
        if key == 'service_id':
            value = canonical_service(value)
        if key in upstream and upstream[key] is not None and upstream[key] != value and key != 'source_engine':
            raise ValueError('Workflow request does not match evidence')
        upstream[key] = value
    if upstream.get('organization_id', context.organization_id) != context.organization_id or upstream.get('service_id', service) != service:
        raise ValueError('Foreign workflow identity')
    # Correlation IDs alone are preserved, never promoted into fabricated workflows.
    if upstream.get('workflow_run_id'):
        upstream.update(organization_id=context.organization_id, service_id=service, source_engine='decision_engine')
    return upstream


def recommend(context, config, service_id=None, decision_type=None, workflow_context=None, registry=None):
    registry = registry or default_registry()
    if workflow_context and not service_id:
        service_id = workflow_context.get('service_id')
    service_id = canonical_service(service_id)
    if decision_type and not service_id:
        raise ValueError('Decision type requires a service')
    if service_id:
        registry.get(service_id, decision_type or SERVICES.get(service_id, (None, None, None))[2])
    enabled = {s.get('service_key') for s in context.profile.get('organization_services', []) if s.get('is_enabled') is True}
    rows, assessments = [], []
    for service in ([service_id] if service_id else SERVICES):
        kind, contract, default = SERVICES[service]
        decision = ALIASES.get(decision_type, decision_type) if decision_type else default
        strategy = registry.get(service, decision)
        if service not in enabled:
            assessments.append({'service_id': service, 'status': 'NOT_CONFIGURED'})
            continue
        latest = {}
        for report in context.reports:
            metadata = report.get('metadata', {})
            if (report.get('organization_id') != context.organization_id or report.get('report_type') != kind or
                report.get('status') != 'CURRENT' or report.get('is_test') is not False or
                metadata.get('research_contract') != contract or
                metadata.get('service_id', 'domain_merchant' if kind == 'DOMAIN_MARKET' else None) != service or
                not fresh(report.get('created_at'), context, config['max_signal_age_days'])):
                continue
            subject = report.get('subject_key', service)
            if subject not in latest or (report['created_at'], report['id']) > (latest[subject]['created_at'], latest[subject]['id']):
                latest[subject] = report
        count = 0
        for report in latest.values():
            identity = workflow_identity(report, context, service, workflow_context)
            results = strategy(context, report, decision, config)
            results.sort(key=lambda result: (-result.score, -result.confidence, result.subject_id))
            for result in results:
                number(result.score, 0, 100)
                number(result.confidence, 0, 1)
                key = service + ':' + decision + ':' + result.subject_id
                active = [r for r in context.active if r.get('metadata', {}).get('decision_key') == key]
                if active:
                    assessments.append({'service_id': service, 'decision_type': decision, 'status': 'ALREADY_RECOMMENDED', 'recommendation_ids': [r['id'] for r in active]})
                    continue
                metadata = {'decision_contract': CONTRACT, 'decision_key': key, 'service_id': service,
                            'decision_type': decision, 'subject_type': report.get('subject_type', kind.lower()),
                            'subject_id': result.subject_id, 'recommendation': result.recommendation,
                            'strategy_version': result.strategy_version, 'policy_version': result.policy_version,
                            'requires_approval': result.requires_approval, 'execution_authorized': False,
                            'execution_status': 'COMPLETED', 'evidence_references': result.evidence_refs,
                            'intelligence_report_id': report['id'], 'details': result.details,
                            'rank': len(rows) + 1, 'action_type': None, 'parameters': {}}
                if identity.get('workflow_run_id'):
                    metadata['workflow_context'] = identity
                for name in ('workflow_run_id', 'parent_run_id', 'correlation_id'):
                    if identity.get(name) is not None:
                        metadata[name] = identity[name]
                expiry = min(context.evaluated_at + timedelta(days=config['recommendation_ttl_days']),
                             timestamp(report['created_at']) + timedelta(days=config['max_signal_age_days']))
                row = {'id': uid(), 'organization_id': context.organization_id, 'recommendation_type': 'MARKET_RESEARCH',
                       'execution_service': None, 'title': decision.replace('_', ' ').title(), 'reason': result.reason,
                       'summary': result.reason, 'score': result.score, 'confidence_score': result.confidence,
                       'priority': result.details.get('priority', 'HIGH' if result.score >= 70 else 'MEDIUM' if result.score >= 50 else 'LOW'),
                       'status': 'RECOMMENDED', 'risk_level': 'LOW', 'currency': context.constraints.currency,
                       'expected_value': None, 'expected_cost': None, 'suggested_budget': 0,
                       'expires_at': expiry.isoformat(), 'metadata': metadata, 'dependencies': [],
                       'evidence': [{'evidence_type': 'INTELLIGENCE_REPORT', 'intelligence_report_id': report['id'],
                                     'description': 'MMonolith ' + contract + '; subject ' + result.subject_id, 'weight': None},
                                    {'evidence_type': 'RULE', 'description': service + '/' + decision + ' strategy ' + result.strategy_version + ', policy ' + result.policy_version, 'weight': None}]}
                row['evidence'].extend({'evidence_type': 'MARKET_SIGNAL', 'signal_id': reference['signal_id'],
                                       'description': 'Scoped upstream outreach measurement', 'weight': None}
                                      for reference in result.evidence_refs if reference.get('signal_id'))
                rows.append(row)
                count += 1
        assessments.append({'service_id': service, 'decision_type': decision, 'execution_status': 'COMPLETED',
                            'status': 'ASSESSED' if latest else 'NO_EVIDENCE', 'recommendations_created': count})
    if len(rows) > 100:
        raise ValueError('Recommendation batch exceeds CRM limit; request one service at a time')
    return rows, assessments
