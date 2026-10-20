#!/usr/bin/env python3
"""V8.9.6 durable original issuer PDF intake (NOT A+ certification).

Captures publisher-hosted PDF bytes into Git, rather than relying solely on
90-day Actions artifacts. Does not assert MOPS publication PIT, full original
identity review, legal signoff, or any of the 13 formal PASS/FAIL decisions.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

MAX_FILE_BYTES = 8_000_000
MAX_TOTAL_BYTES = 35_000_000
SCHEMA = "V896_DURABLE_ORIGINAL_PDF_NOT_CERTIFIED"
HOSTS = {"9802": {"www.fulgentsun.com", "fulgentsun.com"},
         "6206": {"www.flytech.com.tw", "flytech.com.tw"}}
FOCUS_QUARTERS = {
    # 2024 Q3 to 2026 Q2: eight distinct quarters if the publisher supplies
    # each valid document. The publisher's 2025 Q3 link sometimes is '/.pdf'.
    "2024-08", "2024-11", "2025-02", "2025-05", "2025-08",
    "2025-11", "2026-02", "2026-05", "2026-08",
}


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def is_official(issuer, url):
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parsed.path)
    if (parsed.scheme != "https" or parsed.netloc.lower() not in HOSTS[issuer]
            or parsed.username or parsed.password or parsed.port
            or parsed.fragment or parsed.query
            or ".." in path.split("/") or "\\" in path):
        return False
    if issuer == "9802":
        return (path.startswith("/img/Finance/") or path.startswith("/img/News_Release/")) and (
            path.lower().endswith(".pdf") and path.rsplit("/", 1)[-1].lower() != ".pdf")
    return (path.startswith("/data/investor_law/attached/")
            and path.lower().endswith(".pdf") and path.rsplit("/", 1)[-1] != ".pdf")


def select_sources(issuer, source, asof_day, max_documents=12):
    chosen = []
    if issuer == "9802":
        if source.get("issuer") != "9802" or source.get("publisher") != "鈺齊國際":
            raise ValueError("9802_SOURCE_MANIFEST_ISSUER_MISMATCH")
        receipt_map = source.get("receipts", {})
        for item in source.get("discovered", []):
            date = item.get("site_display_date", "")
            title = str(item.get("title", ""))
            category = item.get("category")
            if (date > asof_day or not is_official(issuer, item.get("url", ""))
                    or not re.fullmatch(r"[0-9a-f]{20}", str(item.get("id", "")))):
                continue
            target_quarter = (category == "quarterly" and date[:7] in FOCUS_QUARTERS
                              and ("財務" in title or "合併" in title))
            early_q3 = (category == "news" and date.startswith("2026-10")
                        and "第三季" in title and "自結" in title)
            if not (target_quarter or early_q3):
                continue
            versions = receipt_map.get(item["id"], {}).get("versions", [])
            hashes = [v.get("sha256") for v in versions]
            chosen.append(dict(id=item["id"], category=category, document_date=date,
                               title=title, url=item["url"], expected_hashes=hashes))
        chosen.sort(key=lambda x:(x["category"] == "news", x["document_date"]), reverse=True)
    else:
        if source.get("code") != "6206":
            raise ValueError("6206_SOURCE_MANIFEST_ISSUER_MISMATCH")
        for item in source.get("presentations", []):
            day = item.get("event_date", "")
            url = item.get("source_url", "")
            hash_value = item.get("pdf_sha256")
            if (day > asof_day or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(day))
                    or not is_official(issuer, url)
                    or not re.fullmatch(r"[a-f0-9]{64}", str(hash_value))):
                continue
            chosen.append(dict(id=digest(url.encode())[:20], category="presentation",
                               document_date=day, title=item.get("title", ""),
                               url=url, expected_hashes=[hash_value]))
        chosen.sort(key=lambda x:x["document_date"],reverse=True)
    keys = [x["url"] for x in chosen]
    if len(keys) != len(set(keys)):
        raise ValueError("DUPLICATE_PUBLISHER_DOCUMENT_URL")
    return chosen[:max_documents]


def fetch_pdf(issuer, url):
    if not is_official(issuer, url):
        raise ValueError("NON_OFFICIAL_SOURCE_URL")
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (public-investor-evidence-original-archive)",
        "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200 or not is_official(issuer, response.geturl()):
            raise ValueError("PUBLISHER_PDF_REDIRECT_OR_STATUS_INVALID")
        raw = response.read(MAX_FILE_BYTES + 1)
    return raw


def validate_pdf(raw):
    if (not isinstance(raw, bytes) or len(raw) < 5000 or len(raw) > MAX_FILE_BYTES
            or not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-4096:]):
        raise ValueError("INVALID_OR_OVERSIZE_PDF_BYTES")
    return digest(raw)


def _safe_local(root, relative):
    rel = Path(relative)
    target = (root / rel).resolve()
    if rel.is_absolute() or ".." in rel.parts or root.resolve() not in target.parents:
        raise ValueError("UNSAFE_ORIGINAL_ARCHIVE_PATH")
    return target


def validate_bundle(root, issuer):
    """Verify durable SHA integrity; do not interpret this as auditor signoff."""
    root = Path(root).resolve()
    path = root / "evidence/v880/originals" / issuer / "manifest.json"
    if not path.is_file():
        return dict(issuer=issuer, records=0, statuses=["NO_DURABLE_ORIGINALS_YET"],
                    original_archive_hashes_verified=False, formal_pass_count=0)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != SCHEMA or manifest.get("issuer") != issuer
            or manifest.get("formally_certified_gates") != 0
            or manifest.get("original_MOPS_PIT_verified") is not False):
        raise ValueError("SOURCE_BUNDLE_FALSE_CERTIFICATION_OR_ISSUER")
    unique=set()
    for record in manifest.get("documents", []):
        if (record.get("issuer") != issuer or not is_official(issuer, record.get("source_url",""))
                or not re.fullmatch(r"[a-f0-9]{64}", record.get("sha256",""))
                or record.get("formal_gate_pass") is not False
                or record.get("independently_verified_issuer_filing_time") is not False):
            raise ValueError("SOURCE_BUNDLE_INVALID_RECORD")
        path_str=record.get("archive_path","")
        parts=Path(path_str).parts
        if parts[:4] != ("evidence","v880","originals",issuer) or len(parts)!=5:
            raise ValueError("SOURCE_BUNDLE_ARCHIVE_OUTSIDE_ISSUER_DIRECTORY")
        if path_str in unique:
            raise ValueError("DUPLICATE_ORIGINAL_ARCHIVE_PATH")
        unique.add(path_str)
        archive = _safe_local(root, path_str)
        raw=archive.read_bytes()
        if validate_pdf(raw) != record["sha256"] or len(raw) != record["bytes"]:
            raise ValueError("DURABLE_ORIGINAL_PDF_HASH_OR_SIZE_MISMATCH")
        if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}T.+[+-]\d\d:\d\d",record.get("captured_at_utc","")):
            raise ValueError("ORIGINAL_CAPTURE_TIMESTAMP_MISSING")
    kinds={k:sum(x["document_kind"]==k for x in manifest["documents"])
           for k in ("quarterly","presentation","news")}
    return dict(issuer=issuer, records=len(unique), document_kinds=kinds,
                statuses=["ARCHIVED_ORIGINAL_BYTES_NOT_REVIEWED"],
                original_archive_hashes_verified=True,
                formal_pass_count=0)


def collect(root, issuer, asof_day, now, max_documents=12, fetcher=fetch_pdf):
    root=Path(root).resolve()
    source_path=(root/("issuer/9802/manifest.json" if issuer=="9802"
                       else "ir/6206/manifest.json"))
    source=json.loads(source_path.read_text(encoding="utf-8"))
    selected=select_sources(issuer,source,asof_day,max_documents)
    if not selected:
        raise ValueError("NO_ELIGIBLE_PUBLISHER_DOCUMENTS")
    folder=root/"evidence/v880/originals"/issuer
    manifest_path=folder/"manifest.json"
    old=json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    if old:
        validate_bundle(root,issuer)
    records={x["sha256"]:x for x in (old or {}).get("documents",[])}
    errors=[];bytes_total=0;captured=0;reused=0;hash_discrepancies=0
    for item in selected:
        # A publisher may revise an existing URL. Reuse only the *latest*
        # previously captured SHA, never a superseded historical version.
        latest_receipt = item["expected_hashes"][-1] if item["expected_hashes"] else None
        known=next((x for x in records.values() if x["source_url"]==item["url"]
                    and (x["sha256"] == latest_receipt or
                         x.get("earlier_capture_sha256s")==item["expected_hashes"])),None)
        if known:
            reused+=1
            continue
        try:
            raw=fetcher(issuer,item["url"])
            current=digest(raw) if isinstance(raw,bytes) else ""
            sha=validate_pdf(raw)
            if bytes_total+len(raw)>MAX_TOTAL_BYTES:
                raise ValueError("MAX_BATCH_ARCHIVE_BYTES_EXCEEDED")
            bytes_total+=len(raw)
            different=bool(item["expected_hashes"] and sha not in item["expected_hashes"])
            if sha in records:
                if records[sha]["source_url"] != item["url"]:
                    raise ValueError("SAME_SHA_DIFFERENT_SOURCE_IDENTITY_REVIEW")
                reused+=1
                continue
            dirname=f"{item['document_date']}_{item['id']}_{sha[:16]}.pdf"
            rel=Path("evidence/v880/originals")/issuer/dirname
            path=_safe_local(root,rel)
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists() and path.read_bytes()!=raw:
                raise ValueError("IMMUTABLE_PUBLISHER_PDF_PATH_CONFLICT")
            path.write_bytes(raw)
            record=dict(issuer=issuer,id=item["id"],document_kind=item["category"],
                document_date=item["document_date"],title=item["title"],source_url=item["url"],
                archive_path=rel.as_posix(),sha256=sha,bytes=len(raw),
                captured_at_utc=now,source_original_hash_matches_previous_receipt=not different,
                earlier_capture_sha256s=item["expected_hashes"],
                source_is_official_issuer_https_domain=True,
                issuer_pdf_content_independently_reviewed=False,
                independently_verified_issuer_filing_time=False,
                formal_gate_pass=False)
            records[sha]=record
            captured+=1
            if different:hash_discrepancies+=1
        except Exception as exc:
            errors.append(dict(url=item["url"],issue=type(exc).__name__+":"+str(exc)[:160]))
    if not records:
        raise ValueError("NO_ORIGINALS_ARCHIVED; ERRORS="+str(errors)[:300])
    document_list=sorted(records.values(),key=lambda x:(x["document_date"],x["sha256"]),reverse=True)
    manifest=dict(schema=SCHEMA,issuer=issuer,
        archival_status="ORIGINAL_BYTES_SHA256_CHECKED_NOT_A_FORMAL_GATE",
        source_discovered_from_publisher_manifest=True,
        original_MOPS_PIT_verified=False,original_document_content_independently_reviewed=False,
        formally_certified_gates=0,documents=document_list,
        limitations=["Publisher HTTPS and original PDF bytes establish reproducible captures, not filing PIT.",
                     "Full eight-quarter notes, issuer identity, audited scope, capital terms and reviewer attestation remain unverified.",
                     "Revision or receipt SHA mismatch is retained and requires independent comparison before use."])
    folder.mkdir(parents=True,exist_ok=True)
    new=json.dumps(manifest,ensure_ascii=False,indent=2)+"\n"
    if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8")!=new:
        manifest_path.write_text(new,encoding="utf-8")
    checked=validate_bundle(root,issuer)
    return dict(**checked,selected=len(selected),captured=captured,reused=reused,
                receipt_hash_discrepancies=hash_discrepancies,errors=errors)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--issuer",choices=["9802","6206"],required=True)
    ap.add_argument("--root",default="tw-market-data")
    ap.add_argument("--max-documents",type=int,default=12)
    ap.add_argument("--verify-only",action="store_true")
    args=ap.parse_args()
    if not 1<=args.max_documents<=12:
        ap.error("max-documents must be 1..12")
    now=dt.datetime.now(dt.timezone.utc)
    local_day=now.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    report=(validate_bundle(args.root,args.issuer) if args.verify_only
            else collect(args.root,args.issuer,local_day,now.isoformat(),args.max_documents))
    print(json.dumps(report,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
