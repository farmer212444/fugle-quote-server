#!/usr/bin/env python3
"""Archive official TAIEX total-return closes; retrieval time is never backdated."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880.evidence import timestamp
from tw_model_v880.portfolio import finite
from tw_model_v880.validation_io import source
from scripts.run_research_pipeline import atomic_json

ENDPOINT='https://www.twse.com.tw/rwd/zh/TAIEX/MFI94U'
TAIPEI=dt.timezone(dt.timedelta(hours=8))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def month_url(month):
    if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',month):
        raise ValueError('INVALID_BENCHMARK_MONTH')
    return ENDPOINT+'?'+urllib.parse.urlencode(dict(date=month.replace('-','')+'01',response='json'))


def close_at(day):
    dt.date.fromisoformat(day)
    return day+'T13:30:00+08:00'


def parse(raw,month):
    month_url(month)
    doc=json.loads(raw.decode('utf-8-sig'))
    title=doc.get('title','');y,m=map(int,month.split('-'))
    if (doc.get('stat')!='OK' or f'{y-1911}年{m:02d}月' not in title.replace(' ','')
            or '發行量加權股價報酬指數' not in title):
        raise ValueError('WRONG_BENCHMARK_IDENTITY_OR_MONTH')
    fields=[''.join(str(x).split()) for x in doc['fields']]
    if fields!=['日期','發行量加權股價報酬指數']:
        raise ValueError('WRONG_BENCHMARK_FIELDS')
    rows=[]
    for row in doc['data']:
        if len(row)!=2:raise ValueError('WRONG_BENCHMARK_ROW_SHAPE')
        parts=list(map(int,row[0].split('/')))
        day=dt.date(parts[0]+1911,parts[1],parts[2]).isoformat()
        level=float(str(row[1]).replace(',',''))
        if day[:7]!=month or not finite(level,positive=True):
            raise ValueError('INVALID_BENCHMARK_DATE_OR_LEVEL')
        rows.append(dict(date=day,close_at=close_at(day),level=level))
    dates=[r['date'] for r in rows]
    if not rows or len(rows)>31 or dates!=sorted(set(dates)):
        raise ValueError('EMPTY_DUPLICATE_OR_UNORDERED_BENCHMARK_DATES')
    return rows


def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (public benchmark research)',
                                          'Accept':'application/json','Referer':'https://www.twse.com.tw/'})
    with urllib.request.urlopen(req,timeout=18) as response:
        if response.status!=200 or urllib.parse.urlparse(response.url).hostname!='www.twse.com.tw':
            raise ValueError('UNEXPECTED_BENCHMARK_SOURCE_REDIRECT')
        raw=response.read(1000001)
    if not 100<len(raw)<=1000000:raise ValueError('INVALID_BENCHMARK_RESPONSE_SIZE')
    return raw


def archive(root,month,raw,captured_at):
    root=Path(root).resolve();rows=parse(raw,month);captured=timestamp(captured_at)
    if any(timestamp(r['close_at'])>captured for r in rows):
        raise ValueError('BENCHMARK_CLOSE_AFTER_SOURCE_CAPTURE')
    folder=root/'benchmarks/TAIEX_TR/originals'/month
    sha=digest(raw);packed_path=folder/(sha+'.json.gz');receipt_path=folder/(sha+'.json')
    packed=gzip.compress(raw,mtime=0)
    folder.mkdir(parents=True,exist_ok=True)
    receipt=dict(schema='OFFICIAL_TAIEX_TR_SOURCE_V1',benchmark_id='TAIEX_TR',month=month,
                 source_url=month_url(month),captured_at=captured_at,original_sha256=sha,
                 archive_path=packed_path.relative_to(root).as_posix(),bytes=len(raw),rows=rows)
    if receipt_path.exists():
        prior=json.loads(receipt_path.read_text())
        if (prior.get('rows')!=rows or prior.get('original_sha256')!=sha
                or not packed_path.exists() or packed_path.read_bytes()!=packed):
            raise ValueError('BENCHMARK_ARCHIVE_IMMUTABILITY_CONFLICT')
        receipt=prior
    else:
        if packed_path.exists() and packed_path.read_bytes()!=packed:
            raise ValueError('BENCHMARK_ARCHIVE_IMMUTABILITY_CONFLICT')
        packed_path.write_bytes(packed);atomic_json(receipt_path,receipt)
    reference=dict(path=receipt_path.relative_to(root).as_posix(),sha256=digest(receipt_path.read_bytes()))
    atomic_json(root/'benchmarks/TAIEX_TR/months'/(month+'.json'),reference)
    return reference


def verify(root,reference,asof):
    root=Path(root).resolve();receipt=source(root,reference)
    if (receipt.get('schema')!='OFFICIAL_TAIEX_TR_SOURCE_V1' or receipt.get('benchmark_id')!='TAIEX_TR'
            or receipt.get('source_url')!=month_url(receipt['month'])):
        raise ValueError('BENCHMARK_RECEIPT_IDENTITY_MISMATCH')
    captured=timestamp(receipt['captured_at'])
    if captured>timestamp(asof):raise ValueError('BENCHMARK_SOURCE_CAPTURE_AFTER_ASOF')
    rel=Path(receipt['archive_path']);path=(root/rel).resolve()
    if rel.is_absolute() or '..' in rel.parts or root not in path.parents:
        raise ValueError('UNSAFE_BENCHMARK_ARCHIVE_PATH')
    raw=gzip.decompress(path.read_bytes())
    if len(raw)!=receipt['bytes'] or digest(raw)!=receipt['original_sha256']:
        raise ValueError('BENCHMARK_ORIGINAL_BYTES_MISMATCH')
    rows=parse(raw,receipt['month'])
    if rows!=receipt['rows'] or any(timestamp(r['close_at'])>captured for r in rows):
        raise ValueError('BENCHMARK_NORMALIZED_ROWS_DIFFER_FROM_ORIGINAL')
    return receipt


def load_index(root,asof):
    root=Path(root).resolve();rows={};months={};errors=[]
    for path in sorted((root/'benchmarks/TAIEX_TR/months').glob('*.json')):
        try:
            ref=json.loads(path.read_text());doc=verify(root,ref,asof)
            if path.stem!=doc['month']:raise ValueError('BENCHMARK_POINTER_MONTH_MISMATCH')
            months[path.stem]=ref
            for row in doc['rows']:
                if timestamp(row['close_at'])<=timestamp(asof):
                    if row['date'] in rows:raise ValueError('DUPLICATE_BENCHMARK_SESSION')
                    rows[row['date']]=dict(row,source=ref)
        except (OSError,ValueError,KeyError,TypeError,EOFError) as exc:
            errors.append(dict(path=path.relative_to(root).as_posix(),reason=str(exc)))
    return dict(rows=rows,months=months,errors=errors)


def month_range(first,last):
    y,m=map(int,first[:7].split('-'));out=[]
    while f'{y:04d}-{m:02d}'<=last[:7]:
        out.append(f'{y:04d}-{m:02d}');m+=1
        if m==13:y+=1;m=1
    return out


def refresh(root,months,fetcher=fetch):
    results=[]
    for month in months:
        try:
            raw=fetcher(month_url(month))
            ref=archive(root,month,raw,dt.datetime.now(dt.timezone.utc).isoformat())
            results.append(dict(month=month,status='ARCHIVED',source=ref))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            results.append(dict(month=month,status='SOURCE_UNAVAILABLE',reason=str(exc)))
    atomic_json(Path(root)/'rankings/latest_benchmark_source_refresh.json',dict(results=results))
    return results


def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',default='tw-market-data')
    p.add_argument('--months',nargs='+');args=p.parse_args()
    now=dt.datetime.now(TAIPEI).date();months=args.months
    if months is None:
        months=[];day=now
        for _ in range(4):
            months.append(day.strftime('%Y-%m'));day=day.replace(day=1)-dt.timedelta(days=1)
        months.reverse()
        queue=Path(args.data_root)/'rankings/latest_benchmark_validation.json'
        if queue.exists():
            queued=json.loads(queue.read_text()).get('benchmark_months_required',[])
            # Keep blocked old cohorts on the source queue after calendar rolls.
            months=list(dict.fromkeys(months+queued))[:8]
    if any(month>now.strftime('%Y-%m') for month in months):p.error('Future month forbidden')
    results=refresh(args.data_root,months)
    print(json.dumps(dict(benchmark_id='TAIEX_TR',results=results),ensure_ascii=False))


if __name__=='__main__':main()
