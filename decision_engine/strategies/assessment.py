"""Service-specific advisory scores, persisted in decision-run summaries.

These assessments never imply an execution adapter exists. Only explicitly scoped,
fresh normalized signals enter a score. Missing evidence is UNKNOWN, never a pass.
"""
from datetime import timedelta
from math import isfinite


def assess(context, service, name, weights, required=(), gates=()):
    selected = {}
    for signal in sorted(context.signals, key=lambda s:(s.observed_at,s.id)):
        if (signal.metadata.get('service_id') == service and
                signal.metadata.get('subject_key') == context.subject_key and
                context.evaluated_at-timedelta(days=30) <= signal.observed_at <= context.evaluated_at and
                (signal.expires_at is None or signal.expires_at > context.evaluated_at) and
                signal.source and isfinite(signal.value) and 0 <= signal.value <= 100):
            selected[signal.metric] = signal
    points = {key:round(selected[key].value*weight/100,4) if key in selected else 0 for key,weight in weights.items()}
    missing = [key for key in required if key not in selected]
    blocked = [key for key in gates if key not in selected or selected[key].value < 100]
    confidence = sum(selected[k].confidence*w/100 for k,w in weights.items() if k in selected)
    score = sum(points.values())
    enabled = any(r.get('service_key') == service and r.get('is_enabled') is True
                  for r in context.profile.get('organization_services', []))
    status = ('NOT_CONFIGURED' if not enabled else 'UNKNOWN' if missing else
              'BLOCKED' if blocked else 'REVIEW' if score >= 60 and confidence >= context.constraints.minimum_confidence else 'INSUFFICIENT_EVIDENCE')
    return {'service_id':service,'strategy':name,'status':status,'score':score,'confidence':confidence,
            'points':points,'maximum_points':weights,'missing':missing,'unmet_gates':blocked,
            'evidence_ids':[selected[k].id for k in sorted(set(weights)|set(gates)) if k in selected],
            'execution_authorized':False,
            'reason': 'Service is not enabled for this organization' if not enabled else
                'Missing evidence: '+', '.join(missing) if missing else
                'Required checks unverified or failed: '+', '.join(blocked) if blocked else
                'Advisory assessment only; execution needs its own registered adapter and approval'}
