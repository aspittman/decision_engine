"""Independent engine diagnostic command: GET / SELECT only; no business imports.

Environment is supplied by the engine's normal launcher. Reports describe that
configuration, not every possible invocation of the engine on another machine.
"""
import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args): return None


class ProbeFailure(Exception):
    def __init__(self, status, reason): self.status, self.reason=status, reason


def get(url, secret):
    p=urlparse(url)
    if p.scheme!='https' and not (p.scheme=='http' and p.hostname in ('localhost','127.0.0.1','::1')):
        raise ProbeFailure('UNKNOWN','Configured CRM URL must use HTTPS or loopback HTTP')
    if p.username or p.password or p.fragment:
        raise ProbeFailure('UNKNOWN','Invalid CRM URL')
    try:
        request=Request(url, headers={'Authorization':'Bearer '+secret, 'Accept':'application/json'}, method='GET')
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            raw=response.read(4_000_001)
        if len(raw)>4_000_000: raise ProbeFailure('UNKNOWN','Read response exceeds 4 MB safety limit')
        body=json.loads(raw)
        if not isinstance(body,dict) or body.get('success') is not True: raise ProbeFailure('DEGRADED','CRM returned an invalid read envelope')
        return body['data']
    except HTTPError as exc:
        code=exc.code; exc.close()
        raise ProbeFailure('UNKNOWN' if code==404 else 'DEGRADED', 'CRM HTTP '+str(code)) from None
    except (URLError, TimeoutError, OSError):
        raise ProbeFailure('DISCONNECTED','CRM unreachable or timed out') from None
    except (ValueError, KeyError, TypeError):
        raise ProbeFailure('UNKNOWN','Invalid CRM read response') from None


def state_reads(org, env):
    """Do not construct State: its normal constructor can create/migrate tables."""
    dsn=env.get('SUPABASE_DB_URL')
    if dsn:
        import psycopg
        db=psycopg.connect(dsn, connect_timeout=5, options='-c default_transaction_read_only=on -c statement_timeout=3000')
        mark='%s'
    else:
        path=Path(env.get('ORCHESTRATOR_SQLITE_PATH','data/orchestrator.sqlite3'))
        if not path.is_absolute(): path=ROOT/path
        if not path.is_file(): raise ProbeFailure('UNKNOWN','Workflow persistence is missing; no database created')
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
        db.execute('PRAGMA query_only=ON')
        mark='?'
    try:
        db.execute('SELECT id FROM workflow_runs WHERE organization_id='+mark+' LIMIT 1',(org,)).fetchone()
        db.execute('SELECT s.id FROM stage_runs s JOIN workflow_runs w ON s.workflow_run_id=w.id WHERE w.organization_id='+mark+' LIMIT 1',(org,)).fetchone()
        return {t:{'status':'VERIFIED','reason':'Read-only tenant-scoped SELECT LIMIT 1 succeeded; empty is valid'} for t in ('workflow_runs','stage_runs')}
    finally: db.close()


def probe(profile, organizations, env=None):
    env=dict(os.environ) if env is None else env
    reports={}
    url=env.get(profile['url_env'],'').rstrip('/')
    secret=env.get(profile['secret_env'],'')
    for service, spec in profile['services'].items():
        inputs=spec['inputs']
        checked=datetime.now(timezone.utc).isoformat()
        report={'checked_at':checked,'organization_ids':organizations, 'connectivity_status':'UNKNOWN',
                'write_status':'UNVERIFIED','configuration_scope':env.get('DEVSPACE_DIAGNOSTIC_SCOPE','engine environment'),
                'reads':{t:{'status':'UNKNOWN','reason':'Not checked'} for t in inputs},
                'reason':'No write test is performed; real persistence receipts are separate.', 'last_read':None}
        reports[service]=report
        if not organizations:
            report['reason']='Explicit organization scope is required'; continue
        if not url or not secret:
            report['reason']='Engine CRM URL or credential is not configured'; continue
        org_results=[]
        for org in organizations:
            reads={}
            try:
                # New endpoint is bounded and carries no business record payload.
                route='/api/bot/monitoring-capabilities?'+urlencode({'organization_id':org,'engine_id':profile['engine_id'],'service_id':service})
                try:
                    result=get(url+route,secret)
                    if result.get('organization_id')!=org or result.get('engine_id')!=profile['engine_id'] or result.get('service_id')!=service:
                        raise ProbeFailure('UNKNOWN','Capability response scope mismatch')
                    reads=result.get('reads',{})
                    connection=result.get('connectivity_status','UNKNOWN')
                except ProbeFailure as exc:
                    if exc.reason!='CRM HTTP 404': raise
                    # Existing deployed read contract; never POST/claim work.
                    # Non-domain legacy inputs are not exposed by this contract.
                    if service!='domain_merchant': raise ProbeFailure('UNKNOWN','Bounded capability endpoint not deployed; legacy service reads unverified')
                    route=profile['fallback_route']+'?'+urlencode({'organization_id':org})
                    context=get(url+route,secret)
                    if not isinstance(context,dict): raise ProbeFailure('UNKNOWN','Invalid context')
                    for table in inputs:
                        rows=context.get(table)
                        valid=isinstance(rows,list) and all(isinstance(r,dict) and r.get('organization_id')==org for r in rows)
                        reads[table]={'status':'VERIFIED' if valid else 'UNKNOWN','reason':'Existing authenticated scoped context query succeeded (empty is valid)' if valid else 'Required table missing or tenant validation failed'}
                    connection='CONNECTED'
                if profile['engine_id']=='dsorchestrator': reads.update(state_reads(org,env))
                org_results.append((connection,reads))
            except ProbeFailure as exc:
                org_results.append((exc.status,{t:{'status':'FAILED' if exc.status=='DEGRADED' else 'UNKNOWN','reason':exc.reason} for t in inputs}))
            except Exception:
                org_results.append(('DEGRADED',{t:{'status':'UNKNOWN','reason':'Read-only persistence/configuration check failed; details withheld'} for t in inputs}))
        states=[c for c,_ in org_results]
        report['connectivity_status']=next(s for s in ('DISCONNECTED','DEGRADED','UNKNOWN','CONNECTED') if s in states)
        for table in inputs:
            rows=[reads.get(table,{'status':'UNKNOWN','reason':'Required table missing'}) for _,reads in org_results]
            selected=next((r for r in rows if r.get('status')=='FAILED'),None) or next((r for r in rows if r.get('status')!='VERIFIED'),None) or rows[0]
            report['reads'][table]=selected
        report['read_checked_at']=checked  # Diagnostic verification, not business activity.
        report['reason']='Engine-owned read-only checks using '+report['configuration_scope']+'; write permissions not assumed.'
    return {'engine_id':profile['engine_id'],'status':'OBSERVED','service_capabilities':reports}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--organization',action='append',default=[])
    parser.add_argument('--output',default=str(ROOT/'logs/capability_health.json'))
    args=parser.parse_args()
    organizations=[str(UUID(org)) for org in args.organization]
    if len(organizations)>20: parser.error('At most 20 organizations')
    profile=json.loads(Path(__file__).with_name('profile.json').read_text())
    result=probe(profile,organizations)
    path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f: json.dump(result,f)
    temporary.replace(path)
    print(json.dumps({'engine_id':profile['engine_id'],'output':str(path),'services':{s:r['connectivity_status'] for s,r in result['service_capabilities'].items()}}))


if __name__=='__main__': main()
