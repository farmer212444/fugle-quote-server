#!/usr/bin/env python3
"""Publish a read-only, evidence-bound Munger inversion due-diligence lane."""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from tw_model_v880.munger import build, render


def _source(path):
    raw=Path(path).read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()


def _atomic(path,content):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as handle:
            handle.write(content)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish(root):
    root=Path(root).resolve()
    ranking=root/'tw-market-data/rankings'
    progress,progress_hash=_source(ranking/'v891_gate_progress.json')
    institutional,institutional_hash=_source(ranking/'latest_institutional.json')
    result=build(progress,institutional)
    version=(root/'VERSION').read_text(encoding='utf-8').strip()
    if result['model']!=version:
        raise ValueError('MUNGER_ACTIVE_MODEL_VERSION_MISMATCH')
    result['input_sha256']={
        'v891_gate_progress.json':progress_hash,
        'latest_institutional.json':institutional_hash,
    }
    result['observed_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    # Entire review must validate before either publication is created.
    md=render(result)
    payload=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    _atomic(ranking/'latest_munger_review.json',payload)
    _atomic(ranking/'latest_munger_review.md',md)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    result=publish(args.root)
    print(json.dumps(dict(
        model=result['model'],schema=result['schema'],
        evaluated_issuers=result['evaluated_issuers'],
        institutional_detail_coverage=result['institutional_detail_coverage'],
        new_certificates_issued=0,trade_orders_created=0),ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
