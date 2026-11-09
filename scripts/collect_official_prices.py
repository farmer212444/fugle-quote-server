#!/usr/bin/env python3
"""One official, same-session price intake for daily and research workflows."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.execution_quote_archive import add_execution_fields, persist_price_originals
from scripts.v8a4_market_close_recovery import collect_openapi_sources, reconcile_sessions
from tw_model_v880.freshness import load_dated_exchange_closures

TAIPEI = dt.timezone(dt.timedelta(hours=8))
URLS = {
    'TWSE': 'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL',
    'TPEX': 'https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes',
}


def date_iso(raw):
    value = str(raw or '').strip().replace('/', '').replace('-', '')
    if not re.fullmatch(r'\d{7}|\d{8}', value):
        raise ValueError('INVALID_EXCHANGE_TRADE_DATE')
    if len(value) == 7:
        value = f'{int(value[:3]) + 1911:04d}' + value[3:]
    return dt.date(int(value[:4]), int(value[4:6]), int(value[6:8])).isoformat()


def price(raw):
    try:
        value = float(str(raw).strip().replace(',', ''))
    except (ValueError, TypeError):
        return None
    return value if 0 < value < 1000000 else None


def integer(raw):
    value = str(raw if raw is not None and not isinstance(raw, bool) else '').strip().replace(',', '')
    return int(value) if re.fullmatch(r'\d+', value) else None


def fetch_openapi(market, url, raw_dir):
    if URLS.get(market) != url:
        raise ValueError('UNTRUSTED_PRICE_OPENAPI_URL')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research archival collector)'})
    with urllib.request.urlopen(req, timeout=45) as response:
        if response.status != 200:
            raise ValueError('PRICE_OPENAPI_HTTP_STATUS')
        data = response.read(20000001)
    if not 1000 < len(data) <= 20000000 or b'<html' in data[:200].lower():
        raise ValueError('PRICE_OPENAPI_NOT_JSON')
    records = json.loads(data.decode('utf-8-sig'))
    if not isinstance(records, list) or len(records) < 300:
        raise ValueError('PRICE_OPENAPI_TOO_FEW_ROWS')
    parsed, dates, seen = [], set(), set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('PRICE_OPENAPI_ROW_NOT_OBJECT')
        day = date_iso(record.get('Date'))
        dates.add(day)
        code = str(record.get('Code' if market == 'TWSE' else 'SecuritiesCompanyCode', '')).strip()
        if not re.fullmatch(r'\d{4}', code):
            continue
        if code in seen:
            raise ValueError('PRICE_OPENAPI_DUPLICATE_STOCK')
        seen.add(code)
        row = dict(market=market, date=day, code=code,
                   name=str(record.get('Name' if market == 'TWSE' else 'SecuritiesCompanyName', record.get('Name', ''))).strip(),
                   close=price(record.get('ClosingPrice' if market == 'TWSE' else 'Close')),
                   volume_shares=integer(record.get('TradeVolume' if market == 'TWSE' else 'TradingShares')),
                   turnover_ntd=integer(record.get('TradeValue' if market == 'TWSE' else 'TransactionAmount')))
        parsed.append(add_execution_fields(row, record, market))
    if len(dates) != 1 or sum(x['close'] is not None for x in parsed) < 250:
        raise ValueError('PRICE_OPENAPI_MIXED_DATES_OR_INSUFFICIENT_QUOTES')
    Path(raw_dir).mkdir(parents=True, exist_ok=True)
    (Path(raw_dir) / (market.lower() + '.json')).write_bytes(data)
    return parsed, next(iter(dates)), hashlib.sha256(data).hexdigest()


def atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            name = Path(stream.name)
            stream.write(payload)
        name.replace(path)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def capture(root, raw_dir, *, now=None, probe_only=False, fetch_fn=None, recover_fn=None):
    root, raw_dir = Path(root).resolve(), Path(raw_dir).resolve()
    now = now or dt.datetime.now(TAIPEI)
    if now.tzinfo is None:
        raise ValueError('PRICE_CAPTURE_TIMEZONE_REQUIRED')
    raw_dir.mkdir(parents=True, exist_ok=True)
    fetch = fetch_fn or (lambda market, url: fetch_openapi(market, url, raw_dir))
    gathered, errors = collect_openapi_sources(URLS, fetch)
    if probe_only:
        return dict(status='EARLY_PROBE_ONLY_NOT_PUBLISHED',
                    exchange_sessions={m: x[1] if x else None for m, x in gathered.items()},
                    primary_errors=errors)
    gathered, routes, repaired = reconcile_sessions(
        gathered, URLS, raw_dir, now, load_dated_exchange_closures(root), recover_fn=recover_fn)
    days = {value[1] for value in gathered.values()}
    if len(days) != 1:
        raise ValueError('PRICE_EXCHANGE_DATES_DIFFER')
    day = days.pop()
    if not 0 <= (now.astimezone(TAIPEI).date() - dt.date.fromisoformat(day)).days <= 4:
        raise ValueError('PUBLISHABLE_EXCHANGE_SESSION_TOO_OLD')
    output = root / 'prices'
    latest = output / 'latest_manifest.json'
    if latest.is_file() and day < json.loads(latest.read_bytes())['date']:
        raise ValueError('EXCHANGE_DATE_REGRESSION')
    rows = sorted(gathered['TWSE'][0] + gathered['TPEX'][0], key=lambda x: (x['market'], x['code']))
    if len({(x['market'], x['code']) for x in rows}) != len(rows):
        raise ValueError('PRICE_DUPLICATE_MARKET_STOCK')
    if any(x.get('date') != day or x.get('market') != m
           for m, (items, _, _) in gathered.items() for x in items):
        raise ValueError('PRICE_ROW_IDENTITY_OR_DATE_MISMATCH')
    payload = (json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()
    checksum = hashlib.sha256(payload).hexdigest()
    raw_hashes = {market: value[2] for market, value in gathered.items()}
    # Verify and persist both original sources before touching a dated price
    # correction or the last-good manifest. Never publish one repaired market.
    receipt = persist_price_originals(output, raw_dir, day, checksum, raw_hashes, routes)
    dest = output / (day + '.json')
    if dest.is_file() and dest.read_bytes() != payload:
        prior = dest.read_bytes()
        revision = output / 'revisions' / day / (hashlib.sha256(prior).hexdigest() + '.json')
        if revision.is_file() and revision.read_bytes() != prior:
            raise ValueError('PRICE_REVISION_IMMUTABILITY_CONFLICT')
        if not revision.exists():
            atomic_write(revision, prior)
    if not dest.is_file() or dest.read_bytes() != payload:
        atomic_write(dest, payload)
    manifest = dict(date=day, TWSE_rows=len(gathered['TWSE'][0]), TPEX_rows=len(gathered['TPEX'][0]),
                    total=len(rows), path=f'{root.name}/prices/{day}.json', normalized_sha256=checksum,
                    raw_source_sha256=raw_hashes, sources=routes,
                    original_receipt_path=receipt.relative_to(output).as_posix(),
                    unadjusted_quotes=True, security_master_verified=False,
                    note='Latest daily unadjusted close; not adjusted for cash dividends, splits or corporate actions.')
    data = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    changed = not latest.is_file() or latest.read_bytes() != data
    if changed:
        atomic_write(latest, data)
    return dict(status='OFFICIAL_SAME_SESSION_PRICES_PUBLISHED' if changed else 'LATEST_REFERENCE_UNCHANGED',
                date=day, rows=len(rows), normalized_sha256=checksum,
                dated_recovery_markets=repaired, primary_errors=errors,
                formal_Aplus_added=0, execution_certified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT / 'tw-market-data')
    parser.add_argument('--raw-dir', type=Path, default=ROOT / 'market-raw-daily')
    parser.add_argument('--probe-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(capture(args.root, args.raw_dir, probe_only=args.probe_only)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
