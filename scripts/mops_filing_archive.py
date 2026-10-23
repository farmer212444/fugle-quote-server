#!/usr/bin/env python3
"""Archive MOPS filing bytes and their official upload records, without issuing gates.

The document server's generated PDF URL contains retrieval time, not filing time.
The index explicitly reports only the most recent correction. Amended documents
need a separate version-history adapter and are never admitted by this adapter.
"""
import argparse
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request

PACKAGE_ROOT=Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:sys.path.insert(0,str(PACKAGE_ROOT))
from scripts.history_archive import canonical,digest,safe_path
from scripts.v8a0_9802_pdf_outline import compact,period_tokens

BASE='https://doc.twse.com.tw/server-java/t57sb01'
TAIPEI=dt.timezone(dt.timedelta(hours=8))
SCHEMA='MOPS_OFFICIAL_UPLOAD_DOCUMENT_VERSION_V1'
HEADERS=('證券代號','資料年度','資料類型','結案類型','性質','資料細節說明',
         '備註','電子檔案','檔案大小','上傳日期','財務報告更(補)正')
ISSUERS={'9802':('鈺齊','fulgentsun'),'6206':('飛捷','flytech')}
MAX_PDF_BYTES=8_000_000


def require(condition,reason):
    if not condition:raise ValueError(reason)


def clock():return dt.datetime.now(dt.timezone.utc).isoformat()


def text_html(raw):
    # Both encodings occur on official document-server responses. Do not replace
    # undecodable characters in a company, filing date or correction indicator.
    if re.search(br'charset\s*=\s*["\']?\s*(?:big5|cp950)',raw[:1000],re.I):
        return raw.decode('cp950')
    try:return raw.decode('utf-8-sig')
    except UnicodeDecodeError:return raw.decode('cp950')


class Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        elif tag in ('td','th') and self.row is not None:self.cell=dict(text=[],links=[])
        elif tag=='a' and self.cell is not None:
            self.cell['links'].append(dict(attrs).get('href',''))
    def handle_data(self,data):
        if self.cell is not None:self.cell['text'].append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.cell['text']=' '.join(''.join(self.cell['text']).split())
            self.row.append(self.cell);self.cell=None
        elif tag=='tr' and self.row is not None:
            self.rows.append(self.row);self.row=None;self.cell=None


def index_url(code,year):
    require(re.fullmatch(r'\d{4}',str(code)) and 2000<=year<=2100,'MOPS_INVALID_QUERY_IDENTITY')
    return BASE+'?'+urllib.parse.urlencode(dict(step=1,colorchg=1,co_id=code,
                                               year=year-1911,seamon='',mtype='A'))


def upload_timestamp(value):
    match=re.fullmatch(r'(\d{3,4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})',value)
    require(match is not None,'MOPS_EXACT_UPLOAD_TIMESTAMP_REQUIRED')
    values=list(map(int,match.groups()));values[0]+=1911 if values[0]<1911 else 0
    return dt.datetime(*values,tzinfo=TAIPEI).isoformat()


def parse_index(raw,code,year):
    parser=Rows();parser.feed(text_html(raw))
    heading=None;records=[];seen=set()
    for cells in parser.rows:
        labels=tuple(c['text'] for c in cells)
        if labels==HEADERS:heading=labels;continue
        if len(cells)!=len(HEADERS) or not re.fullmatch(r'\d{4}',labels[0]):continue
        require(heading==HEADERS,'MOPS_INDEX_HEADERS_NOT_CONFIRMED')
        require(labels[0]==code,'MOPS_INDEX_OTHER_ISSUER')
        match=re.fullmatch(r'(\d{3,4})\s*年\s*第([一二三四1-4])季',labels[1])
        require(match is not None,'MOPS_INDEX_ACCOUNTING_PERIOD_MISSING')
        filing_year=int(match[1]);filing_year+=1911 if filing_year<1911 else 0
        require(filing_year==year,'MOPS_INDEX_OTHER_ACCOUNTING_YEAR')
        quarter=int(match[2]) if match[2].isdigit() else '一二三四'.index(match[2])+1
        require(labels[2]=='財務報告書','MOPS_INDEX_OTHER_DOCUMENT_KIND')
        require(len(cells[7]['links'])==1,'MOPS_AMBIGUOUS_DOCUMENT_LINK')
        link=re.fullmatch(r'''javascript:readfile2?\(["']A["'],["'](\d{4})["'],["']([0-9A-Za-z_.-]+\.pdf)["']\);?''',cells[7]['links'][0])
        require(link is not None and link[1]==code,'MOPS_INDEX_LINK_ISSUER_MISMATCH')
        filename=link[2]
        require('..' not in filename and filename.startswith(f'{year}0{quarter}_{code}_'),
                'MOPS_INDEX_FILE_PERIOD_MISMATCH')
        size=labels[8].replace(',','')
        require(size.isdigit() and 5000<=int(size)<=MAX_PDF_BYTES,'MOPS_INDEX_INVALID_FILE_SIZE')
        record=dict(code=code,financial_period=f'{year}-Q{quarter}',file_name=filename,
                    description=labels[5],notes=labels[6],bytes=int(size),
                    official_upload_at=upload_timestamp(labels[9]),
                    latest_reported_correction=labels[10],
                    official_index_reports_only_latest_correction=True)
        identity=(filename,record['official_upload_at'])
        require(identity not in seen,'MOPS_DUPLICATE_FILING_VERSION')
        seen.add(identity);records.append(record)
    require(heading==HEADERS and records,'MOPS_NO_VALID_OFFICIAL_FILING_INDEX')
    return records


def official_url(url):
    parsed=urllib.parse.urlsplit(url)
    return (parsed.scheme=='https' and parsed.netloc=='doc.twse.com.tw'
            and not parsed.fragment and not parsed.username and not parsed.password
            and (parsed.path=='/server-java/t57sb01' or
                 re.fullmatch(r'/pdf/[0-9A-Za-z_.-]+\.pdf',parsed.path) is not None)
            and '..' not in parsed.path)


def fetch(url):
    require(official_url(url),'MOPS_NONOFFICIAL_DOCUMENT_URL')
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (public financial filing archive research)'})
    with urllib.request.urlopen(request,timeout=20) as response:
        require(response.status==200 and official_url(response.url),'MOPS_UNOFFICIAL_REDIRECT_OR_STATUS')
        pieces=[];size=0;started=time.monotonic()
        deadline=90 if urllib.parse.urlsplit(url).path.endswith('.pdf') else 20
        while True:
            require(time.monotonic()-started<deadline,'MOPS_RESPONSE_TOTAL_READ_DEADLINE')
            part=response.read1(min(65536,MAX_PDF_BYTES+1-size))
            if not part:break
            pieces.append(part);size+=len(part)
            require(size<=MAX_PDF_BYTES,'MOPS_EMPTY_OR_OVERSIZE_RESPONSE')
        raw=b''.join(pieces)
    require(0<len(raw)<=MAX_PDF_BYTES,'MOPS_EMPTY_OR_OVERSIZE_RESPONSE')
    return raw


def resolver_url(row):
    return BASE+'?'+urllib.parse.urlencode(dict(step=9,kind='A',co_id=row['code'],filename=row['file_name']))


def parse_resolver(raw,row):
    class Links(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.links=[];self.active=None
        def handle_starttag(self,tag,attrs):
            if tag=='a':self.active=[dict(attrs).get('href',''),[]]
        def handle_data(self,data):
            if self.active is not None:self.active[1].append(data)
        def handle_endtag(self,tag):
            if tag=='a' and self.active is not None:
                self.links.append((self.active[0],''.join(self.active[1]).strip()));self.active=None
    parser=Links();parser.feed(text_html(raw))
    matches=[urllib.parse.urljoin(BASE,url) for url,label in parser.links if label==row['file_name']]
    require(len(matches)==1 and official_url(matches[0]),'MOPS_RESOLVER_DOCUMENT_LINK_NOT_CONFIRMED')
    path=urllib.parse.urlsplit(matches[0]).path
    require(path.startswith('/pdf/'+row['file_name'][:-4]+'_'),'MOPS_RESOLVER_OTHER_DOCUMENT')
    return matches[0]


def store_original(root,relative,raw):
    path=safe_path(root,relative)
    if path.exists():require(path.read_bytes()==raw,'MOPS_IMMUTABLE_ORIGINAL_CONFLICT')
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)
    return dict(path=relative,sha256=digest(raw),bytes=len(raw))


def read_original(root,reference):
    raw=safe_path(root,reference['path']).read_bytes()
    require(len(raw)==reference['bytes'] and digest(raw)==reference['sha256'],'MOPS_ORIGINAL_HASH_OR_SIZE_MISMATCH')
    return raw


def normalize_printed_years(text):
    # KPMG's Flytech covers print ROC years as individual Chinese digits,
    # e.g. 民國一一五年及一一四年. This is not a general numeral guesser.
    digits=str.maketrans('〇零○一二三四五六七八九','000123456789')
    return re.sub(r'[〇零○一二三四五六七八九]{3,4}(?=年)',
                  lambda match:match[0].translate(digits),text)


def native_identity(raw,row):
    import pymupdf
    doc=pymupdf.open(stream=raw,filetype='pdf')
    try:
        require(not doc.needs_pass and 1<=len(doc)<=250,'MOPS_PDF_INVALID_OR_ENCRYPTED')
        cover=normalize_printed_years(compact(doc[0].get_text('text')))
        first=''.join(normalize_printed_years(compact(doc[i].get_text('text')))
                      for i in range(min(12,len(doc))))
        require(any(compact(marker) in cover for marker in ISSUERS.get(row['code'],(row['code'],))),
                'MOPS_PDF_COVER_ISSUER_MISSING')
        year,quarter=map(int,row['financial_period'].split('-Q'))
        require(str(year) in cover or f'{year-1911}年' in cover,'MOPS_PDF_COVER_YEAR_MISSING')
        cover_years=[int(y)+1911 if int(y)<1911 else int(y)
                     for y in re.findall(r'(?<!\d)(\d{3,4})(?=年)',cover)]
        require(cover_years and max(cover_years)==year,'MOPS_PDF_COVER_CURRENT_YEAR_MISMATCH')
        month=quarter*3;day=31 if quarter in (1,4) else 30
        endings=(*period_tokens(row['financial_period']),f'{year-1911}.{month}.{day}',
                 f'{year-1911}.{month:02d}.{day:02d}')
        require(any(compact(token) in first for token in endings),
                'MOPS_PDF_ACCOUNTING_END_DATE_MISSING')
        require('合併' in cover and ('財務報告' in cover or '財務報表' in cover),
                'MOPS_PDF_NOT_CONSOLIDATED_FINANCIAL_REPORT')
        return dict(page_count=len(doc),issuer_and_period_native_text_preflight=True,
                    financial_numbers_and_notes_substantively_reviewed=False)
    finally:doc.close()


def verify_version(root,reference,reader=native_identity):
    receipt=json.loads(read_original(root,reference))
    require(receipt['schema']==SCHEMA and receipt['formal_gate_pass'] is False,'MOPS_VERSION_SCHEMA_OR_FALSE_GATE')
    row=receipt['index_row'];code=row['code'];year=int(row['financial_period'][:4])
    require(receipt['index_url']==index_url(code,year),'MOPS_INDEX_QUERY_IDENTITY_MISMATCH')
    index_raw=read_original(root,receipt['index_original'])
    matches=[r for r in parse_index(index_raw,code,year) if r==row]
    require(len(matches)==1,'MOPS_FILING_NOT_BOUND_TO_ORIGINAL_INDEX')
    resolved=parse_resolver(read_original(root,receipt['resolver_original']),row)
    require(resolved==receipt['resolved_pdf_url'],'MOPS_RESOLVED_PDF_LINK_CHANGED')
    require(receipt['resolver_url']==resolver_url(row),'MOPS_RESOLVER_QUERY_IDENTITY_MISMATCH')
    raw=read_original(root,receipt['pdf_original'])
    require(len(raw)==row['bytes'] and raw.startswith(b'%PDF-') and b'%%EOF' in raw[-4096:],
            'MOPS_PDF_INDEX_SIZE_OR_FORMAT_MISMATCH')
    checked=reader(raw,row)
    require(checked==receipt['native_preflight'],'MOPS_PDF_PREFLIGHT_CHANGED')
    captured=dt.datetime.fromisoformat(receipt['captured_at_utc'])
    require(captured.tzinfo is not None,'MOPS_CAPTURE_TIMEZONE_REQUIRED')
    require(dt.datetime.fromisoformat(row['official_upload_at'])<=captured,'MOPS_UPLOAD_AFTER_CAPTURE')
    require(receipt['official_upload_timestamp_verified'] is True,'MOPS_UPLOAD_CLOCK_NOT_VERIFIED')
    require(receipt['historical_revision_chain_independently_reviewed'] is False,
            'MOPS_FALSE_REVISION_HISTORY_ATTESTATION')
    return receipt


def audit_archive(root,reader=native_identity,codes=None):
    versions=[];errors=[]
    base=Path(root)/'filings/mops'
    paths=(base.glob('[0-9]*/*/receipt.json') if codes is None else
           (path for code in codes for path in (base/str(code)).glob('*/receipt.json')))
    for path in sorted(paths):
        try:
            ref=dict(path=path.relative_to(root).as_posix(),sha256=digest(path.read_bytes()),bytes=path.stat().st_size)
            item=verify_version(root,ref,reader)
            versions.append(dict(reference=ref,**item))
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,UnicodeError) as exc:
            errors.append(dict(path=path.relative_to(root).as_posix(),reason=str(exc)))
    return dict(versions=versions,source_rejections=errors)


def quarters(last,count=8):
    y,q=map(int,last.split('-Q'));end=y*4+q-1
    return [f'{i//4}-Q{i%4+1}' for i in range(end-count+1,end+1)]


def collect(root,codes=('6206','9802'),last='2026-Q2',max_documents=4,source=fetch,reader=native_identity,pause=.25):
    root=Path(root).resolve();wanted=quarters(last);years=sorted({int(p[:4]) for p in wanted})
    archive=audit_archive(root,reader);captured=[];errors=list(archive['source_rejections']);indices=[];requests=0
    existing={digest(canonical(v['index_row'])):v
              for v in archive['versions']}
    candidates=[];restricted=False
    retry_path=root/'filings/mops/retry_queue.json'
    retries=json.loads(retry_path.read_text()) if retry_path.exists() else {}
    for code in codes:
        if restricted:break
        for year in years:
            try:
                url=index_url(code,year);raw=source(url);rows=parse_index(raw,code,year)
                reference=store_original(root,f'filings/mops/indices/{code}/{year}/{digest(raw)}.html',raw)
                indices.append(dict(code=code,year=year,url=url,original=reference,rows=rows))
                for row in rows:
                    if (row['financial_period'] in wanted and row['description']=='IFRSs合併財報'
                            and re.fullmatch(fr"{year}0[1-4]_{code}_AI1(?:_[0-9_]+)?\.pdf",row['file_name'])):
                        candidates.append((row,url,reference))
            except (ValueError,KeyError,TypeError,OSError,RuntimeError,UnicodeError) as exc:
                errors.append(dict(code=code,year=year,reason=str(exc)))
                if getattr(exc,'code',None) in (403,429) or 'UNOFFICIAL_REDIRECT' in str(exc):
                    restricted=True;break
            if pause:time.sleep(pause)
    # Round-robin periods: both focus issuers receive useful coverage each run.
    candidates.sort(key=lambda item:(item[0]['financial_period'],item[0]['code']),reverse=True)
    candidates.sort(key=lambda item:retries.get(digest(canonical(item[0])),{}).get('attempts',0))
    for row,url,index_ref in candidates:
        if restricted:break
        key=digest(canonical(row))
        if key in existing:continue
        if requests>=max_documents:break
        requests+=1
        try:
            locator=resolver_url(row);resolver=source(locator);pdf_url=parse_resolver(resolver,row);pdf=source(pdf_url)
            require(len(pdf)==row['bytes'] and pdf.startswith(b'%PDF-') and b'%%EOF' in pdf[-4096:],
                    'MOPS_PDF_INDEX_SIZE_OR_FORMAT_MISMATCH')
            identity=digest(canonical(dict(row=row,pdf_sha256=digest(pdf))))[:32]
            folder=f"filings/mops/{row['code']}/{identity}"
            pdf_ref=store_original(root,f"filings/mops/originals/{row['code']}/{digest(pdf)}.pdf",pdf)
            resolver_ref=store_original(root,folder+'/resolver.html',resolver)
            preflight=reader(pdf,row)
            receipt=dict(schema=SCHEMA,index_row=row,index_url=url,index_original=index_ref,
                resolver_url=locator,resolver_original=resolver_ref,resolved_pdf_url=pdf_url,pdf_original=pdf_ref,
                captured_at_utc=clock(),native_preflight=preflight,official_upload_timestamp_verified=True,
                generated_pdf_url_time_is_not_filing_time=True,
                historical_revision_chain_independently_reviewed=False,formal_gate_pass=False,
                negative_correction_indicator_is_current_official_index_status_not_human_signoff=True)
            ref=store_original(root,folder+'/receipt.json',json.dumps(receipt,ensure_ascii=False,indent=2).encode()+b'\n')
            verify_version(root,ref,reader);captured.append(ref)
            retries.pop(key,None)
            print(json.dumps(dict(code=row['code'],period=row['financial_period'],status='ORIGINAL_AND_UPLOAD_CLOCK_VERIFIED')),flush=True)
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,UnicodeError) as exc:
            errors.append(dict(code=row['code'],financial_period=row['financial_period'],reason=str(exc)))
            retries[key]=dict(index_row=row,attempts=retries.get(key,{}).get('attempts',0)+1,
                              last_attempt_utc=clock(),reason=str(exc),status='RETRY_NOT_ADMITTED')
            print(json.dumps(errors[-1],ensure_ascii=False),flush=True)
            if getattr(exc,'code',None) in (403,429) or 'UNOFFICIAL_REDIRECT' in str(exc):
                restricted=True;break
        if pause:time.sleep(pause)
    report=dict(schema='MOPS_FILING_INTAKE_PROGRESS_V1',observed_at_utc=clock(),requested_quarters=wanted,
        requested_issuers=list(codes),document_attempts=requests,new_document_versions=len(captured),
        verified_existing_versions=len(archive['versions']),official_index_snapshots=indices,errors=errors,
        source_access_restricted=restricted,
        formal_gate_passes_created=0,stock_return_backtest_completed=False)
    target=root/'filings/mops/latest_collection.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    retry_path.write_text(json.dumps(retries,ensure_ascii=False,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-root',default='tw-market-data')
    parser.add_argument('--max-documents',type=int,default=4);parser.add_argument('--last-quarter')
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args();require(1<=args.max_documents<=20,'MOPS_INVALID_DOCUMENT_BUDGET')
    root=Path(args.data_root)
    if args.verify_only:
        result=audit_archive(root);print(json.dumps(dict(verified_versions=len(result['versions']),errors=result['source_rejections'])))
        if result['source_rejections']:raise SystemExit(1)
    else:
        last=args.last_quarter or json.loads((root/'fundamentals/latest_scan.json').read_text())['last_eligible_quarter']
        result=collect(root,last=last,max_documents=args.max_documents)
        print(json.dumps({k:result[k] for k in ('document_attempts','new_document_versions','verified_existing_versions','errors')},ensure_ascii=False))
        if not result['new_document_versions'] and not result['verified_existing_versions']:
            raise SystemExit('MOPS_NO_VERIFIED_FILING_PROGRESS')


if __name__=='__main__':main()
