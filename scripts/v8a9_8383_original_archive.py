#!/usr/bin/env python3
"""Capture issuer-original 8383 Q1/Q2 PDFs, immutable SHA receipts, no formal PASS.

The exact issuer source URLs come from the pre-reviewed audit-scope watch.
This captures what exists now; publisher dates are NOT historical MOPS PIT.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

SCHEMA='V8A9_8383_ISSUER_ORIGINAL_BYTES_NOT_FORMAL_REVIEW'
ISSUER='8383'
MAX_FILE_BYTES=15_000_000
HOSTS={'www.chenfull.com.tw','chenfull.com.tw'}


def sha256(raw):return hashlib.sha256(raw).hexdigest()


def official_pdf_url(url):
    if not isinstance(url,str):return False
    parsed=urllib.parse.urlsplit(url)
    return (parsed.scheme=='https' and parsed.hostname in HOSTS
            and parsed.username is None and parsed.password is None
            and parsed.port in (None,443)
            and parsed.path.lower().endswith('.pdf')
            and not parsed.fragment)


def fetch_pdf(url):
    if not official_pdf_url(url):raise ValueError('8383_PUBLISHER_URL_NOT_ALLOWLISTED')
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (research-original-source-archive)',
                                               'Accept':'application/pdf'})
    with urllib.request.urlopen(request,timeout=30) as response:
        if response.status!=200 or not official_pdf_url(response.geturl()):
            raise ValueError('8383_PDF_HTTP_OR_REDIRECT_INVALID')
        raw=response.read(MAX_FILE_BYTES+1)
    return raw


def validate_pdf(raw):
    if (not isinstance(raw,bytes) or not 5000<=len(raw)<=MAX_FILE_BYTES
        or not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-4096:]):
        raise ValueError('8383_PDF_INVALID_OR_OVERSIZED')
    return sha256(raw)


def expected_sources(watch):
    if (watch.get('issuer')!='8383' or watch.get('period')!='2026-Q2'
        or watch.get('original_MOPS_filing_PIT_verified') is not False
        or watch.get('formal_auditor_scope_gate_pass') is not False):
        raise ValueError('8383_WATCH_SCOPE_OR_CERTIFICATION_INVALID')
    prior=watch.get('prior_interim_review_observation') or {}
    specs=[('2026-Q1',prior.get('issuer_original_source_url'),prior.get('document_dated')),
           ('2026-Q2',watch.get('source_pdf_url'),watch.get('document_dated'))]
    for period,url,date in specs:
        if not official_pdf_url(url) or not re.fullmatch(r'2026-\d\d-\d\d',str(date)):
            raise ValueError('8383_INVALID_ISSUER_PDF_SOURCE_'+period)
    if len({url for _,url,_ in specs})!=2:raise ValueError('8383_DUPLICATE_PERIOD_SOURCE')
    return specs


def archive_folder(root):
    return Path(root)/'evidence/v880/originals/8383'


def verify_archive(root,watch):
    root=Path(root)
    folder=archive_folder(root)
    path=folder/'manifest.json'
    if not path.exists():
        return dict(status='ORIGINAL_PDF_BYTES_NOT_YET_CAPTURED',verified_periods=[],
                    original_pdf_bytes_hashed=False,MOPS_PIT_verified=False,
                    formal_auditor_scope_gate_pass=False)
    m=json.loads(path.read_text(encoding='utf-8'))
    if (m.get('schema')!=SCHEMA or m.get('issuer')!='8383'
        or m.get('MOPS_PIT_verified') is not False
        or m.get('formal_auditor_scope_gate_pass') is not False):
        raise ValueError('8383_ARCHIVE_FALSE_CERTIFICATION_OR_IDENTITY')
    specs={p:u for p,u,_ in expected_sources(watch)}
    entries=m.get('documents') or []
    if not isinstance(entries,list) or len(entries)>8:
        raise ValueError('8383_ARCHIVE_DOCUMENT_COUNT_INVALID')
    seen=set();periods=set();snapshots={}
    for e in entries:
        period=e.get('period');digest=e.get('sha256')
        if period not in specs or e.get('source_url')!=specs[period]:
            raise ValueError('8383_ARCHIVE_WRONG_ISSUER_SOURCE_OR_PERIOD')
        if not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
            raise ValueError('8383_ARCHIVE_INVALID_HASH')
        if (period,digest) in seen:raise ValueError('8383_DUPLICATED_ORIGINAL_VERSION')
        seen.add((period,digest))
        relative=e.get('archive_path','')
        expected=f'evidence/v880/originals/8383/{period}_{digest[:20]}.pdf'
        if relative!=expected or e.get('formally_certified') is not False:
            raise ValueError('8383_ARCHIVE_UNSAFE_PATH_OR_PASS')
        file=root/relative
        if not file.is_file():
            raise ValueError('8383_ARCHIVE_PDF_BYTES_MISSING')
        raw=file.read_bytes()
        if validate_pdf(raw)!=digest or len(raw)!=e.get('bytes'):
            raise ValueError('8383_ARCHIVE_PDF_SHA_OR_LENGTH_MISMATCH')
        dt.datetime.fromisoformat(e['first_captured_at_utc'].replace('Z','+00:00'))
        periods.add(period);snapshots[period]=dict(sha256=digest,bytes=len(raw))
    return dict(status='ARCHIVED_BYTES_REHASHED_NO_ORIGINAL_NOTES_REVIEW',
        verified_periods=sorted(periods),snapshots=snapshots,
        original_pdf_bytes_hashed=set(specs).issubset(periods),
        MOPS_PIT_verified=False,formal_auditor_scope_gate_pass=False)


def collect(root,*,asof_day,now,fetcher=fetch_pdf):
    root=Path(root)
    watch=json.loads((root/'evidence/v880/auditor_scope_watch/8383.json').read_text(encoding='utf-8'))
    specs=expected_sources(watch)
    if asof_day<watch['first_directly_inspected_on']:
        raise ValueError('8383_ARCHIVE_CANNOT_BACKDATE_FIRST_OBSERVATION')
    if dt.datetime.fromisoformat(now.replace('Z','+00:00')).tzinfo is None:
        raise ValueError('8383_CAPTURE_TIME_MUST_HAVE_TIMEZONE')
    folder=archive_folder(root)
    receipt=verify_archive(root,watch)
    manifest_path=folder/'manifest.json'
    entries=(json.loads(manifest_path.read_text(encoding='utf-8')).get('documents',[])
             if manifest_path.exists() else [])
    for period,url,document_date in specs:
        if document_date>asof_day:raise ValueError('8383_PUBLISHER_DATE_IN_FUTURE')
        try:
            raw=fetcher(url)
        except (OSError,TimeoutError,ValueError) as exc:
            # Fail isolated source capture; keep already SHA-verified records,
            # do not convert a network error into an original-evidence PASS.
            print(f'::warning::8383 ORIGINAL PDF fetch unavailable for {period}: {type(exc).__name__}: {exc}')
            continue
        digest=validate_pdf(raw)
        if any(e['period']==period and e['sha256']==digest for e in entries):
            continue
        folder.mkdir(parents=True,exist_ok=True)
        rel=f'evidence/v880/originals/8383/{period}_{digest[:20]}.pdf'
        dest=root/rel
        if dest.exists() and dest.read_bytes()!=raw:
            raise ValueError('8383_ARCHIVE_FILE_COLLISION')
        dest.write_bytes(raw)
        entries.append(dict(issuer='8383',period=period,source_url=url,
            document_date=document_date,sha256=digest,bytes=len(raw),
            archive_path=rel,first_captured_at_utc=now,
            publisher_date_is_not_pit=True,original_full_notes_reviewed=False,
            formally_certified=False))
    if entries and len(entries)>8:raise ValueError('8383_ARCHIVE_VERSION_BOUND_EXCEEDED_MANUAL_TRIAGE')
    entries.sort(key=lambda e:(e['period'],e['first_captured_at_utc'],e['sha256']))
    if entries:
        folder.mkdir(parents=True,exist_ok=True)
        manifest=dict(schema=SCHEMA,issuer='8383',MOPS_PIT_verified=False,
                      formal_auditor_scope_gate_pass=False,
                      source_issuer_originals_only=True,
                      documents=entries)
        new=json.dumps(manifest,indent=2,ensure_ascii=False)+'\n'
        if not manifest_path.exists() or manifest_path.read_text(encoding='utf-8')!=new:
            manifest_path.write_text(new,encoding='utf-8')
    return verify_archive(root,watch)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path('tw-market-data'))
    p.add_argument('--verify-only',action='store_true')
    args=p.parse_args()
    watch=json.loads((args.root/'evidence/v880/auditor_scope_watch/8383.json').read_text(encoding='utf-8'))
    now=dt.datetime.now(dt.timezone.utc)
    result=(verify_archive(args.root,watch) if args.verify_only else
            collect(args.root,asof_day=now.date().isoformat(),now=now.isoformat()))
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
