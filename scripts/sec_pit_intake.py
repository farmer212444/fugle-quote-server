#!/usr/bin/env python3
"""Bounded SEC original-submission intake; no prediction or PIT grade is issued."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

FOLDER = 'evidence/v880/regulatory_submissions'
SCHEMA = 'SEC_ORIGINAL_SUBMISSION_V1'
UA = 'TaiwanHistoricalResearch/1.0 (https://github.com/farmer212444/fugle-quote-server)'
MAX_BYTES = 50*1024*1024


def require(ok,reason):
    if not ok:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def aware(raw):
    d=dt.datetime.fromisoformat(raw.replace('Z','+00:00'))
    require(d.tzinfo is not None,'SEC_CAPTURE_TIMEZONE_REQUIRED')
    return d.astimezone(dt.timezone.utc)


def source_url(spec):
    cik,accession=spec.get('cik'),spec.get('accession')
    require(isinstance(cik,str) and re.fullmatch(r'\d{1,10}',cik)
            and isinstance(accession,str) and re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession),
            'SEC_SPEC_IDENTITY_INVALID')
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-","")}/{accession}.txt'


def field(raw,name):
    matches=re.findall(rb'(?m)^[\t ]*'+re.escape(name.encode())+rb':[^\S\r\n]*([^\r\n]+)',raw)
    require(len(matches)==1,'SEC_HEADER_FIELD_MISSING_OR_DUPLICATE_'+name)
    return matches[0].decode('ascii').strip()


def parse(raw,spec):
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_BYTES,'SEC_ORIGINAL_SIZE_INVALID')
    require(raw.lstrip().startswith(b'<SEC-DOCUMENT>') and b'</SEC-HEADER>' in raw,'SEC_NOT_ORIGINAL_SUBMISSION')
    header=raw.split(b'</SEC-HEADER>',1)[0]
    accession=field(header,'ACCESSION NUMBER')
    cik=field(header,'CENTRAL INDEX KEY')
    form=field(header,'CONFORMED SUBMISSION TYPE')
    period=field(header,'CONFORMED PERIOD OF REPORT')
    filed=field(header,'FILED AS OF DATE')
    require(accession==spec['accession'] and int(cik)==int(spec['cik'])
            and form==spec['form'],'SEC_SUBMISSION_IDENTITY_MISMATCH')
    require(field(header,'COMPANY CONFORMED NAME')==spec['conformed_name'],'SEC_FILER_NAME_MISMATCH')
    require(period==spec['report_period'],'SEC_REPORT_PERIOD_MISMATCH')
    dt.datetime.strptime(period,'%Y%m%d');dt.datetime.strptime(filed,'%Y%m%d')
    clocks=re.findall(rb'<ACCEPTANCE-DATETIME>(\d{14})',header)
    require(len(clocks)==1,'SEC_ACCEPTANCE_CLOCK_MISSING_OR_DUPLICATE')
    accepted_local=dt.datetime.strptime(clocks[0].decode(),'%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('America/New_York'))
    documents=[]
    for segment in re.findall(rb'(?ms)^<DOCUMENT>\s*\r?\n(.*?)^</DOCUMENT>\s*$',raw):
        head=segment.split(b'<TEXT>',1)[0]
        def tag(name):
            m=re.findall(rb'(?m)^<'+name.encode()+rb'>([^\r\n]+)',head)
            require(len(m)==1,'SEC_DOCUMENT_TAG_INVALID_'+name)
            return m[0].decode('ascii').strip()
        filename=tag('FILENAME');sequence=tag('SEQUENCE')
        require(filename and '/' not in filename and '\\' not in filename
                and filename not in ('.','..') and sequence.isdigit(),'SEC_DOCUMENT_IDENTITY_INVALID')
        documents.append(dict(filename=filename,sequence=int(sequence),type=tag('TYPE'),
                              segment_sha256=digest(segment),segment_bytes=len(segment)))
    require(len(documents)==int(field(header,'PUBLIC DOCUMENT COUNT')) and documents,
            'SEC_SUBMISSION_DOCUMENT_COUNT_MISMATCH')
    require(len({d['filename'] for d in documents})==len(documents)
            and len({d['sequence'] for d in documents})==len(documents),'SEC_DUPLICATE_DOCUMENT')
    require(any(d['type']==form for d in documents),'SEC_PRIMARY_DOCUMENT_MISSING')
    return dict(cik=str(int(cik)),accession=accession,form=form,company_conformed_name=spec['conformed_name'],
                report_period=period,filed_on=dt.datetime.strptime(filed,'%Y%m%d').date().isoformat(),
                accepted_at_eastern=accepted_local.isoformat(),accepted_at_utc=accepted_local.astimezone(dt.timezone.utc).isoformat(),
                documents=documents,document_count=len(documents))


def safe(root,relative):
    root=Path(root).resolve();p=Path(relative);target=(root/p).resolve()
    require(not p.is_absolute() and '..' not in p.parts and root in target.parents,'SEC_ARCHIVE_UNSAFE_PATH')
    return target


def verify(root,receipt):
    root=Path(root).resolve()
    raw=gzip.decompress(safe(root,receipt['archive_path']).read_bytes())
    require(receipt.get('schema')==SCHEMA and receipt['raw_sha256']==digest(raw)
            and receipt['bytes']==len(raw),'SEC_ARCHIVE_BYTES_MISMATCH')
    require(receipt['source_url']==source_url(receipt['requested_spec']),'SEC_ARCHIVE_SOURCE_MISMATCH')
    observed=parse(raw,receipt['requested_spec'])
    require(observed==receipt['parsed'],'SEC_ARCHIVE_PARSED_METADATA_MISMATCH')
    require(aware(observed['accepted_at_utc'])<=aware(receipt['first_captured_at_utc']),
            'SEC_ACCEPTANCE_AFTER_CAPTURE')
    return observed


def archive(root,spec,raw,now=None):
    root=Path(root).resolve();now=now or dt.datetime.now(dt.timezone.utc).isoformat()
    observed=parse(raw,spec)
    require(aware(observed['accepted_at_utc'])<=aware(now),'SEC_ACCEPTANCE_AFTER_CAPTURE')
    identity=digest(raw);folder=root/FOLDER/spec['accession'];folder.mkdir(parents=True,exist_ok=True)
    original=folder/(identity+'.txt.gz');record=folder/(identity+'.json')
    if record.exists():
        prior=json.loads(record.read_bytes());verify(root,prior)
        require(prior['requested_spec']==spec,'SEC_ARCHIVE_SPEC_CHANGED')
        return prior
    require(not original.exists(),'SEC_HALF_WRITTEN_ARCHIVE_REQUIRES_REVIEW')
    prior_versions=sorted(p.stem for p in folder.glob('*.json'))
    receipt=dict(schema=SCHEMA,source_url=source_url(spec),requested_spec=spec,
        archive_path=original.relative_to(root).as_posix(),raw_sha256=identity,bytes=len(raw),
        first_captured_at_utc=aware(now).isoformat(),parsed=observed,prior_content_versions=prior_versions,
        post_acceptance_content_change_observed=bool(prior_versions),
        acceptance_metadata_reparsed_from_original=True,
        sec_acceptance_is_not_a_complete_revision_or_dissemination_history=True,
        full_historical_financial_PIT_admitted=False,formal_Aplus_added=0,
        notes=['SEC can authorize post-acceptance corrections/deletions; complete revision history is still a separate obligation.',
               'No early public availability is inferred from a report signature date or from collection time.',
               'This source pilot covers only the explicitly listed issuer/filings, not the historical market universe.'])
    original.write_bytes(gzip.compress(raw,mtime=0))
    with record.open('x',encoding='utf-8') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2);stream.write('\n')
    verify(root,receipt)
    return receipt


def fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Encoding':'identity'})
    with urllib.request.urlopen(request,timeout=40) as response:
        require(response.status==200 and response.geturl()==url,'SEC_HTTP_STATUS_OR_REDIRECT_UNEXPECTED')
        body=response.read(MAX_BYTES+1)
    require(len(body)<=MAX_BYTES,'SEC_HTTP_BODY_TOO_LARGE')
    return body


def collect(root,manifest,fetcher=fetch,offline=False):
    root=Path(root).resolve();sources=manifest.get('sources')
    require(manifest.get('schema')=='SEC_HISTORICAL_SOURCE_PILOT_V1' and isinstance(sources,list)
            and 0<len(sources)<=8,'SEC_MANIFEST_INVALID_OR_UNBOUNDED')
    require(len({s['accession'] for s in sources})==len(sources),'SEC_MANIFEST_DUPLICATE_ACCESSION')
    receipts,errors,pending=[],[],[]
    for spec in sources:
        source_url(spec)
        cached=sorted((root/FOLDER/spec['accession']).glob('*.json'))
        try:
            if cached:
                for path in cached:
                    receipt=json.loads(path.read_bytes());verify(root,receipt)
                    require(receipt['requested_spec']==spec,'SEC_CACHED_SPEC_MISMATCH')
                    receipts.append(receipt)
            elif offline:
                pending.append(spec['accession'])
            else:
                receipts.append(archive(root,spec,fetcher(source_url(spec))))
                time.sleep(.2)
        except (ValueError,KeyError,TypeError,OSError,EOFError) as exc:
            errors.append(dict(accession=spec['accession'],reason=str(exc)))
    return dict(schema='REGULATORY_SOURCE_INTAKE_STATUS_V1',observed_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        status='SOURCE_ERRORS' if errors else 'SOURCE_COLLECTION_PENDING' if pending else 'ORIGINAL_SUBMISSIONS_VERIFIED',
        requested_filings=len(sources),verified_original_versions=len(receipts),
        issuer_count=len({r['parsed']['cik'] for r in receipts}),
        original_documents=sum(r['parsed']['document_count'] for r in receipts),
        receipts=[dict(accession=r['parsed']['accession'],raw_sha256=r['raw_sha256'],
                       accepted_at_utc=r['parsed']['accepted_at_utc'],report_period=r['parsed']['report_period'],
                       archive_path=r['archive_path']) for r in receipts],
        errors=errors,pending=pending,full_historical_financial_PIT_admitted=0,
        formal_Aplus_added=0,calibrated_expected_returns_created=0)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='tw-market-data')
    parser.add_argument('--manifest',default='tw-market-data/config/sec_historical_sources_v1.json')
    parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    result=collect(Path(args.root),json.loads(Path(args.manifest).read_bytes()),offline=args.offline)
    out=Path(args.root)/'rankings';out.mkdir(parents=True,exist_ok=True)
    (out/'latest_regulatory_source_intake.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    return int(bool(result['errors']))


if __name__=='__main__':raise SystemExit(main())
