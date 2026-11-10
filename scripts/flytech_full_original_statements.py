#!/usr/bin/env python3
"""6206 official quarterly full-statement source intake; NO formal certification.

Only issuer-hosted PDF URLs actually discovered in the issuer's financial
report page may be archived. Each PDF must independently match company,
period, full financial-statement sections and minimum length. Capture is not
evidence of historical publication time or signed accounting review.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0,str(PROJECT))
from scripts.run_research_pipeline import atomic_json

DIRECTORY="https://www.flytech.com.tw/investor.php?act=results"
FOLDER="evidence/v880/originals/6206/full_statements"
MANIFEST=FOLDER+"/manifest.json"
SCHEMA="V8108_6206_QUARTERLY_FULL_ORIGINALS_V1"
MAX_INDEX=2_000_000
MAX_PDF=17_000_000
MAX_BATCH=70_000_000
REGEX_URL=re.compile(r"(?:https?://(?:www\.)?flytech\.com\.tw)?/?data/investor_season/attached/[0-9]{10,24}\.pdf",re.I)
QUARTER_WORDS={"一":1,"二":2,"三":3,"四":4}
SECTION_WORDS=("資產負債表","綜合損益表","權益變動表","現金流量表","財務報告附註")

def require(ok,why):
    if not ok:
        raise ValueError("FLYTECH_FULL_REPORT_"+why)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def quarter_window(last="2026-Q2"):
    m=re.fullmatch(r"(20\d\d)-Q([1-4])",last)
    require(m is not None,"BAD_QUARTER_WINDOW")
    n=int(m[1])*4+int(m[2])-1
    return [f"{i//4}-Q{i%4+1}" for i in range(n-7,n+1)]

def official_url(url):
    if not isinstance(url,str):return False
    parts=urllib.parse.urlsplit(url)
    return (parts.scheme=="https" and parts.netloc=="www.flytech.com.tw"
        and parts.username is None and parts.password is None
        and not parts.fragment and not parts.query
        and re.fullmatch(r"/data/investor_season/attached/[0-9]{10,24}\.pdf",parts.path) is not None)

def strip_markup(snippet):
    snippet=re.sub(r"<script\b[^>]*>[\s\S]*?</script>"," ",snippet,flags=re.I)
    return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",snippet))).strip()

def discover(raw,year):
    """Never infer a period from filename or requested year alone.

    Require a quarter label near the specific official issuer PDF anchor; if
    labels are ambiguous the link remains undiscovered, not mis-attributed.
    PDF internal identity is subsequently validated independently.
    """
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_INDEX,"INDEX_BYTES_INVALID")
    page=raw.decode("utf-8","replace")
    out,ambiguous={},[]
    for m in REGEX_URL.finditer(html.unescape(page)):
        url=urllib.parse.urljoin(DIRECTORY,m.group())
        if not official_url(url):continue
        # A row/list item is more trustworthy than the preceding unrelated
        # year selector. Do not use nearest quarter from other PDF rows.
        before=page[max(0,m.start()-1300):m.start()]
        context=None
        for tag in ("<tr","<li","<p"):
            mark=before.lower().rfind(tag)
            if mark>=0 and (context is None or mark>context):
                context=mark
        if context is not None:
            segment=before[context:]
        else:
            segment=before[-250:]
        # In the AJAX response the quarter may only appear *after* href
        # inside the current anchor; never inspect the next list item.
        tail=page[m.end():m.end()+220]
        tail=re.split(r"</a>|</li>|</tr>|<li|<tr",tail,1,flags=re.I)[0]
        label=strip_markup(segment+" "+tail)
        hits=[QUARTER_WORDS[x] for x in re.findall(r"第([一二三四])季",label)]
        hits += [int(x) for x in re.findall(r"\bQ([1-4])\b",label,re.I)]
        possible=sorted(set(hits))
        if len(possible)!=1:
            ambiguous.append(dict(url=url,status="PERIOD_LABEL_MISSING_OR_AMBIGUOUS"))
            continue
        quarter=possible[0]
        period=f"{year}-Q{quarter}"
        if period in out and out[period]!=url:
            raise ValueError("FLYTECH_FULL_REPORT_TWO_URLS_FOR_ONE_QUARTER")
        out[period]=url
    return out,ambiguous

def fetch(url,cap):
    allowed_index=(isinstance(url,str) and re.fullmatch(
        re.escape(DIRECTORY)+r"&year=20[0-9]{2}",url) is not None)
    if not allowed_index and not official_url(url):
        raise ValueError("FLYTECH_FULL_REPORT_UNTRUSTED_URL")
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (official issuer finance archive research)"})
    with urllib.request.urlopen(req,timeout=25) as resp:
        if resp.status!=200 or resp.geturl()!=url:
            raise ValueError("FLYTECH_FULL_REPORT_HTTP_OR_REDIRECT")
        body=resp.read(cap+1)
    require(200<len(body)<=cap,"SOURCE_EMPTY_OR_LARGE")
    return body

def season_options(raw):
    """Derive server-assigned season IDs from the issuer's own year selector."""
    text=raw.decode("utf-8","replace")
    match=re.search(r'<select\\b[^>]*\\bname\\s*=\\s*["\\\']season["\\\'][^>]*>(.*?)</select>',
                    text,re.I|re.S)
    if not match:return {}
    opts={}
    for val,year in re.findall(
        r'<option\\b[^>]*\\bvalue\\s*=\\s*["\\\'](\\d+)["\\\'][^>]*>\\s*(20\\d{2})\\s*</option>',
        match.group(1),re.I|re.S):
        if int(year) in opts and opts[int(year)]!=int(val):
            raise ValueError("FLYTECH_FULL_REPORT_DUPLICATE_SEASON_ID")
        opts[int(year)]=int(val)
    return opts

def fetch_season(season_id):
    """Issuer's public site.ajax.call route: POST /investor.php act=get_season."""
    require(type(season_id)==int and 1<=season_id<=99,"BAD_SEASON_ID")
    post=urllib.parse.urlencode(dict(act="get_season",season=season_id)).encode("ascii")
    url="https://www.flytech.com.tw/investor.php"
    req=urllib.request.Request(url,data=post,method="POST",headers={
        "User-Agent":"Mozilla/5.0 (issuer financial original archive)",
        "Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",
        "Accept":"application/json,text/javascript,*/*;q=0.8",
        "X-Requested-With":"XMLHttpRequest",
        "Referer":DIRECTORY})
    with urllib.request.urlopen(req,timeout=25) as resp:
        require(resp.status==200 and resp.geturl()==url,"SEASON_AJAX_HTTP_OR_REDIRECT")
        raw=resp.read(MAX_INDEX+1)
    require(0<len(raw)<=MAX_INDEX,"SEASON_AJAX_EMPTY_OR_OVERSIZE")
    doc=json.loads(raw)
    require(doc.get("error_code") in (None,0,"0"),"SEASON_AJAX_ERROR_CODE")
    fragment=doc.get("html",{}).get("season_list")
    require(isinstance(fragment,str),"SEASON_AJAX_LIST_NOT_FOUND")
    return fragment.encode("utf-8"),raw

def roc_digits(year):
    return "".join("零一二三四五六七八九"[int(x)] for x in str(year-1911))

def identity(raw,period):
    import fitz
    require(isinstance(raw,bytes) and 6000<=len(raw)<=MAX_PDF
            and raw.startswith(b"%PDF-") and b"%%EOF" in raw[-4096:],
            "PDF_BYTES_INVALID")
    year=int(period[:4]);q=int(period[-1]);month=("三月三十一","六月三十","九月三十","十二月三十一")[q-1]
    ascii_month=("03/31","06/30","09/30","12/31")[q-1]
    with fitz.open(stream=raw,filetype="pdf") as doc:
        require(22<=len(doc)<=400,"PDF_TOO_SHORT_FOR_FULL_STATEMENTS")
        head="".join(re.sub(r"\s+","",p.get_text()) for p in list(doc)[:min(len(doc),8)])
        alltext="".join(re.sub(r"\s+","",p.get_text()) for p in doc)
        matches_company=("飛捷科技" in head or "FlytechTechnology" in head) and (
            "6206" in head or "飛捷科技股份有限公司" in head)
        matches_year=(str(year-1911) in head or roc_digits(year) in head
                      or str(year) in head)
        matches_period=(month in head or
                        f"{q*3}月{31 if q in (1,4) else 30}日" in head or
                        f"{year}/{ascii_month}" in head)
        sec={s: s in alltext for s in SECTION_WORDS}
        if not matches_company or not matches_year or not matches_period:
            raise ValueError("FLYTECH_FULL_REPORT_PDF_COMPANY_OR_QUARTER_MISMATCH")
        require(all(sec.values()),"PDF_FOUR_STATEMENTS_AND_NOTES_NOT_PROVEN")
        return dict(page_count=len(doc),
            cover_issuer_and_quarter_match=True,
            complete_statements_headings_observed=True,
            sections=sec,source_identity_independently_rechecked=True,
            full_notes_content_reviewed=False,
            auditor_opinion_certified=False,
            filing_publication_PIT_verified=False,
            formal_gate_pass=False)

def safe(root,path):
    root=Path(root).resolve()
    rel=Path(path)
    dst=(root/rel).resolve()
    require(not rel.is_absolute() and ".." not in rel.parts
            and root in dst.parents,"ARCHIVE_UNSAFE_PATH")
    return dst

def prior_manifest(root):
    p=Path(root)/MANIFEST
    if not p.is_file():
        return dict(schema=SCHEMA,issuer="6206",original_issuer_directory=DIRECTORY,
            index_receipts=[],documents=[],fetch_errors=[],
            filing_publication_PIT_verified=False,
            formal_gate_passes_created=0)
    j=json.loads(p.read_text(encoding="utf-8"))
    require(j.get("schema")==SCHEMA and j.get("issuer")=="6206",
            "MANIFEST_SCHEMA_OR_ISSUER_MISMATCH")
    return j

def verify_archive(root,manifest,window):
    record={}
    for item in manifest["documents"]:
        period=item.get("period");url=item.get("source_url")
        require(period in window and official_url(url),"UNTRUSTED_ARCHIVE_RECORD")
        require(period not in record,"DUPLICATE_PERIOD_IN_ARCHIVE")
        raw=safe(root,item["archive_path"]).read_bytes()
        require(digest(raw)==item.get("sha256"),"PDF_ARCHIVE_HASH_MISMATCH")
        # Exact issuer and full-statement identity is always rechecked.
        checked=identity(raw,period)
        require(checked["complete_statements_headings_observed"],
                "PDF_IDENTITY_RECHECK_FAILED")
        record[period]=item
    require(manifest.get("formal_gate_passes_created")==0 and
            manifest.get("filing_publication_PIT_verified") is False,
            "FORGED_FORMAL_PASS_OR_PIT")
    return record

def collect(root,last="2026-Q2",now=None,max_new=3,fetcher=fetch,ajaxer=fetch_season):
    root=Path(root);window=quarter_window(last)
    require(type(max_new)==int and 0<=max_new<=4,"UNBOUNDED_FETCH_REQUEST")
    now=now or dt.datetime.now(dt.timezone.utc)
    require(now.tzinfo is not None,"NAIVE_TIME")
    manifest=prior_manifest(root)
    verified=verify_archive(root,manifest,window)
    urls={}
    errors=[]
    index_total=0
    # The website can change its select widget: each PDF must prove its own
    # period. Never use capture timestamp as historical source availability.
    for year in sorted({int(p[:4]) for p in window},reverse=True):
        url=DIRECTORY+"&year="+str(year)
        try:
            body=fetcher(url,MAX_INDEX)
            index_total+=len(body)
            require(index_total<=3*MAX_INDEX,"INDEX_TOTAL_OVERSIZE")
            discovered,ambiguous=discover(body,year)
            ids=season_options(body)
            if year in ids:
                try:
                    fragment,raw_ajax=ajaxer(ids[year])
                    require(type(fragment) is bytes and type(raw_ajax) is bytes,
                            "AJAX_SOURCE_BYTES_REQUIRED")
                    # The original JSON response is archived immutably so
                    # the issuer-origin link can be replayed in GitHub.
                    hx=digest(raw_ajax)
                    ajax_path=f"{FOLDER}/source_pages/{year}_{hx[:20]}_ajax.json"
                    ajax_dst=safe(root,ajax_path)
                    ajax_dst.parent.mkdir(parents=True,exist_ok=True)
                    if ajax_dst.exists():
                        require(ajax_dst.read_bytes()==raw_ajax,
                                "AJAX_ORIGINAL_BYTES_CHANGED")
                    else:ajax_dst.write_bytes(raw_ajax)
                    manifest.setdefault("ajax_receipts",[])
                    if not any(x.get("sha256")==hx for x in manifest["ajax_receipts"]):
                        manifest["ajax_receipts"].append(dict(
                            year=year,season_id=ids[year],url="https://www.flytech.com.tw/investor.php",
                            archive_path=ajax_path,sha256=hx,
                            captured_at_utc=now.isoformat()))
                    dynamic,ambiguous_ajax=discover(fragment,year)
                    discovered.update(dynamic)
                    ambiguous.extend(ambiguous_ajax)
                except Exception as exc:
                    errors.append(dict(year=year,reason="AJAX_"+type(exc).__name__,
                                       detail=str(exc)[:180]))
            idx_hash=digest(body)
            idx_rel=f"{FOLDER}/source_pages/{year}_{idx_hash[:20]}.html"
            dst=safe(root,idx_rel);dst.parent.mkdir(parents=True,exist_ok=True)
            if dst.exists():
                require(dst.read_bytes()==body,"INDEX_IMMUTABLE_CONFLICT")
            else:dst.write_bytes(body)
            if not any(r.get("sha256")==idx_hash and r.get("year")==year
                       for r in manifest["index_receipts"]):
                manifest["index_receipts"].append(dict(year=year,url=url,
                    archive_path=idx_rel,sha256=idx_hash,
                    captured_at_utc=now.isoformat()))
            for period,pdf in discovered.items():
                if period not in window:continue
                if period in urls and urls[period]!=pdf:
                    raise ValueError("FLYTECH_FULL_REPORT_CONFLICTING_DISCOVERY")
                urls[period]=pdf
            if ambiguous:
                errors.append(dict(year=year,reason="AMBIGUOUS_LINKS",
                                   count=len(ambiguous)))
            if not discovered:
                errors.append(dict(year=year,reason="NO_PERIOD_LINKS_DISCOVERED",
                                   source_index_sha256=idx_hash))
        except Exception as exc:
            errors.append(dict(year=year,reason="INDEX_"+type(exc).__name__,
                               detail=str(exc)[:140]))
    added=0;bytes_used=0
    for period in sorted(set(urls)-set(verified),reverse=True):
        if added>=max_new:break
        try:
            raw=fetcher(urls[period],MAX_PDF)
            bytes_used+=len(raw)
            require(bytes_used<=MAX_BATCH,"BATCH_DOWNLOAD_BYTES_EXCEEDED")
            details=identity(raw,period)
            sha=digest(raw)
            relative=f"{FOLDER}/{period}/{sha[:24]}.pdf"
            dst=safe(root,relative);dst.parent.mkdir(parents=True,exist_ok=True)
            if dst.exists():require(dst.read_bytes()==raw,"PDF_IMMUTABLE_CONFLICT")
            else:dst.write_bytes(raw)
            manifest["documents"].append(dict(period=period,source_url=urls[period],
                sha256=sha,bytes=len(raw),archive_path=relative,
                captured_at_utc=now.isoformat(),pdf_identity=details,
                official_issuer_link_discovered=True,
                first_publication_timestamp_verified=False,
                original_full_notes_reviewed=False,
                formal_gate_pass=False))
            added+=1
        except Exception as exc:
            errors.append(dict(period=period,reason="PDF_"+type(exc).__name__,
                               detail=str(exc)[:160],url=urls[period]))
    manifest["documents"].sort(key=lambda d:d["period"])
    manifest["last_evidence_collection_utc"]=now.isoformat()
    manifest["last_fetch_errors"]=errors
    manifest["last_discovery_count"]=len(urls)
    manifest["formal_gate_passes_created"]=0
    manifest["filing_publication_PIT_verified"]=False
    verified=verify_archive(root,manifest,window)
    atomic_json(root/MANIFEST,manifest)
    summary=dict(schema="V8108_6206_EIGHT_QUARTER_SOURCE_PROGRESS_V1",
        issuer="6206",target_financial_period=last,
        required_quarters=window,archived_quarters=sorted(verified),
        original_full_statements_archived=len(verified),
        original_quarters_missing=[p for p in window if p not in verified],
        newly_downloaded_quarters=added,source_period_links_discovered=len(urls),
        index_origin_capture_is_not_issuer_publication_PIT=True,
        source_note_contents_fully_reviewed=False,
        original_publication_PIT_certified=False,
        formal_Aplus=False,formal_gate_passes_issued=0,
        collection_errors=errors)
    atomic_json(root/"rankings/6206_full_original_statements_progress.json",summary)
    md=["# 6206 飛捷｜八季完整原始財報補檔（非正式PASS）","",
        "目標期："+last+"；已封存可重驗完整PDF："+str(len(verified))+"/8",
        "原件仍缺："+", ".join(summary["original_quarters_missing"]),
        "源網頁連結已辨識："+str(len(urls))+"；本次新增："+str(added)+"份",
        "來源頁取得時間不能代替原始公告發布時間；全文附註、會計師意見、13項關卡未完成正式核閱。",
        "","|季度|原始檔SHA|狀態|","|---|---|---|"]
    for p in window:
        row=verified.get(p)
        md.append("|"+p+"|"+(row["sha256"][:18] if row else "—")+"|"+
                  ("原始PDF已重驗，待核閱" if row else "待補官方財報")+"|")
    if errors:
        md.extend(["","來源缺漏或下載錯誤均已登錄 JSON，不當作已完成。"])
    md.extend(["","新增正式PASS：0；新增A+：0；沒有交易指令。",""])
    (root/"rankings/6206_full_original_statements_progress.md").write_text(
        "\n".join(md),encoding="utf-8")
    return summary

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-root",default="tw-market-data")
    ap.add_argument("--last",default="2026-Q2")
    ap.add_argument("--max-new",type=int,default=3)
    args=ap.parse_args()
    result=collect(args.data_root,last=args.last,max_new=args.max_new)
    print(json.dumps(dict(original_pdf_quarters=result["original_full_statements_archived"],
        found_links=result["source_period_links_discovered"],
        new=result["newly_downloaded_quarters"],
        missing=result["original_quarters_missing"],
        formal_gate_passes=0),ensure_ascii=False))
if __name__=="__main__":
    main()
