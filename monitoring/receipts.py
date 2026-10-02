"""Best-effort reference-only observations. Never participates in business success."""
import json
import fcntl
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def record(engine, service, org, table, record_id, event_type, context=None):
    try:
        if not all(isinstance(v, str) and v for v in (engine, service, org, table, record_id)): return False
        context = context or {}
        root = next((p for p in Path(__file__).resolve().parents if (p/'monitoring/profile.json').is_file()), Path.cwd())
        path = Path(os.getenv('DEVSPACE_CAPABILITY_EVENTS', str(root/'logs/capability_events.jsonl')))
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(trace_event_id=str(uuid4()), engine_id=engine, service_id=service,
                   organization_id=org, stage='persistence' if event_type=='write_persisted' else 'data_read',
                   event_type=event_type, status='COMPLETED', timestamp=datetime.now(timezone.utc).isoformat(),
                   workflow_run_id=context.get('workflow_run_id'), correlation_id=context.get('correlation_id'),
                   metadata={'table':table, 'record_id':record_id}, source_reference=table+':'+record_id)
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            if path.exists() and path.stat().st_size > 8_000_000:
                path.replace(path.with_suffix('.jsonl.1'))
            fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
            try: os.write(fd, (json.dumps(row)+'\n').encode())
            finally: os.close(fd)
        return True
    except Exception:
        return False


def context_reads(engine, org, data):
    """A successful scoped context response proves receipt, not execution."""
    try:
        for table in ('intelligence_reports', 'execution_results'):
            for row in data.get(table, []):
                if row.get('organization_id') != org: continue
                context=row.get('metadata', {}).get('workflow_context', {})
                service=row.get('service_id') or context.get('service_id')
                if not service and (row.get('report_type')=='DOMAIN_MARKET' or row.get('execution_service')=='domain_merchant'):
                    service='domain_merchant'
                if row.get('workflow_run_id'): context={**context, 'workflow_run_id':row['workflow_run_id']}
                if service: record(engine, service, org, table, row.get('id'), 'read_succeeded', context)
    except Exception:
        pass


def recommendation_writes(org, rows):
    try:
        for row in rows:
            context=row.get('metadata', {}).get('workflow_context', {})
            service=row.get('service_id') or context.get('service_id') or ('domain_merchant' if str(row.get('recommendation_type','')).startswith('DOMAIN_') else None)
            if service: record('decision_engine',service,org,'recommendations',row.get('id'),'write_persisted',context)
    except Exception:
        pass
