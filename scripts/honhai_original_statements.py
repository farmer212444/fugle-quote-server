#!/usr/bin/env python3
"""Archive only exact verified Foxconn issuer PDF originals; never issue a PASS.

Initial allowlist contains independently located full consolidated statements.
Missing quarters and inaccessible bytes remain PENDING, never zero evidence or PASS.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_research_pipeline import atomic_json

SCHEMA="HONHAI_2317_FULL_ISSUER_PDF_ARCHIVE_V1"
FOLDER="evidence/v880/originals/2317/full_statements"
MANIFEST=FOLDER+"/manifest.json"
MAX_PDF_BYTES=30_000_000
HTTP403_RETRY=dt.timedelta(hours=24)
KNOWN={
 "2025-Q1":"https://image.honhai.com/financy_by_quarterly/2025Q1_consolidared_report%28c%29_1747304642.pdf",
 "2025-Q3":"https://image.honhai.com/upload/202511/financy_by_quarterly/2025Q3_consolidared_report%28c%29_20251114_4728.pdf",
 "2025-Q2":"https://image.honhai.com/upload/202508/financy_by_quarterly/2025Q2_consolidared_report%28c%29_20250814_9796.pdf",
 "2025-Q4":"https://image.honhai.com/upload/202603/financy_by_quarterly/2025Q4_consolidared_report%28c%29_20260316_8056.pdf",
 "2026-Q1":"https://image.honhai.com/upload/202605/financy_by_quarterly/2026Q1_consolidared_report%28c%29_20260515_2694.pdf",
}
CHINESE_QUARTERS=("一","二","三")
SECTIONS=("會計師","合併資產負債表","合併綜合損益表",
          "合併權益變動表","合併現金流量表","合併財務報表附註")

def sha(raw):return hashlib.sha256(raw).hexdigest()

def aware(value):
    v=dt.datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if v.tzinfo is None:raise ValueError("HONHAI_NAIVE_CAPTURE_TIMESTAMP")
    return v

def window(last):
    m=re.fullmatch(r"(20\d{2})-Q([1-4])",str(last))
    if not m:raise ValueError("HONHAI_INVALID_QUARTER")
    last_index=int(m[1])*4+int(m[2])-1
    return [f"{i//4}-Q{i%4+1}" for i in range(last_index-7,last_index+1)]

def safe(root,relative):
    p=Path(relative)
    target=(Path(root).resolve()/p).resolve()
    if p.is_absolute() or ".." in p.parts or Path(root).resolve() not in target.parents:
        raise ValueError("HONHAI_ARCHIVE_UNSAFE_PATH")
    return target

def fetch(url):
    if url not in KNOWN.values():raise ValueError("HONHAI_URL_NOT_VERIFIED_ALLOWLIST")
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (issuer financial original preservation)",
        "Accept":"application/pdf"})
    with urllib.request.urlopen(req,timeout=20) as response:
        if response.status!=200 or response.geturl()!=url:
            raise ValueError("HONHAI_UNEXPECTED_HTTP_STATUS_OR_REDIRECT")
        raw=response.read(MAX_PDF_BYTES+1)
    return raw

def pdf_identity(raw,period):
    import fitz
    if (not isinstance(raw,bytes) or not 5000<=len(raw)<=MAX_PDF_BYTES
            or not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-4096:]):
        raise ValueError("HONHAI_INVALID_COMPLETE_PDF")
    year=int(period[:4]);quarter=int(period[-1]);roc=year-1911
    expected=(f"民國{roc}年度及{roc-1}年度" if quarter==4
              else f"民國{roc}年及{roc-1}年第{CHINESE_QUARTERS[quarter-1]}季")
    with fitz.open(stream=raw,filetype="pdf") as doc:
        if not 20<=len(doc)<=300:raise ValueError("HONHAI_FULL_STATEMENT_PAGE_COUNT_INVALID")
        cover=re.sub(r"\s+","",doc[0].get_text())
        toc=re.sub(r"\s+","",doc[1].get_text())
        if (not cover or "鴻海精密工業股份有限公司" not in cover
                or "股票代碼2317" not in cover
                or "合併財務報告暨會計師" not in cover
                or expected not in cover):
            raise ValueError("HONHAI_PDF_ISSUER_PERIOD_NOT_CONFIRMED")
        if not all(s in toc for s in SECTIONS):
            raise ValueError("HONHAI_PDF_FULL_FOUR_STATEMENTS_NOTES_MISSING")
        return dict(page_count=len(doc),
                    native_cover_issuer_and_period_verified=True,
                    contents_four_statements_notes_and_auditor_listed=True,
                    full_contents_accounting_reviewed=False,
                    auditor_scope_formally_reviewed=False,
                    filing_release_PIT_verified=False,
                    formal_gate_pass=False)

def validate_archive(root,last,asof):
    root=Path(root).resolve();required=window(last);cut=aware(asof)
    manifest=safe(root,MANIFEST)
    if not manifest.exists():
        return dict(issuer="2317",records=0,document_kinds=dict(quarterly=0),
                    coverage=None,original_archive_hashes_verified=False,
                    formal_pass_count=0,documents=[])
    m=json.loads(manifest.read_text(encoding="utf-8"))
    if (m.get("schema")!=SCHEMA or m.get("issuer")!="2317"
            or m.get("formal_gate_pass") is not False
            or m.get("full_content_review_complete") is not False
            or m.get("MOPS_filing_PIT_verified") is not False):
        raise ValueError("HONHAI_ARCHIVE_SCHEMA_OR_FORMAL_PASS_TAMPERED")
    docs=[];seen=set()
    for entry in m.get("documents",[]):
        when=aware(entry["captured_at_utc"])
        if when>cut:continue
        period=entry["period"];digest=entry["sha256"]
        if (period not in KNOWN or entry.get("source_url")!=KNOWN[period]
                or not re.fullmatch("[0-9a-f]{64}",digest)
                or entry.get("formal_gate_pass") is not False
                or period in seen):
            raise ValueError("HONHAI_ARCHIVED_ORIGINAL_SOURCE_ID_INVALID")
        seen.add(period)
        rel=f"{FOLDER}/{period}_{digest[:20]}.pdf"
        if entry.get("archive_path")!=rel:raise ValueError("HONHAI_ARCHIVED_ORIGINAL_PATH_INVALID")
        raw=safe(root,rel).read_bytes()
        if sha(raw)!=digest or len(raw)!=entry["bytes"]:
            raise ValueError("HONHAI_PDF_REHASH_OR_SIZE_FAILED")
        if pdf_identity(raw,period)!=entry["pdf_identity"]:
            raise ValueError("HONHAI_ORIGINAL_IDENTITY_CHANGED")
        docs.append(entry)
    found=sorted(set(required)&seen)
    cover=dict(required_quarters=required,found_quarters=found,
               missing_quarters=[p for p in required if p not in found],
               full_original_pdf_content_reviewed=False,
               original_MOPS_PIT_verified=False,formal_gate_pass=False,
               source_window_end=last)
    return dict(issuer="2317",records=len(docs),document_kinds=dict(quarterly=len(docs)),
                coverage=cover,original_archive_hashes_verified=bool(docs),
                formal_pass_count=0,documents=docs)

def collect(root,last,*,fetcher=fetch,clock=lambda:dt.datetime.now(dt.timezone.utc)):
    root=Path(root).resolve()
    now=aware(clock().isoformat())
    required=window(last)
    existing=validate_archive(root,last,now.isoformat())
    path=safe(root,MANIFEST)
    manifest=(json.loads(path.read_text(encoding="utf-8")) if path.exists()
              else dict(schema=SCHEMA,issuer="2317",formal_gate_pass=False,
                        full_content_review_complete=False,MOPS_filing_PIT_verified=False,
                        documents=[],last_fetch_errors=[]))
    due=[]
    for period,url in KNOWN.items():
        if period not in required or any(x["period"]==period for x in existing["documents"]):
            continue
        last_error=next((x for x in manifest.get("last_fetch_errors",[])
                         if x.get("period")==period and "403" in x.get("error","")),None)
        if last_error and manifest.get("last_network_attempt_at_utc"):
            tried=aware(manifest["last_network_attempt_at_utc"])
            if tried>now:raise ValueError("HONHAI_NETWORK_ATTEMPT_IN_FUTURE")
            if now<tried+HTTP403_RETRY:continue
        due.append((period,url))
    errors=[];attempted=False
    for period,url in due:
        attempted=True
        try:
            raw=fetcher(url)
            identity=pdf_identity(raw,period)
            digest=sha(raw);rel=f"{FOLDER}/{period}_{digest[:20]}.pdf"
            target=safe(root,rel);target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                if target.read_bytes()!=raw:raise ValueError("HONHAI_IMMUTABLE_SOURCE_CONFLICT")
            else:
                with target.open("xb") as f:f.write(raw)
            manifest["documents"].append(dict(period=period,source_url=url,
                sha256=digest,bytes=len(raw),archive_path=rel,
                captured_at_utc=clock().isoformat(),pdf_identity=identity,
                formal_gate_pass=False))
        except (OSError,ValueError,RuntimeError,EOFError) as e:
            errors.append(dict(period=period,error=type(e).__name__+":"+str(e)))
    # Keep genuine HTTP403 failures during deferred retry; other errors are
    # per-current-attempt only. No successful period can remain failed.
    failures={e["period"]:e for e in manifest.get("last_fetch_errors",[])
              if "403" in e.get("error","")
              and e.get("period") in KNOWN
              and e.get("period") not in {d["period"] for d in manifest["documents"]}}
    for entry in errors:failures[entry["period"]]=entry
    for period,_ in due:
        if period not in {e["period"] for e in errors}:failures.pop(period,None)
    manifest["last_fetch_errors"]=list(failures.values())
    manifest["last_intake_at_utc"]=clock().isoformat()
    if attempted:manifest["last_network_attempt_at_utc"]=clock().isoformat()
    path.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(path,manifest)
    report=validate_archive(root,last,clock().isoformat())
    report["source_errors"]=manifest["last_fetch_errors"]
    return report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-root",default="tw-market-data")
    parser.add_argument("--last-quarter")
    opts=parser.parse_args()
    root=Path(opts.data_root)
    last=opts.last_quarter or json.loads((root/"fundamentals/latest_scan.json").read_text())["last_eligible_quarter"]
    result=collect(root,last)
    print(json.dumps(dict(issuer="2317",archived=result["records"],
          formal_pass_count=0,missing=result["coverage"]["missing_quarters"] if result["coverage"] else None,
          source_errors=result.get("source_errors",[])),ensure_ascii=False))

if __name__=="__main__":main()
