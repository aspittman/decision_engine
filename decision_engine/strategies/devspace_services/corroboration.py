"""Count independent platforms, rather than connector labels or search results."""
from urllib.parse import urlparse

PLATFORMS = {'upwork.com':'upwork','reddit.com':'reddit','github.com':'github_issues',
    'stackoverflow.com':'stack_overflow','play.google.com':'google_play',
    'trends.google.com':'google_trends','fiverr.com':'fiverr','remotive.com':'remotive'}
SUPPORT = {'buyer_request','job_posting','technical_pain','review_pain','search_interest'}


def source_family(row):
    host=(urlparse(row.get('url','')).hostname or '').lower().removeprefix('www.')
    for domain, family in PLATFORMS.items():
        if host==domain or host.endswith('.'+domain): return family
    # Group aliases/subdomains of other public boards conservatively.
    parts=host.split('.')
    suffix=3 if host.endswith(('.co.uk','.com.au','.co.in')) else 2
    return '.'.join(parts[-suffix:])


def corroboration(rows):
    matrix={}
    seen=set()
    declining=[]
    for row in rows:
        # Search snippets and supply listings never confirm buying demand.
        if row.get('kind') not in SUPPORT: continue
        comparison=row.get('comparison') or {}
        if row.get('kind')=='search_interest' and comparison.get('current',0)<comparison.get('previous',0):
            declining.append(row.get('id'))
            continue
        family=source_family(row)
        if not family: continue
        identity=row.get('url')
        text=' '.join(row.get('text','').lower().split())
        # Long identical syndicated descriptions cannot create extra confirmation.
        fingerprint=('text',text) if len(text)>=120 else ('url',identity)
        if fingerprint in seen: continue
        seen.add(fingerprint)
        matrix.setdefault(family,set()).add(row['kind'])
    families=sorted(matrix)
    buyers=sorted(f for f,kinds in matrix.items() if 'buyer_request' in kinds)
    return {'independent_source_count':len(families),'independent_sources':families,
        'declining_interest_evidence_ids':declining,
        'buyer_source_count':len(buyers),'buyer_sources':buyers,
        'source_kind_matrix':{f:sorted(matrix[f]) for f in families},
        'status':('CROSS_SOURCE_DEMAND' if buyers and len(families)>=2 else
            'SINGLE_SOURCE_DEMAND' if buyers else 'CORROBORATED_PROXIES' if len(families)>=2 else
            'INDIRECT_EVIDENCE_ONLY' if families else 'UNCONFIRMED'),
        'scope':'Independent platforms; hiring, pain and search interest remain proxies. Competitor offers and search snippets excluded.'}


def research_score(rows):
    confirmation=corroboration(rows)
    requests=sum(r.get('kind')=='buyer_request' for r in rows)
    kinds={k for values in confirmation['source_kind_matrix'].values() for k in values}
    return min(100,min(25,requests*5)+min(60,confirmation['independent_source_count']*15)+min(15,len(kinds)*5))
