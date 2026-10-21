"""Reviewed business-matched peers on the same forward diluted EPS basis."""
import hashlib
import re
import math
from pathlib import Path
from urllib.parse import urlparse

from .evidence import timestamp
from .math import operating_scenario,pct,number


def matched_multiples(ledger,data,code,period,target_date,asof,cyclical):
    if (ledger.get('code')!=code or ledger.get('financial_period')!=period
            or ledger.get('target_date')!=target_date or ledger.get('review_completed') is not True
            or not ledger.get('reviewer_id') or not ledger.get('issuer_business_model')):
        raise ValueError('MATCHED_PEER_REVIEW_IDENTITY_OR_SCOPE_MISSING')
    cutoff=timestamp(asof)
    if not timestamp(ledger['available_at'])<=timestamp(ledger['checked_at'])<=cutoff<=timestamp(ledger['expires_at']):
        raise ValueError('MATCHED_PEER_REVIEW_FUTURE_OR_EXPIRED')
    if not ledger.get('sources'):
        raise ValueError('MATCHED_PEER_ORIGINAL_SOURCES_REQUIRED')
    root=Path(data.root).resolve()
    for item in ledger['sources']:
        rel=Path(item['archive_path']);path=(root/rel).resolve()
        if rel.is_absolute() or '..' in rel.parts or root not in path.parents:
            raise ValueError('MATCHED_PEER_UNSAFE_SOURCE_PATH')
        if (urlparse(item['url']).scheme!='https' or
                timestamp(item['available_at'])>timestamp(ledger['checked_at']) or
                hashlib.sha256(path.read_bytes()).hexdigest()!=item.get('sha256')):
            raise ValueError('MATCHED_PEER_SOURCE_HASH_OR_DATE_MISMATCH')
        if hasattr(data,'receipt'):data.receipt(path,'MATCHED_PEER_ORIGINAL_SOURCE_BYTES_RECHECKED')
    peers=ledger.get('peers',[])
    ids=[(p.get('market'),p.get('code')) for p in peers]
    if len(peers)<3 or len(set(ids))!=len(peers) or any(c==code for _,c in ids):
        raise ValueError('AT_LEAST_THREE_DISTINCT_EXTERNAL_PEERS_REQUIRED')
    values=[];bridges=[]
    expected_basis='MID_CYCLE_NORMALIZED_FORWARD_DILUTED_EPS' if cyclical else 'TARGET_YEAR_FORWARD_DILUTED_EPS'
    for peer in peers:
        if (peer.get('business_model')!=ledger['issuer_business_model'] or
                peer.get('earnings_basis')!=expected_basis or peer.get('currency')!='TWD'):
            raise ValueError('PEER_BUSINESS_EPS_CYCLE_OR_CURRENCY_BASIS_MISMATCH')
        quote=data.prices.get((peer['market'],peer['code']))
        if not quote or quote.get('date')!=data.price_date or not quote.get('close'):
            raise ValueError('PEER_SAME_DATE_OFFICIAL_QUOTE_REQUIRED')
        b=peer['operating_bridge']
        fields=('revenue_k','gross_margin','opex_ratio','nonoperating_k','tax_rate','parent_fraction','shares')
        values=[number(b.get(k)) for k in fields]
        b=dict(zip(fields,values))
        if None in values or b['revenue_k']<=0 or b['shares']<=0 or not 0<=b['gross_margin']<=1 or not 0<=b['opex_ratio']<=1 or not 0<=b['tax_rate']<1 or not 0<b['parent_fraction']<=1.2:
            raise ValueError('PEER_OPERATING_BRIDGE_NUMERIC_OR_ACCOUNTING_BOUNDS_INVALID')
        close=number(quote['close'])
        if close is None or close<=0:raise ValueError('PEER_REFERENCE_PRICE_INVALID')
        forecast=operating_scenario(*values,1)
        eps=forecast['eps']
        if eps<=0:
            raise ValueError('NONPOSITIVE_PEER_FORWARD_EPS_REQUIRES_NON_PE_ROUTE')
        pe=close/eps
        if not math.isfinite(pe) or pe<=0:raise ValueError('NONFINITE_PEER_FORWARD_MULTIPLE')
        # Keep operating inputs separate from the cross-company PE sample.
        bridges.append(dict(code=peer['code'],forward_eps=eps,price=close,forward_pe=pe))
    values=[p['forward_pe'] for p in bridges]
    return dict(base=pct(values,.5),bear=pct(values,.25),bull=pct(values,.75),
                peers=bridges,method='MATCHED_FORWARD_OPERATING_BRIDGES_NOT_ANALYST_TARGETS',
                cycle_basis=expected_basis,formal_quality_pass=False)
