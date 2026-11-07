#!/usr/bin/env python3
"""Archive SEC-filed TSMC consolidated reports as separately labeled evidence.

The 6-K exhibits are issuer-provided English translations of Chinese reports.
Their bytes and disclosure periods can be rechecked, but never constitute a
Chinese-original reconciliation, human review, historical MOPS PIT, or PASS.
"""
import argparse
import datetime as dt
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.run_research_pipeline import atomic_json

ISSUER='2330'
FOLDER='evidence/v880/originals/2330/sec_6k_exhibits'
MAX_BYTES=10_000_000
MIN_BYTES=80_000
# Exact SEC Exhibit 99.1 URLs verified against TSMC CIK 1046179 6-K records.
# No generated accession numbers, URL guesses or third-party content mirrors.
FILING_URLS={
 '2024-Q3':'https://www.sec.gov/Archives/edgar/data/1046179/000104617924000126/tsmc2024q3consolidatedfina.htm',
 '2025-Q1':'https://www.sec.gov/Archives/edgar/data/1046179/000104617925000059/tsmc2025q1consolidatdfinan.htm',
 '2025-Q2':'https://www.sec.gov/Archives/edgar/data/1046179/000104617925000097/tsmc2025q2consolidatedfina.htm',
 '2025-Q3':'https://www.sec.gov/Archives/edgar/data/1046179/000104617925000128/a2025q3consolidatedreport-.htm',
 '2025-Q4':'https://www.sec.gov/Archives/edgar/data/1046179/000104617926000024/a2025q4consolidatedreport-.htm',
 '2026-Q1':'https://www.sec.gov/Archives/edgar/data/1046179/000104617926000278/a2026q1consolidatedreport-.htm',
 '2026-Q2':'https://www.sec.gov/Archives/edgar/data/1046179/000104617926000541/a2026q2consolidatedreport-.htm',
}
MONTHS={1:'MARCH',2:'JUNE',3:'SEPTEMBER',4:'DECEMBER'}
DAYS={1:'31',2:'30',3:'30',4:'31'}


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.words=[]
    def handle_data(self,data):
        self.words.append(data)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(raw,quarter):
    if not MIN_BYTES<=len(raw)<=MAX_BYTES or b'<html' not in raw[:2000].lower():
        raise ValueError('TSMC_SEC_EXHIBIT_NOT_FULL_HTML')
    parser=Text()
    parser.feed(raw.decode('utf-8','replace'))
    body=re.sub(r'\s+',' ',unescape(' '.join(parser.words)).upper())
    y,q=map(int,(quarter[:4],quarter[-1]))
    period=f'{MONTHS[q]} {DAYS[q]}, {y}'
    required=(
        'TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY LIMITED',
        'AND SUBSIDIARIES',
        'CONSOLIDATED BALANCE SHEETS',
        'CONSOLIDATED STATEMENTS OF COMPREHENSIVE INCOME',
        'CONSOLIDATED STATEMENTS OF CASH FLOWS',
        'NOTES TO CONSOLIDATED FINANCIAL STATEMENTS',
        period.upper(),
    )
    missing=[v for v in required if v not in body]
    if missing:raise ValueError('TSMC_SEC_PERIOD_OR_COMPLETE_STATEMENT_MISMATCH:'+repr(missing))
    return dict(issuer='TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY LIMITED',
                reported_period=quarter,period_marker=period,
                four_main_sections_and_notes_heading_detected=True,
                full_accounting_notes_human_review_complete=False,
                chinese_original_reconciliation_complete=False,
                original_MOPS_PIT_verified=False,
                formal_gate_pass=False)


def fetch(url):
    if url not in FILING_URLS.values():raise ValueError('TSMC_SEC_URL_NOT_ALLOWLISTED')
    req=urllib.request.Request(url,headers={
        'User-Agent':'Public issuer report verification https://github.com/farmer212444/fugle-quote-server',
        'Accept':'text/html'})
    with urllib.request.urlopen(req,timeout=12) as resp:
        if resp.status!=200 or resp.geturl()!=url:
            raise ValueError('TSMC_SEC_HTTP_STATUS_OR_REDIRECT')
        raw=resp.read(MAX_BYTES+1)
    return raw


def safe(root,rel):
    base=root.resolve();p=Path(rel);target=(base/p).resolve()
    if p.is_absolute() or '..' in p.parts or base not in target.parents:
        raise ValueError('TSMC_SEC_ARCHIVE_UNSAFE_PATH')
    return target


def collect(root,*,fetcher=fetch,clock=lambda:dt.datetime.now(dt.timezone.utc),
            pause=lambda n:time.sleep(n)):
    root=Path(root).resolve();manifest=root/FOLDER/'manifest.json'
    if manifest.exists():
        meta=json.loads(manifest.read_text(encoding='utf-8'))
        if (meta.get('issuer')!=ISSUER or meta.get('schema')!='TSMC_SEC_6K_SOURCE_ARCHIVE_V1'
            or meta.get('formal_gate_pass') is not False):
            raise ValueError('TSMC_SEC_ARCHIVE_IDENTITY_INVALID')
        rows=meta.get('documents',[])
    else:
        rows=[];meta=dict(schema='TSMC_SEC_6K_SOURCE_ARCHIVE_V1',issuer=ISSUER,
                          formal_gate_pass=False,documents=rows)
    seen=set()
    for row in rows:
        quarter=row['period']
        if (quarter in seen or FILING_URLS.get(quarter)!=row['source_url']
            or row.get('origin')!='SEC_6K_EXHIBIT_99_1'):
            raise ValueError('TSMC_SEC_DUPLICATE_OR_UNTRUSTED_RECEIPT')
        seen.add(quarter)
        raw=safe(root,row['archive_path']).read_bytes()
        if len(raw)!=row['bytes'] or digest(raw)!=row['sha256']:
            raise ValueError('TSMC_SEC_ARCHIVE_HASH_MISMATCH')
        if identity(raw,quarter)!=row['identity']:
            raise ValueError('TSMC_SEC_ARCHIVE_IDENTITY_RECHECK_MISMATCH')
    failures=[]
    for quarter,url in FILING_URLS.items():
        if quarter in seen:continue
        try:
            raw=fetcher(url);kind=identity(raw,quarter);sha=digest(raw)
            rel=f'{FOLDER}/{quarter}_{sha[:20]}.html'
            target=safe(root,rel);target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and target.read_bytes()!=raw:
                raise ValueError('TSMC_SEC_ARCHIVE_IMMUTABILITY_CONFLICT')
            if not target.exists():target.write_bytes(raw)
            rows.append(dict(period=quarter,source_url=url,origin='SEC_6K_EXHIBIT_99_1',
                             sha256=sha,bytes=len(raw),archive_path=rel,
                             captured_at_utc=clock().isoformat(),identity=kind))
            seen.add(quarter)
        except (OSError,ValueError,UnicodeError) as exc:
            failures.append(dict(period=quarter,error=type(exc).__name__+':'+str(exc)))
        pause(1)
    meta.update(last_checked_at_utc=clock().isoformat(),last_errors=failures)
    atomic_json(manifest,meta)
    return dict(schema=meta['schema'],issuer=ISSUER,
                sec_translated_exhibits_verified=len(seen),
                expected_sec_exhibits=len(FILING_URLS),
                archived_quarters=sorted(seen),
                missing_quarters=sorted(set(FILING_URLS)-seen),
                source_errors=failures,documents=rows,
                chinese_original_pdf_gate_unmodified=True,
                original_full_content_review_complete=False,
                original_MOPS_PIT_verified=False,formal_gate_pass=False)


def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',default='tw-market-data')
    a=p.parse_args();root=Path(a.data_root)
    result=collect(root)
    atomic_json(root/'rankings/tsmc_sec_filing_archive.json',result)
    lines=['# 2330 SEC 6-K 原始申報英譯財報備援封存','',
           f"已封存核對：{result['sec_translated_exhibits_verified']}/{result['expected_sec_exhibits']} 期。",
           'SEC Exhibits 為台積電英文譯本及官方申報資料，不是原始中文全文查核、會計師核閱範圍的人工簽核或 PIT 證書。',
           '與台積電官網中文原件獨立存證，不能以英譯資料自動換發13項正式PASS。','',
           '|季度|證據來源|狀態|','|---|---|---|']
    for q,url in FILING_URLS.items():
        lines.append(f"|{q}|{url}|{'SEC原件SHA封存待核' if q in result['archived_quarters'] else '取得失敗待補'}|")
    for item in result['source_errors']:
        lines.append(f"- {item['period']}：{item['error']}")
    (root/'rankings/tsmc_sec_filing_archive.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(archived=result['sec_translated_exhibits_verified'],
        expected=result['expected_sec_exhibits'],errors=len(result['source_errors']),
        formal_gate_pass=False),ensure_ascii=False))


if __name__=='__main__':main()
