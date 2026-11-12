#!/usr/bin/env python3
"""Archive partial official tables for a bounded set; never replace full-quarter inputs."""
import argparse
import datetime as dt
import gzip
import json
import concurrent.futures
from html import unescape
import re
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_research_pipeline import atomic_json
from tw_model_v880.early_bulk import (FOLDER, SCHEMA, URLS, MOPS, ANNOUNCEMENT_KIND,
                                    parse, period, sha, announcement, verified_source)
from tw_model_v880.evidence import timestamp

MAX_LAST_GOOD_AGE_DAYS = 7


def verify_retained_last_good(root, requested, now=None):
    """A failed live pull may keep *only* an independently replayable old manifest.

    The manifest is never rewritten, restamped, or represented as fresh. Missing
    newly requested issuers are named explicitly, rather than treated as zero
    observations. Old source archives must retain the same original SHA bytes.
    """
    root = Path(root).resolve()
    old_path = root / FOLDER / 'manifest.json'
    if not old_path.is_file():
        raise ValueError('EARLY_LAST_GOOD_MANIFEST_MISSING')
    prior_bytes = old_path.read_bytes()
    old = json.loads(prior_bytes)
    if (old.get('schema') != SCHEMA or old.get('formal_quality_pass') is not False
            or old.get('retrospective_PIT_verified') is not False):
        raise ValueError('EARLY_LAST_GOOD_MANIFEST_SCOPE_INVALID')
    prior_scope = old.get('requested_issuers')
    if (not isinstance(prior_scope, list) or not prior_scope or len(prior_scope)>2004
            or not isinstance(old.get('captures'), list) or not old['captures']
            or not isinstance(old.get('announcements', []), list)):
        raise ValueError('EARLY_LAST_GOOD_MANIFEST_INCOMPLETE')
    def identity(row):
        if (not isinstance(row,dict) or row.get('market') not in ('TWSE','TPEX')
                or not isinstance(row.get('code'),str)
                or not re.fullmatch(r'\d{4}',row['code'])):
            raise ValueError('EARLY_LAST_GOOD_ISSUER_IDENTITY_INVALID')
        return (row['market'],row['code'])
    scope = [identity(x) for x in prior_scope]
    wanted = [identity(x) for x in requested]
    if len(scope)!=len(set(scope)) or len(wanted)!=len(set(wanted)):
        raise ValueError('EARLY_LAST_GOOD_DUPLICATED_ISSUER')
    captured_markets = [r.get('market') for r in old['captures']]
    if (len(captured_markets)!=len(set(captured_markets))
            or not set(m for m,c in wanted).issubset(set(captured_markets))):
        raise ValueError('EARLY_LAST_GOOD_MARKET_SOURCE_MISSING')
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError('EARLY_LAST_GOOD_CLOCK_NAIVE')
    cutoff = timestamp(now.isoformat())
    verified_count = 0
    receipt_times = []
    notice_pairs = set()
    for receipt in old['captures'] + old.get('announcements', []):
        if receipt.get('source_kind') == ANNOUNCEMENT_KIND:
            pair = identity(receipt)
            if pair in notice_pairs or pair not in set(scope):
                raise ValueError('EARLY_LAST_GOOD_NOTICE_SCOPE_OR_DUPLICATE')
            notice_pairs.add(pair)
        verified_source(root, receipt, cutoff)
        receipt_times.append(timestamp(receipt['captured_at']))
        verified_count += 1
    newest = max(receipt_times)
    if newest>cutoff or (cutoff-newest)>dt.timedelta(days=MAX_LAST_GOOD_AGE_DAYS):
        raise ValueError('EARLY_LAST_GOOD_SOURCE_TOO_OLD_OR_FUTURE')
    extra = sorted(set(wanted)-set(scope))
    return dict(
        prior_manifest_sha256=sha(prior_bytes),
        previous_manifest_unchanged=True,
        verified_retained_receipts=verified_count,
        last_good_capture_utc=newest.isoformat(),
        latest_observation_is_not_new=True,
        missing_latest_requested_issuers=[
            dict(market=market,code=code) for market,code in extra],
        newly_requested_issuers_not_assumed_observed=True,
        formal_quality_pass=False,
        model_PIT_or_Aplus_advanced=False,
    )


def fetch_bytes(request, limit, timeout, *, expected_url=None):
    """Retry only transport failures; source identity and content still fail closed."""
    for attempt in range(3):
        delay = 2 ** attempt
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200 or (expected_url and response.geturl() != expected_url):
                    raise ValueError('EARLY_BULK_SOURCE_HTTP_OR_REDIRECT_INVALID')
                return response.read(limit)
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
            retry_after = (exc.headers.get('Retry-After', '') if exc.headers else '').strip()
            if retry_after.isdecimal():
                if len(retry_after) > 6 or int(retry_after) > 5:
                    raise  # Do not retry earlier than a longer server cooldown.
                delay = max(delay, int(retry_after))
            reason = 'HTTP_' + str(exc.code)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == 2:
                raise
            reason = type(exc).__name__
        print(json.dumps(dict(status='EARLY_SOURCE_TRANSPORT_RETRY', attempt=attempt + 1,
                              reason=reason, delay_seconds=delay,
                              source_url=request.full_url)))
        time.sleep(delay)


def capture(root, market):
    request = urllib.request.Request(URLS[market], headers={'User-Agent': 'Mozilla/5.0 (dated financial research archive)'})
    raw = fetch_bytes(request, 8_000_001, 25, expected_url=URLS[market])
    rows = parse(raw)
    digest = sha(raw)
    folder = root / FOLDER / market
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = folder / (digest + '.json')
    archive = folder / (digest + '.raw.gz')
    if receipt_path.exists():
        old = json.loads(receipt_path.read_bytes())
        if not archive.is_file() or gzip.decompress(archive.read_bytes()) != raw:
            raise ValueError('EARLY_BULK_EXISTING_CAPTURE_MISMATCH')
        return old
    packed = gzip.compress(raw, mtime=0)
    receipt = dict(market=market, source_url=URLS[market], archive_path=archive.relative_to(root).as_posix(),
                   raw_sha256=digest, gzip_sha256=sha(packed), bytes=len(raw),
                   captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                   observed_rows=len(rows), observed_periods=sorted({period(x) for x in rows.values()}),
                   partial_table_not_complete_universe=True, formal_quality_pass=False)
    archive.write_bytes(packed)
    atomic_json(receipt_path, receipt)
    return receipt


def capture_notices(root, issuer):
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    code, market = issuer['code'], issuer['market']
    params = dict(encodeURIComponent=1, step=1, firstin=1, off=1, isQuery='Y',
                  co_id=code, TYPEK='all', year=now.year-1911, month=now.month)
    url = MOPS + '?' + urllib.parse.urlencode(params)
    raw = fetch_bytes(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), 2_000_001, 20)
    if len(raw) > 2_000_000:
        raise ValueError('EARLY_ANNOUNCEMENT_LIST_TOO_LARGE')
    text = raw.decode('utf-8-sig')
    if '公開資訊觀測站' not in text:
        raise ValueError('EARLY_ANNOUNCEMENT_LIST_UNRECOGNIZED')
    folder = root / FOLDER / market
    folder.mkdir(parents=True, exist_ok=True)
    digest = sha(raw)
    listing = folder / (digest + '.listing.html.gz')
    listing.write_bytes(gzip.compress(raw, mtime=0))
    probe = dict(code=code, market=market, source_url=url,
                 archive_path=listing.relative_to(root).as_posix(), raw_sha256=digest,
                 gzip_sha256=sha(listing.read_bytes()), bytes=len(raw),
                 captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                 searched_year=now.year, searched_month=now.month,
                 no_match_does_not_prove_no_announcement=True)
    receipts = []
    for tr in re.findall(r'<tr\b.*?</tr>', text, re.I | re.S):
        if not re.search(r'第[三3]季.*財務報', tr) or '預計' in tr:
            continue
        if '代子公司' in tr or '代重要子公司' in tr:
            continue
        values = {}
        for field in ('seq_no', 'spoke_time', 'spoke_date', 'co_id', 'TYPEK'):
            matches = re.findall(r'\.' + field + r"\.value='([^']+)'", unescape(tr))
            if len(matches) != 1:
                raise ValueError('EARLY_ANNOUNCEMENT_DETAIL_LINK_AMBIGUOUS')
            values[field] = matches[0]
        if values['co_id'] != code or values['TYPEK'] != {'TWSE': 'sii', 'TPEX': 'otc'}[market]:
            raise ValueError('EARLY_ANNOUNCEMENT_DETAIL_LINK_IDENTITY_MISMATCH')
        if not (re.fullmatch(r'\d{8}', values['spoke_date']) and re.fullmatch(r'\d{6}', values['spoke_time'])
                and re.fullmatch(r'\d{1,3}', values['seq_no'])):
            raise ValueError('EARLY_ANNOUNCEMENT_DETAIL_LINK_CLOCK_INVALID')
        detail_url = MOPS + '?' + urllib.parse.urlencode(dict(firstin='true', step=2, off=1, **values))
        body = fetch_bytes(urllib.request.Request(detail_url, headers={'User-Agent': 'Mozilla/5.0'}), 2_000_001, 20)
        if len(body) > 2_000_000:
            raise ValueError('EARLY_ANNOUNCEMENT_DETAIL_TOO_LARGE')
        digest = sha(body)
        archive, receipt_path = folder / (digest + '.notice.html.gz'), folder / (digest + '.notice.json')
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_bytes())
        else:
            packed = gzip.compress(body, mtime=0)
            receipt = dict(code=code, market=market, source_kind=ANNOUNCEMENT_KIND,
                            source_url=detail_url, archive_path=archive.relative_to(root).as_posix(),
                            raw_sha256=digest, gzip_sha256=sha(packed), bytes=len(body),
                            captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                            original_company_announcement_not_complete_financial_statement=True,
                            formal_quality_pass=False)
            announcement(body, receipt)
            archive.write_bytes(packed)
            atomic_json(receipt_path, receipt)
        verified_source(root, receipt, timestamp(dt.datetime.now(dt.timezone.utc).isoformat()))
        receipts.append(receipt)
    probe['observed_quarterly_earnings_announcements'] = len(receipts)
    return probe, receipts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT / 'tw-market-data')
    parser.add_argument('--codes', nargs='+')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--retain-verified-on-error', action='store_true',
                        help='continue on failed new sources only when the last-good '
                             'manifest is independently replayed with bounded age')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.offline:
        path = root / FOLDER / 'manifest.json'
        if path.exists():
            doc = json.loads(path.read_bytes())
            for receipt in doc['captures'] + doc.get('announcements', []):
                verified_source(root, receipt, timestamp(dt.datetime.now(dt.timezone.utc).isoformat()))
        print('OFFLINE_EARLY_QUARTER_ARCHIVES_VERIFIED_NO_CERTIFICATES_ISSUED')
        return 0
    if not args.codes:
        previous = json.loads((root / 'rankings/latest_research.json').read_bytes())
        args.codes = [r['code'] for r in previous['top10_market_research']]
        manifest = root / FOLDER / 'manifest.json'
        if manifest.exists():
            args.codes += [r['code'] for r in json.loads(manifest.read_bytes())['requested_issuers']]
    evidence = json.loads(gzip.decompress((root / 'evidence/v880/snapshot.json.gz').read_bytes()))
    requested = [dict(code=c, market=evidence['master'][c]['market']) for c in sorted(set(args.codes))]
    captures, errors = [], []
    for market in sorted({x['market'] for x in requested}):
        try:
            captures.append(capture(root, market))
        except Exception as exc:
            errors.append(dict(market=market, error=str(exc)))
    probes, notices = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        tasks = {pool.submit(capture_notices, root, issuer): issuer for issuer in requested}
        for future, issuer in tasks.items():
            try:
                probe, rows = future.result()
                probes.append(probe)
                notices.extend(rows)
            except Exception as exc:
                errors.append(dict(code=issuer['code'], error=str(exc)))
    # Never permit a malformed or unreachable current source into the
    # model. Scheduled runs may continue on *previous, fully hash-replayed*
    # evidence, with an explicit intake-health artifact and a bounded age.
    health_path = root / 'rankings/early_bulk_intake_health_latest.json'
    if errors:
        issue=dict(status='CURRENT_EARLY_SOURCES_REJECTED',errors=errors,
                   new_captures_not_admitted=True,
                   Aplus_added=0,older_source_not_a_current_observation=True)
        if args.retain_verified_on_error:
            retained=verify_retained_last_good(root,requested)
            issue.update(retained)
            issue['status']='VERIFIED_LAST_GOOD_RETAINED_NEW_SOURCES_REJECTED'
            atomic_json(health_path,issue)
            print(json.dumps(issue,ensure_ascii=False))
            return 0
        print(json.dumps(issue,ensure_ascii=False))
        return 1
    manifest = dict(schema=SCHEMA, requested_issuers=requested, captures=captures,
                    announcements=notices, announcement_probes=probes,
                    full_market_eligible_period_unchanged=True,
                    formal_quality_pass=False, retrospective_PIT_verified=False)
    atomic_json(root / FOLDER / 'manifest.json', manifest)
    atomic_json(health_path,dict(status='ALL_CURRENT_EARLY_SOURCES_CAPTURED',
        requested=len(requested),new_source_errors=[],
        retained_prior_after_failed_fetch=False,
        issuer_announcements=len(notices),Aplus_added=0,
        historical_PIT_certified=False))
    print(json.dumps(dict(status='OFFICIAL_PARTIAL_TABLE_ARCHIVED_RESEARCH_ONLY',
                         requested=len(requested), issuer_announcements=len(notices), captures=[dict(market=r['market'], rows=r['observed_rows'],
                         periods=r['observed_periods']) for r in captures]), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
