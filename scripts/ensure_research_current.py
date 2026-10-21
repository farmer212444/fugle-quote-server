#!/usr/bin/env python3
"""Rebuild a stale derived model cache from validated sources before audit export."""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880 import VERSION
from tw_model_v880.data import model_source_state
from tw_model_v880.provenance import code_fingerprint


def stale_reasons(root,meta,*,runtime_hash=None):
    root=Path(root).resolve();reasons=[]
    if meta.get('model')!=VERSION:reasons.append('MODEL_VERSION_CHANGED')
    if meta.get('model_code_sha256')!=(runtime_hash or code_fingerprint()):reasons.append('RUNTIME_CODE_CHANGED')
    if meta.get('model_source_state')!=model_source_state(root):reasons.append('SOURCE_MANIFEST_OR_LEDGER_CHANGED')
    if meta.get('strategy_variant','current-information')!='current-information':reasons.append('SHADOW_VARIANT_IS_NOT_CURRENT_RESEARCH')
    for receipt in meta.get('input_receipts',[]):
        rel=Path(receipt['path']);path=(root/rel).resolve()
        if rel.is_absolute() or '..' in rel.parts or root not in path.parents:raise ValueError('CACHE_INPUT_RECEIPT_UNSAFE_PATH')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=receipt.get('sha256'):
            reasons.append('INPUT_RECEIPT_CHANGED:'+receipt['path'])
    return reasons


def ensure_current(root,asof,target_date=None,runner=None):
    root=Path(root);path=root/'rankings/latest_research.json'
    try:
        meta=json.loads(path.read_text(encoding='utf-8'))
        reasons=stale_reasons(root,meta)
    except (OSError,json.JSONDecodeError):
        meta={};reasons=['RESEARCH_CACHE_MISSING_OR_UNREADABLE']
    if not reasons:return dict(status='CURRENT_HASHED_RESEARCH_REUSED',rebuilt=False)
    if runner is None:
        from scripts.tw_v880_run import run
        runner=run
    target=target_date or meta.get('target_date') or f'{int(asof[:4])+1}-12-31'
    runner(root,asof,target)
    remaining=stale_reasons(root,json.loads(path.read_text(encoding='utf-8')))
    if remaining:raise ValueError('REBUILT_RESEARCH_STILL_STALE:'+str(remaining))
    return dict(status='REBUILT_FROM_VALIDATED_SOURCES',rebuilt=True,reasons=reasons)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-root',default='tw-market-data')
    parser.add_argument('--target-date');args=parser.parse_args()
    now=dt.datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='microseconds')
    print(json.dumps(ensure_current(args.data_root,now,args.target_date),ensure_ascii=False))


if __name__=='__main__':main()
