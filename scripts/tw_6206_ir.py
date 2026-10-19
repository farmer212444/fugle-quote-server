#!/usr/bin/env python3
"""Daily official 6206 investor-presentation PDF collection; NO automatic valuation approval."""
import argparse
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

TZ = dt.timezone(dt.timedelta(hours=8))
OUT = Path("tw-market-data/ir/6206")
RAW = Path("market-raw-ir/6206")
SITE = "https://www.flytech.com.tw/investor.php?act=analyst&year={year}"
DATE = re.compile(r"20\d{2}[/.\-](?:0?[1-9]|1[012])[/.\-](?:[012]?\d|3[01])")
TR = re.compile(r"<tr\b[^>]*>.*?</tr>", re.I | re.S)
ANCHOR = re.compile(r"<a\b[^>]*\bhref\s*=\s*[\"']([^\"']+)[\"']", re.I)
KEYS = ("EPS", "毛利率", "營業利益", "營益率", "營業收入", "營收",
        "存貨", "應收帳款", "展望", "AI", "SaaS", "客戶", "產品組合", "股利")
MAXPDF = 25_000_000

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def source_allowed(url):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.username or p.password or p.port or p.query or p.fragment:
        return False
    domain = (p.hostname or "").lower()
    path = urllib.parse.unquote(p.path.lower())
    if ".." in path.split("/") or "\\\\" in path:
        return False
    return (domain in ("www.flytech.com.tw","flytech.com.tw") and
            path.startswith("/data/investor_law/attached/") and path.endswith(".pdf")) or (
            domain == "mopsov.twse.com.tw" and
            re.fullmatch(r"/nas/str/6206\d{8}m\d{3}\.pdf",path) is not None)

def iso_date(text):
    m=DATE.search(text)
    if not m:return None
    s=m.group().replace("/","-").replace(".","-")
    y,month,day=[int(v) for v in s.split("-")]
    try:return dt.date(y,month,day).isoformat()
    except ValueError:return None

def plain(x):
    return html.unescape(re.sub(r"<[^>]*>"," ",x)).strip()

def parse_listing(raw,base):
    page=raw.decode("utf-8-sig",errors="replace")
    entries={}
    def consider(block):
        day=iso_date(plain(block))
        if not day:return
        for href in ANCHOR.findall(block):
            url=urllib.parse.urljoin(base,html.unescape(href).strip())
            if source_allowed(url):
                entries[(day,url)]=dict(date=day,pdf_url=url,listing_url=base)
    for row in TR.findall(page):consider(row)
    # Some versions use div/li cards instead of table rows; restrict each
    # discovered date+PDF to a local card and refuse ambiguous dates.
    if not entries:
        for match in ANCHOR.finditer(page):
            link=urllib.parse.urljoin(base,html.unescape(match.group(1)).strip())
            if not source_allowed(link):continue
            before=page[max(0,match.start()-900):match.start()]
            dates=[iso_date(plain(x)) for x in re.findall(
                r"20\d{2}[/.\-]\d{1,2}[/.\-]\d{1,2}",before)]
            dates=[d for d in dates if d]
            if dates:
                entries[(dates[-1],link)]=dict(date=dates[-1],pdf_url=link,listing_url=base)
    return sorted(entries.values(),key=lambda x:(x["date"],x["pdf_url"]),reverse=True)

def request(url,limit=MAXPDF):
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; public investor research archive)",
        "Accept":"application/pdf,text/html,*/*"})
    with urllib.request.urlopen(req,timeout=40) as resp:
        if resp.status!=200:raise ValueError("SOURCE_HTTP_STATUS_NOT_200")
        if urllib.parse.urlparse(resp.url).scheme!="https":
            raise ValueError("INSECURE_SOURCE_REDIRECT")
        if url.lower().endswith(".pdf") and not source_allowed(resp.url):
            raise ValueError("PDF_REDIRECTED_OUTSIDE_OFFICIAL_DOMAINS")
        result=resp.read(limit+1)
    if len(result)>limit:raise ValueError("SOURCE_TOO_LARGE")
    return result

def extract_pdf(blob):
    if not blob.startswith(b"%PDF-") or len(blob)<5000:
        raise ValueError("NOT_A_COMPLETE_ORIGINAL_PDF")
    import pymupdf
    doc=pymupdf.open(stream=blob,filetype="pdf")
    if doc.page_count<1 or doc.page_count>250:
        raise ValueError("PDF_PAGE_COUNT_INVALID")
    pages=[page.get_text("text") for page in doc]
    lead=" ".join(pages[:min(5,len(pages))]).lower()
    if not any(name in lead for name in ("6206","飛捷","flytech")):
        raise ValueError("PDF_ISSUER_ID_NOT_OBSERVED")
    if sum(len(p.strip()) for p in pages)<120:
        raise ValueError("PDF_NO_READABLE_TEXT_REQUIRES_MANUAL_REVIEW")
    return pages

def excerpts(pages):
    out=[]
    for i,body in enumerate(pages,1):
        lines=[" ".join(line.split()) for line in body.splitlines()]
        for n,line in enumerate(lines):
            if len(line)<4 or not any(k.lower() in line.lower() for k in KEYS):
                continue
            # Excerpts are source traceability, NOT extracted audited facts.
            excerpt=" ".join(lines[max(0,n-1):min(len(lines),n+2)])[:350]
            if excerpt and len(out)<35:
                out.append(dict(page=i,quote=excerpt))
    return out

def render_report(data):
    entries=data["presentations"]
    current=sorted(entries,key=lambda x:x["event_date"],reverse=True)
    lines=["# 6206 飛捷｜官方法說簡報自動擷取","",
        "來源：飛捷科技官方投資人關係網站；部分原件可另經 MOPS 查核。",
        "資料首次被程式觀測的時間，不等於公司原始公告時間。",
        "**不是正式財報審計、不是估值調整、不是13項A+門檻自動通過。**","",
        f"已保存 {len(current)} 份可讀官方簡報紀錄（如原網址更新，保留來源SHA）。",""]
    for e in current[:5]:
        lines += [f"## {e['event_date']}｜{e['title']}",
                  f"官方原件：{e['source_url']}",
                  f"PDF SHA256：`{e['pdf_sha256']}`",
                  f"逐頁文字：`{e['text_path']}`",
                  f"頁數：{e['pages']}；資料首次觀測：{e['first_captured_utc']}",""]
        for x in e.get("excerpts",[])[:12]:
            lines.append(f"- 第{x['page']}頁：{x['quote']}")
        lines.append("")
    return "\n".join(lines)+"\n"

def collect(asof=None,out=OUT,rawdir=RAW,fetch=request,max_documents=4):
    asof=asof or dt.datetime.now(TZ)
    now=asof.astimezone(dt.timezone.utc).isoformat()
    out=Path(out); rawdir=Path(rawdir)
    manifest=out/"manifest.json"
    existing=json.loads(manifest.read_text("utf-8")) if manifest.exists() else {}
    entries={x["source_url"]:x for x in existing.get("presentations",[])}
    found=[];errors=[]
    for year in (asof.year,asof.year-1):
        listing=SITE.format(year=year)
        try:
            page=fetch(listing,3_000_000)
            hits=parse_listing(page,listing)
            if not hits:raise ValueError("NO_VERIFIABLE_OFFICIAL_PDF_LINKS_FOUND")
            found.extend(hits)
        except Exception as e:
            errors.append(dict(source=listing,issue=type(e).__name__+":"+str(e)[:160]))
    if not found and not entries:
        raise ValueError("OFFICIAL_INVESTOR_LISTING_UNREACHABLE_NO_BASELINE")
    for item in sorted(found,key=lambda x:x["date"],reverse=True)[:max_documents]:
        url=item["pdf_url"]
        if item["date"]>asof.date().isoformat():continue
        try:
            blob=fetch(url,MAXPDF)
            sha=digest(blob)
            previous=entries.get(url)
            if previous and previous.get("pdf_sha256")==sha:
                continue
            pages=extract_pdf(blob)
            idpart=item["date"]+"_"+sha[:12]
            out.mkdir(parents=True,exist_ok=True)
            rawdir.mkdir(parents=True,exist_ok=True)
            path=rawdir/(idpart+".pdf")
            path.write_bytes(blob)
            textpath=out/(idpart+".txt")
            textdata="\n".join(f"=== Page {i} ===\n{text}" for i,text in enumerate(pages,1))
            textpath.write_text(textdata,encoding="utf-8")
            date=item["date"]
            title="6206 於 "+date+" 官方法人說明會簡報"
            entries[url]=dict(code="6206",source_url=url,
               listing_url=item["listing_url"],event_date=date,title=title,
               first_captured_utc=previous.get("first_captured_utc",now) if previous else now,
               latest_captured_utc=now,pdf_sha256=sha,original_pdf_artifact=path.as_posix(),
               pdf_archived_in_repository=False,original_company_filing_time_verified=False,
               pages=len(pages),text_path=textpath.as_posix(),
               extracted_text_sha256=digest(textdata.encode()),excerpts=excerpts(pages),
               gate_pass=False,formal_Aplus_unchanged=True)
            print("NEW_OFFICIAL_PRESENTATION",date,url,sha[:12],flush=True)
        except Exception as e:
            errors.append(dict(source=url,issue=type(e).__name__+":"+str(e)[:160]))
    if not entries:
        raise ValueError("NO_VERIFIED_FLYTECH_PRESENTATION_AVAILABLE:"+str(errors)[:500])
    records=sorted(entries.values(),key=lambda x:(x["event_date"],x["source_url"]),reverse=True)
    result=dict(schema="V887_OFFICIAL_PRESENTATION_COLLECTOR",code="6206",
                source_site=SITE.format(year=asof.year),
                search_years=[asof.year,asof.year-1],
                source_errors=errors,original_PIT_proven=False,
                formal_Aplus_count_added=0,presentations=records)
    content=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    md=render_report(result)
    out.mkdir(parents=True,exist_ok=True)
    if not manifest.exists() or manifest.read_text("utf-8")!=content:
        manifest.write_text(content,encoding="utf-8")
    report=out/"latest.md"
    if not report.exists() or report.read_text("utf-8")!=md:
        report.write_text(md,encoding="utf-8")
    print(json.dumps(dict(found=len(found),archived=len(records),
        new=len([e for e in records if e["latest_captured_utc"]==now]),
        errors=errors),ensure_ascii=False))
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--max-documents",type=int,default=4)
    args=p.parse_args()
    if not 1<=args.max_documents<=12:p.error("max-documents must be 1..12")
    collect(max_documents=args.max_documents)
