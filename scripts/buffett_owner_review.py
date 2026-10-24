#!/usr/bin/env python3
"""Publish a provenance-checked Buffett research sidecar after institutional review."""
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
from tw_model_v880.buffett import build,render


def read_with_hash(path):
    raw=Path(path).read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()


def _utc(value):
    if not isinstance(value,str) or not value:
        raise ValueError("BUFFETT_SOURCE_DATE_REQUIRED")
    moment=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
    if moment.tzinfo is None:
        raise ValueError("BUFFETT_OFFSET_AWARE_TIMESTAMP_REQUIRED")
    return moment.astimezone(dt.timezone.utc)


def _original_9802_bytes(root,cash,estimate_vintage):
    original=cash.get("original_cash_review") or {}
    cutoff=_utc(estimate_vintage)
    if _utc(original.get("reviewed_at"))>cutoff:
        raise ValueError("BUFFETT_SOURCE_REVIEW_FROM_FUTURE")
    sources=original.get("original_sources")
    if not isinstance(sources,list) or {s.get("period") for s in sources} != {"2025-Q2","2026-Q2"} or len(sources)!=2:
        raise ValueError("BUFFETT_9802_TWO_HALFYEAR_ORIGINALS_REQUIRED")
    hashes=[]
    for s in sources:
        if _utc(s.get("captured_at_utc"))>cutoff:
            raise ValueError("BUFFETT_FUTURE_ORIGINAL_CAPTURE")
        path=s.get("archive_path")
        sha=s.get("sha256")
        if not isinstance(path,str) or not path.startswith("evidence/v880/originals/9802/") or not path.endswith(".pdf"):
            raise ValueError("BUFFETT_ARCHIVE_PATH_NOT_ALLOWED")
        if not isinstance(sha,str) or len(sha)!=64:
            raise ValueError("BUFFETT_ARCHIVE_SHA_REQUIRED")
        raw=(root/path).read_bytes()
        if not raw.startswith(b"%PDF") or hashlib.sha256(raw).hexdigest()!=sha:
            raise ValueError("BUFFETT_ARCHIVED_PDF_HASH_MISMATCH")
        hashes.append(dict(period=s["period"],relative_path=path,sha256=sha))
    return hashes


def _atomic(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=path.name+".",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as output:
            output.write(text)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def publish(root):
    root=Path(root).resolve()
    data=root/"tw-market-data"
    source=data/"rankings/latest_institutional.json"
    cashfile=data/"rankings/latest_9802_cash_review.json"
    institutional,institutional_sha=read_with_hash(source)
    cash,cash_sha=read_with_hash(cashfile)
    if (root/"VERSION").read_text(encoding="utf-8").strip()!=institutional.get("model"):
        raise ValueError("BUFFETT_SOURCE_VERSION_NOT_ACTIVE_RUNTIME")
    # Only the same-current-issuer, same-vintage original is eligible.
    if cash.get("estimate_vintage")!=institutional.get("estimate_vintage"):
        raise ValueError("BUFFETT_INCONSISTENT_CASH_REVIEW_VINTAGE")
    archives=_original_9802_bytes(data,cash,institutional["estimate_vintage"])
    report=build(institutional,cash)
    report["input_sha256"]={"latest_institutional.json":institutional_sha,
                            "latest_9802_cash_review.json":cash_sha}
    report["checked_original_pdfs"]=archives
    report["observed_at_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
    md=render(report)
    content=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    _atomic(data/"rankings/latest_buffett_review.json",content)
    _atomic(data/"rankings/latest_buffett_review.md",md)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=ROOT)
    args=parser.parse_args()
    output=publish(args.root)
    print(json.dumps(dict(model=output["model"],
                          issuer_count=output["institutional_issuer_count"],
                          original_9802_cash_cases=output["issuer_cash_original_case_count"],
                          verified_owner_earnings=0,new_certifications=0,orders=0),
                     ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
