#!/usr/bin/env python3
"""Rebuild a stale derived model cache from validated sources before audit export."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880 import VERSION
from tw_model_v880.data import model_source_state,source_ledgers,nested_records
from tw_model_v880.evidence import timestamp
from tw_model_v880.freshness import assess_price_freshness,load_dated_exchange_closures
from tw_model_v880.provenance import code_fingerprint,runtime_dependencies


def time_reasons(root,meta,asof):
    """Cache reuse must not extend a decision beyond its date or evidence clock."""
    cutoff=timestamp(asof)
    try:
        vintage=timestamp(meta['estimate_vintage'])
        reference=meta['asof_price_date']
        closures=load_dated_exchange_closures(root)
        old=assess_price_freshness(vintage.isoformat(),reference,closures)
        current=assess_price_freshness(cutoff.isoformat(),reference,closures)
    except (KeyError,ValueError,TypeError,AttributeError):
        return ['CACHE_TIME_CONTEXT_MISSING_OR_INVALID']
    if vintage>cutoff:return ['CACHE_ESTIMATE_FROM_FUTURE']
    reasons=[]
    if vintage.astimezone(ZoneInfo('Asia/Taipei')).date()!=cutoff.astimezone(ZoneInfo('Asia/Taipei')).date():
        reasons.append('EVALUATION_DATE_CHANGED')
    if old['potentially_missing_weekdays']!=current['potentially_missing_weekdays']:
        reasons.append('PRICE_FRESHNESS_CONTEXT_CHANGED')
    for path in source_ledgers(root):
        try:
            for item in nested_records(json.loads(path.read_text(encoding='utf-8'))):
                for field in ('available_at','checked_at','expires_at','effective_at','fetched_at',
                              'estimate_created_at','captured_at_utc','first_recorded_at'):
                    if not item.get(field):continue
                    boundary=timestamp(item[field])
                    crossed=(vintage<=boundary<cutoff if field=='expires_at' else vintage<boundary<=cutoff)
                    if crossed:reasons.append('EVIDENCE_TIME_BOUNDARY_CROSSED:'+path.relative_to(root).as_posix())
        except (ValueError,TypeError,AttributeError,OSError):
            # A rejected issuer ledger remains pending in the model. Its content
            # hash tracks repairs; do not turn its bad clock into a global loop.
            continue
    return list(dict.fromkeys(reasons))


def full_result_reasons(root,meta):
    ref=meta.get('full_results')
    if not isinstance(ref,dict) or ref.get('path')!='v880_full_results.json.gz':
        return ['CACHE_FULL_RESULTS_REFERENCE_INVALID']
    try:
        packed=(root/'rankings'/ref['path']).read_bytes()
        if hashlib.sha256(packed).hexdigest()!=ref.get('sha256'):
            return ['CACHE_FULL_RESULTS_HASH_MISMATCH']
        raw=gzip.decompress(packed)
        if hashlib.sha256(raw).hexdigest()!=ref.get('json_sha256'):
            return ['CACHE_FULL_RESULTS_JSON_HASH_MISMATCH']
        full=json.loads(raw)
        keys=('model','model_code_sha256','runtime_dependencies','strategy_variant','strategy_variant_sha256',
              'estimate_vintage','asof_price_date','target_date','model_source_state','input_receipts',
              'financial_last_quarter','revenue_month','policy','data_scope','formal_Aplus_count','formal_Aplusplus_count')
        if not isinstance(full,dict) or any(full.get(k)!=meta.get(k) for k in keys):
            return ['CACHE_FULL_RESULTS_CONTEXT_MISMATCH']
        rows=full.get('all_model_rows')
        if not isinstance(rows,list) or len(rows)!=meta.get('data_scope',{}).get('model_rows'):
            return ['CACHE_FULL_RESULTS_UNIVERSE_MISMATCH']
    except (OSError,ValueError,EOFError,TypeError,AttributeError):
        return ['CACHE_FULL_RESULTS_MISSING_OR_UNREADABLE']
    return []


def stale_reasons(root,meta,*,runtime_hash=None,asof=None,target_date=None):
    root=Path(root).resolve();reasons=[]
    if not isinstance(meta,dict):return ['RESEARCH_CACHE_INVALID_DOCUMENT']
    if meta.get('model')!=VERSION:reasons.append('MODEL_VERSION_CHANGED')
    if meta.get('model_code_sha256')!=(runtime_hash or code_fingerprint()):reasons.append('RUNTIME_CODE_CHANGED')
    if meta.get('runtime_dependencies')!=runtime_dependencies():reasons.append('RUNTIME_DEPENDENCIES_CHANGED')
    if meta.get('model_source_state')!=model_source_state(root):reasons.append('SOURCE_MANIFEST_OR_LEDGER_CHANGED')
    if meta.get('strategy_variant','current-information')!='current-information':reasons.append('SHADOW_VARIANT_IS_NOT_CURRENT_RESEARCH')
    if target_date is not None and meta.get('target_date')!=target_date:reasons.append('FORECAST_TARGET_DATE_CHANGED')
    if asof is not None:reasons.extend(time_reasons(root,meta,asof))
    receipts=meta.get('input_receipts')
    if not isinstance(receipts,list):return reasons+['CACHE_INPUT_RECEIPTS_INVALID']
    for receipt in receipts:
        if not isinstance(receipt,dict) or not isinstance(receipt.get('path'),str):
            reasons.append('CACHE_INPUT_RECEIPTS_INVALID');continue
        rel=Path(receipt['path']);path=(root/rel).resolve()
        if rel.is_absolute() or '..' in rel.parts or root not in path.parents:raise ValueError('CACHE_INPUT_RECEIPT_UNSAFE_PATH')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=receipt.get('sha256'):
            reasons.append('INPUT_RECEIPT_CHANGED:'+receipt['path'])
    reasons.extend(full_result_reasons(root,meta))
    return reasons


def ensure_current(root,asof,target_date=None,runner=None):
    root=Path(root);path=root/'rankings/latest_research.json'
    try:
        meta=json.loads(path.read_text(encoding='utf-8'))
        reasons=stale_reasons(root,meta,asof=asof,target_date=target_date)
    except (OSError,json.JSONDecodeError):
        meta={};reasons=['RESEARCH_CACHE_MISSING_OR_UNREADABLE']
    if not reasons:return dict(status='CURRENT_HASHED_RESEARCH_REUSED',rebuilt=False)
    if runner is None:
        from scripts.tw_v880_run import run
        runner=run
    target=target_date or (meta.get('target_date') if isinstance(meta,dict) else None) or f'{int(asof[:4])+1}-12-31'
    runner(root,asof,target)
    remaining=stale_reasons(root,json.loads(path.read_text(encoding='utf-8')),asof=asof,target_date=target)
    if remaining:raise ValueError('REBUILT_RESEARCH_STILL_STALE:'+str(remaining))
    return dict(status='REBUILT_FROM_VALIDATED_SOURCES',rebuilt=True,reasons=reasons)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-root',default='tw-market-data')
    parser.add_argument('--target-date');args=parser.parse_args()
    now=dt.datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='microseconds')
    print(json.dumps(ensure_current(args.data_root,now,args.target_date),ensure_ascii=False))


if __name__=='__main__':main()
