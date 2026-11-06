#!/usr/bin/env python3
"""Capture a bounded issuer earnings pilot and replay date-aware TTM arithmetic.

Issuer-dated documents captured today are useful research inputs. They do not,
on their own, establish the content that was publicly available years ago.
"""
import argparse
import datetime as dt
import gzip
import json
import re
import time
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from scripts.sec_pit_intake import aware, digest, fetch, require, safe
except ModuleNotFoundError:
    from sec_pit_intake import aware, digest, fetch, require, safe

FOLDER = 'evidence/v880/issuer_earnings'
SCHEMA = 'ISSUER_DATED_EARNINGS_ORIGINAL_V1'
TAIPEI = ZoneInfo('Asia/Taipei')


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def source_url(spec):
    require(spec.get('market') == 'TWSE' and spec.get('code') == '2330',
            'ISSUER_PILOT_IDENTITY_NOT_SUPPORTED')
    endpoint = spec.get('url', '')
    require(isinstance(endpoint, str) and re.fullmatch(
        r'https://pr\.tsmc\.com/english/news/\d+', endpoint),
        'ISSUER_SOURCE_NOT_ALLOWLISTED')
    period = dt.date.fromisoformat(spec['report_period'])
    require((period.month, period.day) in ((3, 31), (6, 30), (9, 30), (12, 31)),
            'ISSUER_PERIOD_NOT_QUARTER_END')
    require(period < dt.date.fromisoformat(spec['published_on']),
            'ISSUER_PUBLICATION_BEFORE_PERIOD_END')
    return endpoint


def parse(raw, spec):
    source_url(spec)
    require(isinstance(raw, bytes) and 0 < len(raw) <= 5*1024*1024,
            'ISSUER_ORIGINAL_SIZE_INVALID')
    html = raw.decode('utf-8-sig')
    require('<html' in html.lower(), 'ISSUER_HTML_REQUIRED')
    parser = Text()
    parser.feed(html)
    text = re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()
    dates = re.findall(r'Issued on:\s*(\d{4}/\d{2}/\d{2})', text)
    require(len(dates) == 1 and dates[0].replace('/', '-') == spec['published_on'],
            'ISSUER_PUBLICATION_DATE_MISMATCH')
    require('Issued by: TSMC' in text, 'ISSUER_AUTHOR_MISSING')
    number = r'([\d,]+\.\d+)'
    pattern = (r'TSMC\s*\(TWSE:\s*2330,\s*NYSE:\s*TSM\)\s*today announced '
               r'consolidated revenue of NT\$' + number + r' billion, '
               r'net income of NT\$' + number + r' billion, and diluted earnings '
               r'per share of NT\$' + number + r' \(US\$[\d.]+ per ADR unit\) '
               r'for the (first|second|third|fourth) quarter ended '
               r'([A-Za-z]+ \d{1,2}, \d{4})\.')
    matches = re.findall(pattern, text)
    require(len(matches) == 1, 'ISSUER_EARNINGS_PARAGRAPH_MISSING_OR_DUPLICATE')
    revenue, income, eps, quarter, end = matches[0]
    period = dt.datetime.strptime(end, '%B %d, %Y').date()
    require(period.isoformat() == spec['report_period'], 'ISSUER_REPORT_PERIOD_MISMATCH')
    require(quarter == ('first', 'second', 'third', 'fourth')[(period.month-1)//3],
            'ISSUER_QUARTER_NAME_MISMATCH')
    require('TIFRS' in text and 'on a consolidated basis' in text,
            'ISSUER_ACCOUNTING_BASIS_UNVERIFIED')
    def decimal(value):
        return str(Decimal(value.replace(',', '')))
    return dict(market='TWSE', code='2330', published_on=spec['published_on'],
                publication_clock_precision='DATE_ONLY', report_period=period.isoformat(),
                quarter=(period.month-1)//3+1, currency='TWD', basis='CONSOLIDATED_TIFRS',
                diluted_eps_twd_per_ordinary_share=decimal(eps),
                revenue_twd_billion=decimal(revenue), net_income_twd_billion=decimal(income),
                financial_paragraph_sha256=digest(matches[0].__repr__().encode()))


def verify(root, receipt):
    raw = gzip.decompress(safe(root, receipt['archive_path']).read_bytes())
    require(receipt.get('schema') == SCHEMA and receipt['raw_sha256'] == digest(raw)
            and receipt['bytes'] == len(raw), 'ISSUER_ARCHIVE_BYTES_MISMATCH')
    require(receipt['source_url'] == source_url(receipt['requested_spec']),
            'ISSUER_ARCHIVE_SOURCE_MISMATCH')
    facts = parse(raw, receipt['requested_spec'])
    require(facts == receipt['facts'], 'ISSUER_ARCHIVE_FACTS_MISMATCH')
    require(aware(receipt['first_captured_at_utc']).astimezone(TAIPEI).date()
            >= dt.date.fromisoformat(facts['published_on']), 'ISSUER_CAPTURE_PREDATES_DOCUMENT')
    return facts


def archive(root, spec, raw, now=None):
    root = Path(root).resolve()
    facts = parse(raw, spec)
    now = aware(now or dt.datetime.now(dt.timezone.utc).isoformat())
    require(now.astimezone(TAIPEI).date() >= dt.date.fromisoformat(facts['published_on']),
            'ISSUER_CAPTURE_PREDATES_DOCUMENT')
    identity = digest(raw)
    folder = root/FOLDER/spec['code']/spec['report_period']
    folder.mkdir(parents=True, exist_ok=True)
    original = folder/(identity+'.html.gz')
    path = folder/(identity+'.json')
    if path.exists():
        receipt = json.loads(path.read_bytes())
        verify(root, receipt)
        require(receipt['requested_spec'] == spec, 'ISSUER_ARCHIVE_SPEC_CHANGED')
        return receipt
    require(not original.exists(), 'ISSUER_HALF_WRITTEN_ARCHIVE')
    prior = [json.loads(p.read_bytes()) for p in sorted(folder.glob('*.json'))]
    for old in prior:
        verify(root, old)
    receipt = dict(schema=SCHEMA, source_url=source_url(spec), requested_spec=spec,
        archive_path=original.relative_to(root).as_posix(), raw_sha256=identity, bytes=len(raw),
        first_captured_at_utc=now.isoformat(), facts=facts,
        prior_observed_hashes=[r['raw_sha256'] for r in prior],
        financial_content_change_observed=any(r['facts'] != facts for r in prior),
        publication_date_and_current_content_verified=True,
        historical_version_at_publication_verified=False, historical_universe_verified=False,
        full_historical_financial_PIT_admitted=False, formal_Aplus_added=0)
    original.write_bytes(gzip.compress(raw, mtime=0))
    with path.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    verify(root, receipt)
    return receipt


def research_ttm(root, receipts, cutoff):
    """Date-aware research arithmetic only; cannot certify retrospective PIT.

    Date-only releases enter on the following Taipei calendar day. Conflicting
    observed versions are rejected rather than selecting today's latest value.
    """
    cutoff = aware(cutoff).astimezone(TAIPEI)
    periods = {}
    for receipt in receipts:
        facts = verify(root, receipt)
        if dt.date.fromisoformat(facts['published_on']) >= cutoff.date():
            continue
        period = facts['report_period']
        if period in periods:
            require(periods[period]['facts'] == facts, 'ISSUER_HISTORICAL_VERSION_AMBIGUOUS')
        else:
            periods[period] = receipt
    require(len(periods) >= 4, 'ISSUER_FOUR_RELEASED_QUARTERS_REQUIRED')
    chosen = [periods[p] for p in sorted(periods)[-4:]]
    indices = [dt.date.fromisoformat(r['facts']['report_period']).year*4
               + r['facts']['quarter'] for r in chosen]
    require(indices == list(range(indices[0], indices[0]+4)), 'ISSUER_TTM_QUARTER_GAP')
    eps = sum((Decimal(r['facts']['diluted_eps_twd_per_ordinary_share']) for r in chosen), Decimal(0))
    return dict(as_of=cutoff.isoformat(), method='SUM_FOUR_REPORTED_QUARTER_DILUTED_EPS_RESEARCH',
        sum_reported_diluted_eps_twd=str(eps),
        is_exact_annual_diluted_eps=False,
        note='Quarterly diluted denominators can differ; summed reported EPS is an approximation.',
        report_periods=[r['facts']['report_period'] for r in chosen],
        source_hashes=[r['raw_sha256'] for r in chosen],
        retrospective_PIT_verified=False, eligible_for_expected_return_calibration=False)


def collect(root, manifest, fetcher=fetch, offline=False):
    require(manifest.get('schema') == 'ISSUER_EARNINGS_SOURCE_PILOT_V1', 'ISSUER_MANIFEST_SCHEMA')
    sources = manifest.get('sources')
    require(isinstance(sources, list) and 0 < len(sources) <= 16, 'ISSUER_MANIFEST_UNBOUNDED')
    require(len({source_url(s) for s in sources}) == len(sources), 'ISSUER_DUPLICATE_SOURCE')
    receipts, errors, pending = [], [], []
    for spec in sources:
        try:
            if offline:
                paths = sorted((Path(root)/FOLDER/spec['code']/spec['report_period']).glob('*.json'))
                if not paths:
                    pending.append(spec['report_period'])
                for path in paths:
                    receipt = json.loads(path.read_bytes())
                    verify(root, receipt)
                    require(receipt['requested_spec'] == spec, 'ISSUER_CACHE_SPEC_MISMATCH')
                    receipts.append(receipt)
            else:
                receipts.append(archive(root, spec, fetcher(source_url(spec))))
                time.sleep(.2)
        except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
            errors.append(dict(url=spec['url'], reason=str(exc)))
    result = dict(schema='ISSUER_EARNINGS_INTAKE_STATUS_V1',
        observed_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        status='SOURCE_ERRORS' if errors else 'SOURCE_COLLECTION_PENDING' if pending else 'ISSUER_ORIGINALS_CAPTURED',
        requested_documents=len(sources), verified_document_versions=len(receipts),
        issuer_count=len({r['facts']['code'] for r in receipts}), records=receipts,
        errors=errors, pending=pending, research_ttm_replays=[],
        full_historical_financial_PIT_admitted=0, calibrated_expected_returns_created=0,
        formal_Aplus_added=0)
    for cutoff in manifest.get('research_replay_cutoffs', []):
        try:
            result['research_ttm_replays'].append(research_ttm(root, receipts, cutoff))
        except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
            result['research_ttm_replays'].append(dict(as_of=cutoff, status='BLOCKED', reason=str(exc)))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='tw-market-data')
    parser.add_argument('--manifest', default='tw-market-data/config/issuer_earnings_sources_v1.json')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    result = collect(Path(args.root), json.loads(Path(args.manifest).read_bytes()), offline=args.offline)
    out = Path(args.root)/'rankings'
    out.mkdir(parents=True, exist_ok=True)
    (out/'latest_issuer_earnings_intake.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}, ensure_ascii=False))
    return int(bool(result['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
