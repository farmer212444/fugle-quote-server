#!/usr/bin/env python3
"""2330 full issuer statements: durable original bytes, never a formal PASS.

The cover and contents are checked for issuer/period/scope. Raster statement
pages are explicitly left for OCR and review; filenames and hashes alone do
not establish accounting accuracy, an auditor opinion, or disclosure PIT.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import http.client
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.run_research_pipeline import atomic_json

DIRECTORY='https://investor.tsmc.com/chinese/financial-reports'
FOLDER='evidence/v880/originals/2330/full_statements'
MANIFEST=FOLDER+'/manifest.json'
SCHEMA='TSMC_2330_FULL_ORIGINAL_STATEMENTS_SOURCE_INTAKE_V1'
MAX_PDF=25_000_000
MAX_BATCH=175_000_000
TAIPEI=dt.timezone(dt.timedelta(hours=8))
SECTIONS=('合併資產負債表','合併綜合損益表','合併權益變動表',
          '合併現金流量表','合併財務報告附註')
HTTP403_RETRY_DELAY=dt.timedelta(hours=24)


def digest(raw):return hashlib.sha256(raw).hexdigest()


def aware(value):
    value=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('TSMC_SOURCE_CAPTURE_TIMEZONE_REQUIRED')
    return value


def quarter_window(last):
    m=re.fullmatch(r'(20\d{2})-Q([1-4])',str(last))
    if not m:raise ValueError('TSMC_INVALID_QUARTER_WINDOW')
    n=int(m[1])*4+int(m[2])-1
    return [f'{i//4}-Q{i%4+1}' for i in range(n-7,n+1)]


def pdf_url(url):
    if not isinstance(url,str):return False
    u=urllib.parse.urlsplit(url)
    path=urllib.parse.unquote(u.path)
    return (u.scheme=='https' and u.netloc=='investor.tsmc.com'
            and not u.query and not u.fragment
            and re.fullmatch(r'/sites/ir/financial-report/(20\d{2})/TSMC (20\d{2})Q[1-4] Consolidated Financial Statements_C(?:_\d+)?\.pdf',path) is not None
            and path.split('/')[4]==re.search(r'TSMC (20\d{2})',path)[1])


class DirectoryLinks(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.href=None;self.parts=[];self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.href=dict(attrs).get('href');self.parts=[]
    def handle_data(self,data):
        if self.href:self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='a':
            if self.href:self.links.append((self.href,''.join(self.parts).strip()))
            self.href=None


def discover(raw,required):
    parser=DirectoryLinks();parser.feed(raw.decode('utf-8-sig'))
    result={}
    for href,label in parser.links:
        url=urllib.parse.urljoin(DIRECTORY,href)
        if not pdf_url(url):continue
        m=re.search(r'(20\d{2})Q([1-4])',urllib.parse.unquote(url))
        year,q=int(m[1]),int(m[2]);period=f'{year}-Q{q}'
        if period not in required:continue
        expected={1:f'{year}年度第一季',2:f'{year}年度上半年度',
                  3:f'{year}年度前三季',4:f'{year}年'}[q]
        if re.sub(r'\s+','',label)!=expected:raise ValueError('TSMC_DIRECTORY_LABEL_PERIOD_MISMATCH')
        spec=dict(period=period,title=label,source_url=url)
        if period in result and result[period]!=spec:raise ValueError('TSMC_AMBIGUOUS_QUARTER_SOURCE')
        result[period]=spec
    return result


def fetch(url,limit):
    if url!=DIRECTORY and not pdf_url(url):raise ValueError('TSMC_UNTRUSTED_SOURCE_URL')
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (issuer-original financial source archive)'})
    with urllib.request.urlopen(request,timeout=45) as response:
        if response.status!=200 or response.geturl()!=url:raise ValueError('TSMC_SOURCE_HTTP_OR_REDIRECT_INVALID')
        raw=response.read(limit+1)
    if not 1000<len(raw)<=limit:raise ValueError('TSMC_SOURCE_EMPTY_OR_OVERSIZED')
    return raw


def pdf_identity(raw,period):
    import fitz
    if not 5000<=len(raw)<=MAX_PDF or not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-4096:]:
        raise ValueError('TSMC_INVALID_OR_OVERSIZED_ORIGINAL_PDF')
    with fitz.open(stream=raw,filetype='pdf') as doc:
        if not 20<=len(doc)<=300:raise ValueError('TSMC_FULL_REPORT_PAGE_COUNT_INVALID')
        cover=re.sub(r'\s+','',doc[0].get_text())
        toc=re.sub(r'\s+','',doc[1].get_text())
        year,q=map(int,(period[:4],period[-1]));roc=year-1911
        header=f'民國{roc}及{roc-1}年度' if q==4 else f'民國{roc}及{roc-1}年第{q}季'
        # Scanned images and outlined glyphs both have no extractable text.
        # Preserve official-directory-linked bytes with explicit identity PENDING.
        raster_cover_and_contents=(not cover and not toc and
            bool(doc[0].get_images() or doc[0].get_drawings()) and
            bool(doc[1].get_images() or doc[1].get_drawings()))
        if not raster_cover_and_contents and ('台灣積體電路製造股份有限公司' not in cover or '及子公司' not in cover
            or '合併財務報告暨會計師' not in cover or header not in cover):
            raise ValueError('TSMC_PDF_INTERNAL_ISSUER_OR_PERIOD_MISMATCH')
        if not raster_cover_and_contents and not all(s in toc for s in SECTIONS):
            raise ValueError('TSMC_FULL_STATEMENTS_AND_NOTES_NOT_LISTED')
        core=[i for i in range(2,min(12,len(doc))) if len(re.sub(r'\s+','',doc[i].get_text()))<40]
        return dict(page_count=len(doc),pdf_cover_issuer_and_period_verified=not raster_cover_and_contents,
            four_statements_and_notes_listed_in_contents=not raster_cover_and_contents,
            identity_status=('RASTER_COVER_AND_CONTENTS_OCR_OR_VISUAL_REVIEW_REQUIRED'
                             if raster_cover_and_contents else 'NATIVE_COVER_AND_CONTENTS_CHECKED'),
            raster_or_unextractable_core_pages_1based=[i+1 for i in core],
            financial_statement_and_note_content_review_complete=False,
            auditor_opinion_formally_reviewed=False)


def safe(root,relative):
    p=Path(relative);target=(root/p).resolve()
    if p.is_absolute() or '..' in p.parts or root not in target.parents:
        raise ValueError('TSMC_SOURCE_ARCHIVE_UNSAFE_PATH')
    return target


def store_bytes(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('TSMC_IMMUTABLE_ARCHIVE_CONFLICT')
    else:
        with path.open('xb') as f:f.write(raw)


def validate_archive(root,last_quarter,asof):
    root=Path(root).resolve();required=quarter_window(last_quarter);cut=aware(asof)
    path=root/MANIFEST
    if not path.exists():
        records=[];indices={}
    else:
        m=json.loads(path.read_text(encoding='utf-8'))
        if (m.get('schema')!=SCHEMA or m.get('issuer')!='2330'
            or m.get('formal_gate_pass') is not False or m.get('original_MOPS_PIT_verified') is not False
            or m.get('full_content_review_complete') is not False):
            raise ValueError('TSMC_ARCHIVE_SCHEMA_OR_FALSE_CERTIFICATION')
        indices={}
        for entry in m.get('index_versions',[]):
            if aware(entry['captured_at_utc'])>cut:continue
            h=entry['sha256'];rel=f'{FOLDER}/index_{h}.html'
            if entry.get('archive_path')!=rel or entry.get('source_url')!=DIRECTORY or not re.fullmatch(r'[a-f0-9]{64}',h):
                raise ValueError('TSMC_SOURCE_INDEX_IDENTITY_INVALID')
            raw=safe(root,rel).read_bytes()
            if digest(raw)!=h:raise ValueError('TSMC_SOURCE_INDEX_HASH_MISMATCH')
            if h in indices:raise ValueError('TSMC_DUPLICATE_SOURCE_INDEX')
            indices[h]=(raw,aware(entry['captured_at_utc']))
        records=[];seen=set()
        for entry in m.get('documents',[]):
            captured=aware(entry['captured_at_utc'])
            if captured>cut:continue
            period=entry['period'];h=entry['sha256'];url=entry['source_url']
            if not re.fullmatch(r'[a-f0-9]{64}',h):raise ValueError('TSMC_DOCUMENT_HASH_INVALID')
            rel=f'{FOLDER}/{period}_{h[:20]}.pdf'
            if entry.get('archive_path')!=rel or not pdf_url(url) or entry.get('formal_gate_pass') is not False:
                raise ValueError('TSMC_DOCUMENT_IDENTITY_OR_FALSE_CERTIFICATION')
            if (period,h) in seen:raise ValueError('TSMC_DUPLICATE_ORIGINAL_VERSION')
            seen.add((period,h))
            index=indices.get(entry['index_sha256'])
            if index is None or index[1]>captured:raise ValueError('TSMC_ORIGINAL_DIRECTORY_PROVENANCE_MISSING')
            spec=discover(index[0],[period]).get(period)
            if not spec or spec['source_url']!=url or spec['title']!=entry.get('title'):
                raise ValueError('TSMC_ORIGINAL_NOT_LINKED_BY_ISSUER_DIRECTORY')
            raw=safe(root,rel).read_bytes()
            if digest(raw)!=h or len(raw)!=entry['bytes']:raise ValueError('TSMC_ORIGINAL_PDF_HASH_OR_SIZE_MISMATCH')
            identity=pdf_identity(raw,period)
            if identity!=entry.get('pdf_identity'):raise ValueError('TSMC_PDF_METADATA_NOT_REPRODUCIBLE')
            records.append(entry)
    found=sorted({r['period'] for r in records}&set(required))
    identified=sorted({r['period'] for r in records
                       if r['pdf_identity']['pdf_cover_issuer_and_period_verified']}&set(required))
    coverage=dict(required_quarters=required,found_quarters=found,
        missing_quarters=[p for p in required if p not in found],
        source_title_coverage_complete=len(found)==8,
        pdf_accounting_period_internal_identity_verified=bool(found) and identified==found,
        native_cover_identity_verified_quarters=identified,
        native_cover_identity_pending_quarters=[p for p in found if p not in identified],
        full_original_pdf_content_reviewed=False,
        eight_full_report_notes_and_auditor_scope_reviewed=False,
        original_MOPS_PIT_verified=False,formal_gate_pass=False,
        source_window_end=last_quarter)
    return dict(issuer='2330',records=len(records),document_kinds=dict(quarterly=len(records)),
        original_archive_hashes_verified=bool(records),formal_pass_count=0,
        statuses=['ISSUER_LINKED_ORIGINAL_BYTES_RECHECKED_NOT_CONTENT_CERTIFIED'] if records else ['NO_DURABLE_FULL_ORIGINALS_YET'],
        coverage=coverage,documents=records)


def collect(root,last_quarter,*,fetcher=fetch,clock=lambda:dt.datetime.now(dt.timezone.utc)):
    root=Path(root).resolve();required=quarter_window(last_quarter);now=clock()
    if now.tzinfo is None:raise ValueError('TSMC_SOURCE_CAPTURE_TIMEZONE_REQUIRED')
    year,q=int(last_quarter[:4]),int(last_quarter[-1])
    end=dt.date(year+(q==4),1 if q==4 else q*3+1,1)-dt.timedelta(days=1)
    if end>now.astimezone(TAIPEI).date():raise ValueError('TSMC_FUTURE_STATEMENT_PERIOD')
    existing=validate_archive(root,last_quarter,now.isoformat())
    path=root/MANIFEST
    m=json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(
        schema=SCHEMA,issuer='2330',formal_gate_pass=False,original_MOPS_PIT_verified=False,
        full_content_review_complete=False,index_versions=[],documents=[])
    # Do not repeat a full set of HTTP 403s every time GitHub pushes a new
    # commit. The prior immutable receipts remain authoritative, never a PASS.
    missing=existing['coverage']['missing_quarters']
    denied={item.get('period') for item in m.get('last_fetch_errors',[])
            if isinstance(item,dict)
            and isinstance(item.get('error'),str)
            and ('HTTP Error 403' in item['error'] or 'HTTP 403 Forbidden' in item['error'])}
    if missing and 'DIRECTORY' in denied and set(missing).issubset(denied):
        when=m.get('last_network_attempt_at_utc') or m.get('last_intake_at_utc')
        if when:
            prior=aware(when)
            if prior>now:raise ValueError('TSMC_LAST_NETWORK_ATTEMPT_IN_FUTURE')
            retry_at=prior+HTTP403_RETRY_DELAY
            if now<retry_at:
                result=existing
                result['fetch_errors']=m['last_fetch_errors']
                result['http403_retry_deferred_quarters']=list(missing)
                result['http403_retry_due_at_utc']=retry_at.isoformat()
                return result
    directory_errors=[]
    try:
        raw=fetcher(DIRECTORY,3_000_000);specs=discover(raw,required);index_hash=digest(raw)
    except (OSError,ValueError,EOFError,http.client.IncompleteRead) as exc:
        error=dict(period='DIRECTORY',error=type(exc).__name__+':'+str(exc))
        # The origin's index can be temporarily blocked while its documents
        # remain downloadable. Reuse only an already-provenanced, SHA-verified
        # original issuer index; never guess financial-report URLs or permit
        # an unrelated mirror to establish issuer provenance.
        cached=[]
        for entry in m.get('index_versions',[]):
            if aware(entry['captured_at_utc'])>now:continue
            data=safe(root,entry['archive_path']).read_bytes()
            if digest(data)!=entry['sha256']:
                raise ValueError('TSMC_CACHED_INDEX_HASH_MISMATCH')
            spec=discover(data,required)
            if spec:cached.append((len(spec),entry['captured_at_utc'],entry['sha256'],data,spec))
        if cached:
            _,_,index_hash,raw,specs=max(cached,key=lambda x:(x[0],x[1]))
            error['recovery']='SHA_VERIFIED_ARCHIVED_ISSUER_INDEX'
            directory_errors.append(error)
        else:
            m['last_intake_at_utc']=clock().isoformat();m['last_requested_window_end']=last_quarter
            m['last_network_attempt_at_utc']=clock().isoformat()
            m['last_fetch_errors']=[error]
            atomic_json(path,m)
            result=validate_archive(root,last_quarter,clock().isoformat());result['fetch_errors']=m['last_fetch_errors']
            return result
    rel=f'{FOLDER}/index_{index_hash}.html';store_bytes(root/rel,raw)
    if not any(x['sha256']==index_hash for x in m['index_versions']):
        m['index_versions'].append(dict(source_url=DIRECTORY,sha256=index_hash,archive_path=rel,captured_at_utc=clock().isoformat()))
    pending=[s for s in specs.values() if not any(d['period']==s['period'] and d['source_url']==s['source_url'] for d in m['documents'])]
    errors=list(directory_errors);batch_bytes=0
    # Network reads are independent; publication of originals and receipts is ordered.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures=[(spec,pool.submit(fetcher,spec['source_url'],MAX_PDF)) for spec in pending]
        for spec,future in futures:
            try:
                body=future.result();identity=pdf_identity(body,spec['period']);batch_bytes+=len(body)
                if batch_bytes>MAX_BATCH:raise ValueError('TSMC_SOURCE_BATCH_SIZE_LIMIT')
                h=digest(body);rel=f"{FOLDER}/{spec['period']}_{h[:20]}.pdf";store_bytes(root/rel,body)
                m['documents'].append(dict(**spec,sha256=h,bytes=len(body),archive_path=rel,
                    index_sha256=index_hash,captured_at_utc=clock().isoformat(),pdf_identity=identity,formal_gate_pass=False))
                print('TSMC_ORIGINAL_CAPTURED',spec['period'],identity['page_count'],len(body),flush=True)
            except (OSError,ValueError,RuntimeError,EOFError,http.client.IncompleteRead) as exc:
                errors.append(dict(period=spec['period'],error=type(exc).__name__+':'+str(exc)))
    m['last_intake_at_utc']=clock().isoformat();m['last_requested_window_end']=last_quarter
    m['last_network_attempt_at_utc']=clock().isoformat()
    m['last_fetch_errors']=errors
    atomic_json(path,m)
    result=validate_archive(root,last_quarter,clock().isoformat())
    result['fetch_errors']=errors
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',default='tw-market-data');p.add_argument('--last-quarter')
    a=p.parse_args();root=Path(a.data_root)
    last=a.last_quarter or json.loads((root/'fundamentals/latest_scan.json').read_text())['last_eligible_quarter']
    result=collect(root,last)
    report={k:result[k] for k in ('issuer','records','coverage','fetch_errors','formal_pass_count')}
    # A deferred HTTP 403 is not a fresh fetch failure. Publish the bounded
    # retry state explicitly so downstream triage can distinguish the two.
    report['http403_retry_deferred_quarters']=result.get('http403_retry_deferred_quarters',[])
    report['http403_retry_due_at_utc']=result.get('http403_retry_due_at_utc')
    report['source_window_end']=last
    report['checked_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    report['documents']=[{k:d[k] for k in ('period','title','source_url','archive_path','sha256','bytes','captured_at_utc','pdf_identity')} for d in result['documents']]
    report['all_13_formal_gates_unchanged']=True
    atomic_json(root/'rankings/tsmc_original_statements_intake.json',report)
    lines=['# 2330 台積電完整財報原件收集進度','',
        f"原件視窗：{result['coverage']['required_quarters'][0]} 至 {last}；檢查時間：{report['checked_at_utc']}。",'',
        f"官方目錄連結及雜湊已覆核：{len(result['coverage']['found_quarters'])}/8 季；"
        f"原生文字封面與目錄辨識：{len(result['coverage']['native_cover_identity_verified_quarters'])}/8 季。",'',
        '此處8/8只代表官方目錄列示的原始PDF已封存；掃描頁、會計數值、完整附註、會計師範圍及公告PIT仍待覆核。',
        '2026-Q3簡明自結／法說附件是不同來源，不能替代該季完整財報。13項正式品質門檻不變。','',
        '|資料期|頁數|封面／目錄機器辨識|SHA-256|','|---|---:|---|---|']
    for d in sorted(result['documents'],key=lambda x:(x['period'],x['captured_at_utc'])):
        state='已辨識；全文待核' if d['pdf_identity']['pdf_cover_issuer_and_period_verified'] else '掃描影像；待OCR／視覺覆核'
        lines.append(f"|{d['period']}|{d['pdf_identity']['page_count']}|{state}|{d['sha256']}|")
    if result['coverage']['missing_quarters']:
        lines+=['','缺少原件：'+', '.join(result['coverage']['missing_quarters'])]
    if result['fetch_errors']:
        lines+=['','本輪來源錯誤（包含保留的上一輪403）：']+[f"- {e['period']}：{e['error']}" for e in result['fetch_errors']]
    if report['http403_retry_deferred_quarters']:
        lines += ['','本次 HTTP 403 有界重試保護：暫停重試 '+
                  ', '.join(report['http403_retry_deferred_quarters'])+
                  '；下一次允許重新嘗試時間 '+str(report['http403_retry_due_at_utc'])+
                  '。未進行網路重試，不代表檔案已下載或財報已核閱。']
    from scripts.tw_v880_run import atomic
    atomic(root/'rankings/tsmc_original_statements_intake.md','\n'.join(lines)+'\n')
    print(json.dumps({k:result[k] for k in ('issuer','records','coverage','fetch_errors','formal_pass_count')},ensure_ascii=False))


if __name__=='__main__':main()
