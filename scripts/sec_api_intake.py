#!/usr/bin/env python3
"""Official SEC machine API originals, distinct from full submission archives."""
import argparse
import datetime as dt
import gzip
import json
import re
from pathlib import Path

try:
    from scripts.sec_pit_intake import aware,digest,fetch,require,safe
except ModuleNotFoundError:
    from sec_pit_intake import aware,digest,fetch,require,safe

FOLDER='evidence/v880/regulatory_submissions/api'


def url(cik,kind):
    require(isinstance(cik,str) and re.fullmatch(r'\d{1,10}',cik),'SEC_API_CIK_INVALID')
    padded=f'{int(cik):010}'
    require(kind in ('submissions','companyfacts'),'SEC_API_KIND_INVALID')
    return (f'https://data.sec.gov/submissions/CIK{padded}.json' if kind=='submissions'
            else f'https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json')


def summarize(raw,cik,kind):
    data=json.loads(raw.decode('utf-8-sig'))
    require(type(data.get('cik')) in (int,str) and int(data['cik'])==int(cik),'SEC_API_ISSUER_MISMATCH')
    if kind=='submissions':
        recent=data.get('filings',{}).get('recent',{})
        require(isinstance(recent.get('accessionNumber'),list) and recent['accessionNumber'],
                'SEC_API_FILING_ARRAYS_MISSING')
        required=('accessionNumber','filingDate','reportDate','acceptanceDateTime','form','primaryDocument')
        n=len(recent['accessionNumber'])
        require(all(isinstance(recent.get(k),list) and len(recent[k])==n for k in required),
                'SEC_API_FILING_ARRAY_LENGTH_MISMATCH')
        require(len(set(recent['accessionNumber']))==n,'SEC_API_DUPLICATE_ACCESSION')
        return dict(cik=str(int(cik)),entity_name=data.get('name'),filing_records=n,
                    historical_segment_files=len(data['filings'].get('files',[])))
    facts=data.get('facts');require(isinstance(facts,dict) and facts,'SEC_API_FACTS_MISSING')
    concepts=observations=0;filed=[]
    for namespace,tags in facts.items():
        require(isinstance(tags,dict),'SEC_API_FACT_NAMESPACE_INVALID')
        for tag,item in tags.items():
            require(isinstance(item.get('units'),dict),'SEC_API_FACT_UNITS_MISSING');concepts+=1
            for unit,values in item['units'].items():
                require(isinstance(values,list),'SEC_API_FACT_VALUES_INVALID')
                observations+=len(values)
                for row in values:
                    if row.get('filed'):filed.append(dt.date.fromisoformat(row['filed']).isoformat())
    require(observations>0,'SEC_API_EMPTY_FACTS')
    return dict(cik=str(int(cik)),entity_name=data.get('entityName'),concepts=concepts,
                fact_observations=observations,first_filed=min(filed) if filed else None,
                last_filed=max(filed) if filed else None)


def capture(root,cik,kind,fetcher=fetch):
    root=Path(root);endpoint=url(cik,kind)
    raw=fetcher(endpoint);summary=summarize(raw,cik,kind);identity=digest(raw)
    folder=root/FOLDER/str(int(cik))/kind;folder.mkdir(parents=True,exist_ok=True)
    original=folder/(identity+'.json.gz');receipt=folder/(identity+'.receipt.json')
    if receipt.exists():
        record=json.loads(receipt.read_bytes())
        old=gzip.decompress(safe(root,record['archive_path']).read_bytes())
        require(record.get('schema')=='SEC_API_ORIGINAL_V1' and record.get('source_url')==endpoint
                and record.get('cik')==str(int(cik)) and record.get('kind')==kind
                and record.get('raw_sha256')==identity and record.get('bytes')==len(old)
                and digest(old)==identity and summarize(old,cik,kind)==record['summary'],'SEC_API_CACHE_CORRUPT')
        aware(record['first_captured_at_utc'])
        return record
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    record=dict(schema='SEC_API_ORIGINAL_V1',source_url=endpoint,kind=kind,cik=str(int(cik)),
        raw_sha256=identity,bytes=len(raw),first_captured_at_utc=now,summary=summary,
        archive_path=original.relative_to(root).as_posix(),
        is_official_api_response_not_original_filing_document=True,
        full_revision_history_and_historical_universe_verified=False,
        financial_PIT_admitted=False,formal_Aplus_added=0)
    require(not original.exists(),'SEC_API_HALF_WRITTEN_ARCHIVE')
    original.write_bytes(gzip.compress(raw,mtime=0))
    with receipt.open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False,indent=2);f.write('\n')
    return record


def run(root,ciks,fetcher=fetch):
    require(0<len(ciks)<=3 and len(set(ciks))==len(ciks),'SEC_API_UNBOUNDED_OR_DUPLICATE_CIKS')
    records,errors=[],[]
    for cik in ciks:
        for kind in ('submissions','companyfacts'):
            try:records.append(capture(root,cik,kind,fetcher))
            except (ValueError,KeyError,TypeError,OSError,EOFError) as e:errors.append(dict(cik=cik,kind=kind,reason=str(e)))
    return dict(schema='SEC_API_INTAKE_STATUS_V1',observed_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        status='SOURCE_ERRORS' if errors else 'API_ORIGINALS_CAPTURED',
        captured_api_responses=len(records),records=records,errors=errors,
        full_original_submission_documents_captured=0,calibrated_returns_created=0,formal_Aplus_added=0)


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='tw-market-data');p.add_argument('--cik',nargs='+',default=['1046179']);a=p.parse_args()
    r=run(Path(a.root),a.cik);out=Path(a.root)/'rankings';out.mkdir(parents=True,exist_ok=True)
    (out/'latest_sec_api_intake.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(r,ensure_ascii=False));return int(bool(r['errors']))


if __name__=='__main__':raise SystemExit(main())
