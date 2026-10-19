#!/usr/bin/env python3
"""V8.7.7 Taiwan official MOPS 8-quarter financial evidence collector.

Safety: neither a complete batch nor EPS extrapolation certifies A+/A++.
Company-specific publication timestamps, dilution, and capex must be audited.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import pathlib
import re
import time
import unicodedata
import urllib.parse
import urllib.request

OUT = pathlib.Path('tw-market-data')
FIN = OUT / 'fundamentals'
RAW = pathlib.Path('market-raw-quarterly')
MOPS = 'https://mopsov.twse.com.tw/mops/web/'
KINDS = {'income': 'ajax_t163sb04', 'cashflow': 'ajax_t163sb20'}
MARKETS = {'TWSE': 'sii', 'TPEX': 'otc'}
TZ = dt.timezone(dt.timedelta(hours=8))


def norm(value):
    s = unicodedata.normalize('NFKC', str(value))
    return re.sub(r'[\s\u3000(),()%％：:＿_／/、\-.]', '', s)


def num(raw):
    if raw is None:
        return None
    s = unicodedata.normalize('NFKC', str(raw)).strip().replace(',', '')
    if s.lower() in ('', 'nan', 'none', '--', '-', 'n/a', '—', '－'):
        return None
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        result = float(s)
    except ValueError:
        return None
    return result if result == result and abs(result) < 1e16 else None


def column(cols, aliases):
    # Exact match first; allows MOPS variants and duplicated two-row headings.
    for alias in aliases:
        target = norm(alias)
        for col in cols:
            if norm(col) == target:
                return col
    for alias in aliases:
        target = norm(alias)
        for col in cols:
            if target in norm(col):
                return col
    return None


def parse(body: bytes, kind: str, year: int, quarter: int, market: str):
    import pandas as pd
    try:
        tables = pd.read_html(io.StringIO(body.decode('utf-8-sig', errors='replace')), displayed_only=False)
    except (ValueError, ImportError) as exc:
        raise ValueError('MOPS response had no valid HTML financial tables') from exc
    found = {}
    for frame in tables:
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = [' '.join(str(x) for x in c if str(x) != 'nan' and not str(x).startswith('Unnamed'))
                             for c in frame.columns]
        cols = list(frame.columns)
        code_col = column(cols, ['公司代號', '公司代碼'])
        if not code_col:
            for n in range(min(3, len(frame))):
                headers = list(frame.iloc[n].astype(str))
                if column(headers, ['公司代號', '公司代碼']):
                    frame = frame.iloc[n + 1:].copy()
                    frame.columns = headers
                    cols = list(frame.columns)
                    code_col = column(cols, ['公司代號', '公司代碼'])
                    break
        if not code_col:
            continue
        name_col = column(cols, ['公司名稱'])
        fields = ({
            'revenue_ytd_k': ['營業收入'],
            'gross_profit_ytd_k': ['營業毛利毛損淨額', '營業毛利毛損'],
            'operating_profit_ytd_k': ['營業利益損失', '營業利益'],
            'net_income_ytd_k': ['本期淨利淨損', '本期稅後淨利', '稅後淨利淨損'],
            'basic_eps_ytd': ['基本每股盈餘元', '基本每股盈餘'],
            'diluted_eps_ytd': ['稀釋每股盈餘元', '稀釋每股盈餘'],
        } if kind == 'income' else {
            'operating_cashflow_ytd_k': ['營業活動之淨現金流入流出', '營業活動淨現金流入流出',
                                         '營業活動之淨現金流量', '營業活動現金流量'],
            'capex_ytd_k': ['取得不動產廠房及設備', '購置不動產廠房及設備'],
        })
        selected = {field: column(cols, aliases) for field, aliases in fields.items()}
        required = 'basic_eps_ytd' if kind == 'income' else 'operating_cashflow_ytd_k'
        if selected[required] is None:
            continue
        for _, series in frame.iterrows():
            code = str(series[code_col]).strip()
            if not re.fullmatch(r'\d{4}', code) or code in found:
                continue
            row = {'code': code, 'name': str(series[name_col]).strip() if name_col else '',
                   'market': market, 'period': f'{year}-Q{quarter}',
                   'source': MOPS + KINDS[kind],
                   'unit': 'NTD_thousands_except_EPS', 'company_PIT_verified': False,
                   'year_to_date_values': True}
            row.update({f: num(series[c]) if c else None for f, c in selected.items()})
            if row[required] is not None:
                found[code] = row
    return sorted(found.values(), key=lambda r: r['code'])


def allowed_end(asof):
    # Conservative statutory deadline proxies, not company-specific publication timestamps.
    pairs = []
    for y in range(asof.year - 3, asof.year + 1):
        pairs.extend([(dt.date(y, 5, 16), y, 1), (dt.date(y, 8, 16), y, 2),
                      (dt.date(y, 11, 16), y, 3), (dt.date(y + 1, 4, 2), y, 4)])
    return max((y, q) for release, y, q in pairs if release <= asof)



def latest_completed_quarter(asof):
    """The latest quarter which has ENDED, irrespective of statutory filing deadline."""
    if asof.month in (1, 2, 3):
        return asof.year - 1, 4
    return asof.year, (asof.month - 1) // 3


def early_quarter_candidate(asof):
    """Do not change the full-market eligible period on a single early issuer report."""
    last=latest_completed_quarter(asof)
    return last if last > allowed_end(asof) else None


def early_watch_9802(asof, offline=False):
    """Read official early quarterly issuer data without changing market-wide modeling vintage.

    One early issuer's report cannot stand in for full-market quarterly coverage or
    company-specific original filing PIT; this only creates a research watch receipt.
    """
    candidate=early_quarter_candidate(asof)
    if candidate is None or offline:
        return dict(status='NO_NEW_PREDEADLINE_QUARTER_TO_PROBE',period=None)
    y,q=candidate
    label=f'{y}-Q{q}'
    source=MOPS+KINDS['income']
    try:
        raw=download(y,q,'TWSE','income')
        # MOPS can return a syntactically valid older-period table for a future query.
        from html import unescape
        plain=unescape(re.sub('<[^>]+>',' ',raw.decode('utf-8-sig',errors='replace')))
        normalized=''.join(plain.split())
        season={1:'[一1]',2:'[二2]',3:'[三3]',4:'[四4]'}[q]
        if not re.search('第'+season+'季',normalized):
            raise ValueError('SOURCE_QUARTER_TITLE_NOT_CONFIRMED')
        rows=parse(raw,'income',y,q,'TWSE')
        row=next((x for x in rows if x['code']=='9802'),None)
        if row is None:
            return dict(status='9802_NOT_YET_IN_OFFICIAL_QUARTER_TABLE',period=label)
        revenue=num(row.get('revenue_ytd_k'))
        gross=num(row.get('gross_profit_ytd_k'))
        if revenue is None or revenue<=0 or gross is None:
            raise ValueError('9802_REVENUE_OR_GROSS_PROFIT_INCOMPLETE')
        q3_gm=None
        last=periods((y,q),2)[0]
        previous=f'{last[0]}-Q{last[1]}'
        prior=load(FIN/previous/'TWSE_income.json',previous,'TWSE','income')
        prior_row=next((x for x in prior['rows'] if x['code']=='9802'),None) if prior else None
        if prior_row and all(num(prior_row.get(k)) is not None for k in ('revenue_ytd_k','gross_profit_ytd_k')):
            delta_revenue=revenue-num(prior_row['revenue_ytd_k'])
            delta_gross=gross-num(prior_row['gross_profit_ytd_k'])
            if delta_revenue>0:
                q3_gm=round(100*delta_gross/delta_revenue,4)
        receipt=dict(schema='V885_EARLY_ISSUER_FINANCIAL_RESEARCH_V1',
                     code='9802',market='TWSE',financial_period=label,
                     source_url=source,original_html_sha256=hashlib.sha256(raw).hexdigest(),
                     quarter_title_checked=True,issuer_filing_PIT_verified=False,
                     report_year_independently_verified=False,
                     captured_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                     published_at_original_company_timestamp=None,
                     observed_income_row=row,
                     year_to_date_gross_margin_pct=round(100*gross/revenue,4),
                     new_quarter_gross_margin_pct=q3_gm,
                     status='EARLY_OFFICIAL_TABLE_RESEARCH_ONLY_NOT_FORMAL_MODEL_INPUT',
                     full_market_quarter_eligibility_unchanged=True,
                     must_not_set_certification_gate_pass=True)
        loc=FIN/'early_watch'/f'9802_{y}-Q{q}.json'
        loc.parent.mkdir(parents=True,exist_ok=True)
        # Do not churn the repo when the observed source HTML and financial row are unchanged.
        previous_receipt=json.loads(loc.read_text(encoding='utf-8')) if loc.exists() else None
        if previous_receipt and previous_receipt.get('observed_income_row')==row and previous_receipt.get('financial_period')==label:
            return dict(status='ALREADY_OBSERVED_NO_NEW_FINANCIAL_DATA',period=label,
                        latest_observed_gross_margin_pct=q3_gm)
        rawpath=RAW/'early_watch'/label/'TWSE_income_9802.html'
        rawpath.parent.mkdir(parents=True,exist_ok=True)
        rawpath.write_bytes(raw)
        dump(loc,receipt)
        return dict(status='NEW_EARLY_9802_FINANCIAL_NUMBERS_RESEARCH_ONLY',period=label,
                    latest_observed_gross_margin_pct=q3_gm)
    except Exception as exc:
        # Source blocks or incomplete filings do not halt existing complete-quarter collector.
        return dict(status='EARLY_9802_SOURCE_PENDING_RETRY',
                    period=label,error=f'{type(exc).__name__}:{str(exc)[:180]}')


def periods(end, count=8):
    y, q = end
    result = []
    for _ in range(count):
        result.append((y, q))
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return result[::-1]


def download(y, q, market, kind):
    form = urllib.parse.urlencode({'encodeURIComponent': 1, 'step': 1, 'firstin': 1,
                                   'off': 1, 'isQuery': 'Y', 'TYPEK': MARKETS[market],
                                   'year': y - 1911, 'season': f'{q:02d}'}).encode()
    req = urllib.request.Request(MOPS + KINDS[kind], data=form,
                                 headers={'User-Agent': 'Mozilla/5.0 (public data archival)'})
    with urllib.request.urlopen(req, timeout=45) as res:
        data = res.read(15_000_001)
    if not 500 < len(data) <= 15_000_000 or b'captcha' in data[:5000].lower():
        raise ValueError('Invalid/blocked/oversized MOPS response')
    return data


def dump(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def load(path, label, market, kind):
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    rows = obj.get('rows', [])
    if (obj.get('period'), obj.get('market'), obj.get('kind')) != (label, market, kind):
        return None
    if len(rows) < 100 or len({r['code'] for r in rows}) != len(rows):
        return None
    return obj


def revenue_rows():
    try:
        m = json.loads((OUT / 'latest_manifest.json').read_text(encoding='utf-8'))
        shards = m['shards']
        rows = []
        for s in shards:
            path = pathlib.Path(s['path'])
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != s['sha256']:
                raise ValueError('Monthly revenue hash mismatch: ' + str(path))
            rows.extend(json.loads(data))
        return {str(row['code']): row for row in rows}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('NO_VERIFIED_REVENUE', exc, flush=True)
        return {}


def estimate(code, points, r):
    # Illustrative EPS scenarios, NOT investor-ready forward valuations.
    periods_needed = ('2025-Q2', '2025-Q4', '2026-Q2')
    eps = [points.get((label, 'income'), {}).get('basic_eps_ytd') for label in periods_needed]
    base = {'code': code, 'formal_Aplus': False, 'formal_Aplusplus': False,
            'rating': '資料不足', 'eps_2027_base': None,
            'unverified_gates': ['company-specific PIT', '8Q margins and conversion',
                                 'OCF/FCF and CAPEX', 'diluted share count',
                                 'sector-consistent PE', 'independent price/valuation',
                                 'management and industry validation']}
    if any(x is None for x in eps):
        return base
    ytd_yoy = num((r or {}).get('ytd_yoy_pct'))
    proxy = eps[1] - eps[0] + eps[2]
    if proxy <= 0 or ytd_yoy is None:
        return dict(base, eps_2026_proxy=round(proxy, 3))
    growth = max(-0.15, min(0.20, ytd_yoy / 200))
    return dict(base, rating='估值待驗', eps_2025_fy_reported=round(eps[1], 3),
                eps_2026_proxy=round(proxy, 3),
                revenue_ytd_yoy_pct=ytd_yoy,
                eps_2027_bear=round(proxy * 0.8, 3),
                eps_2027_base=round(proxy * (1 + growth), 3),
                eps_2027_bull=round(proxy * 1.35, 3),
                eps_model='EPS2026 proxy = EPS2025 FY - EPS2025 H1 + EPS2026 H1; 2027 base growth = 0.5*YTD revenue YoY, clamped -15%..20%',
                model_warning='Proxy uses EPS subtraction despite weighted-share variation; experimental only; NOT a target price.')


def scan(asof, max_fetches=12, offline=False):
    end = allowed_end(asof)
    want = periods(end)
    tasks = [(y, q, market, kind) for y, q in want[::-1] for market in MARKETS for kind in KINDS]
    count, saved, errors = 0, 0, []
    for y, q, market, kind in tasks:
        label = f'{y}-Q{q}'
        path = FIN / label / f'{market}_{kind}.json'
        if load(path, label, market, kind) or offline or count >= max_fetches:
            continue
        count += 1
        try:
            body = download(y, q, market, kind)
            data = parse(body, kind, y, q, market)
            if len(data) < 100:
                raise ValueError(f'Only {len(data)} parsed rows; refusing layout mismatch')
            rawpath = RAW / label / f'{market}_{kind}.html'
            rawpath.parent.mkdir(parents=True, exist_ok=True)
            rawpath.write_bytes(body)
            dump(path, {'period': label, 'kind': kind, 'market': market,
                        'capture_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                        'raw_sha256': hashlib.sha256(body).hexdigest(),
                        'company_PIT_verified': False, 'rows': data})
            saved += 1
            print('CAPTURED', label, market, kind, len(data), flush=True)
        except Exception as exc:
            errors.append({'period': label, 'market': market, 'kind': kind, 'error': str(exc)})
            print('CAPTURE_FAILED', label, market, kind, exc, flush=True)
        time.sleep(1.4)
    observations, loaded = {}, []
    for y, q in want:
        label = f'{y}-Q{q}'
        for market in MARKETS:
            for kind in KINDS:
                cached = load(FIN / label / f'{market}_{kind}.json', label, market, kind)
                if not cached:
                    continue
                loaded.append(f'{label}/{market}/{kind}')
                for record in cached['rows']:
                    observations.setdefault((market, record['code']), {})[(label, kind)] = record
    revenue = revenue_rows()
    results = []
    for (market, code), rows in observations.items():
        est = estimate(code, rows, revenue.get(code))
        est['market'] = market
        est['income_quarters'] = sum((f'{y}-Q{q}', 'income') in rows for y, q in want)
        est['cashflow_quarters'] = sum((f'{y}-Q{q}', 'cashflow') in rows for y, q in want)
        cfo = rows.get((f'{end[0]}-Q{end[1]}', 'cashflow'))
        est['latest_cfo_ytd_k'] = cfo.get('operating_cashflow_ytd_k') if cfo else None
        # All issuer PIT, capex/FCF, management and share-dilution checks remain blocked.
        results.append(est)
    preview = sorted(results, key=lambda r: (r['eps_2027_base'] is not None,
                                               r['eps_2027_base'] or 0), reverse=True)[:30]
    summary = {'model': 'V8.7.7 official financial foundation', 'asof_taipei': asof.isoformat(),
               'last_eligible_quarter': f'{end[0]}-Q{end[1]}',
               'created_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
               'expected_market_quarter_statement_batches': len(tasks),
               'verified_batches': len(loaded), 'missing_batches': len(tasks) - len(loaded),
               'new_batches_this_run': saved, 'requests_attempted': count,
               'failures': errors, 'batches': loaded,
               'companies_with_some_data': len(results),
               'companies_with_full_8Q_income': sum(r['income_quarters'] == 8 for r in results),
               'formal_Aplus_count': 0, 'formal_Aplusplus_count': 0,
               'status': 'ALL_BATCHES_PRESENT_UNAUDITED' if len(loaded) == len(tasks) else 'PARTIAL',
               'disclaimer': 'NO FORMAL A+: issuer PIT dates, OCF/FCF, dilution, sector PE and management checks are not complete. EPS projections are illustrative only.',
               'preview_not_ranked_by_return': preview}
    dump(FIN / 'latest_scan.json', summary)
    return summary


def self_test():
    sample = '''<table><thead><tr><th>公司代號</th><th>公司名稱</th><th>營業收入</th>
    <th>營業毛利（毛損）</th><th>營業利益（損失）</th><th>本期淨利（淨損）</th>
    <th>基本每股盈餘（元）</th></tr></thead><tbody><tr><td>9802</td><td>鈺齊</td>
    <td>1,234</td><td>234</td><td>123</td><td>(20)</td><td>0.26</td></tr></tbody></table>'''
    rows = parse(sample.encode(), 'income', 2026, 2, 'TWSE')
    assert len(rows) == 1, rows
    assert rows[0]['basic_eps_ytd'] == 0.26 and rows[0]['net_income_ytd_k'] == -20
    d = {('2025-Q2', 'income'): {'basic_eps_ytd': 2.0},
         ('2025-Q4', 'income'): {'basic_eps_ytd': 5.0},
         ('2026-Q2', 'income'): {'basic_eps_ytd': 2.5}}
    r = estimate('9802', d, {'ytd_yoy_pct': '20'})
    assert r['eps_2026_proxy'] == 5.5 and r['eps_2027_base'] == 6.05
    assert not r['formal_Aplus']
    assert allowed_end(dt.date(2026, 10, 17)) == (2026, 2)
    assert early_quarter_candidate(dt.date(2026, 10, 19)) == (2026, 3)
    assert early_quarter_candidate(dt.date(2026, 11, 16)) is None
    assert early_quarter_candidate(dt.date(2026, 8, 10)) is None
    assert latest_completed_quarter(dt.date(2027, 1, 5)) == (2026, 4)
    assert len(periods((2026, 2))) == 8
    print('SELF_TEST_OK: 8Q, MOPS HTML, negative numbers, EPS scenario, fail-closed A+')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--self-test', action='store_true')
    p.add_argument('--offline', action='store_true')
    p.add_argument('--asof', help='YYYY-MM-DD in Taipei')
    p.add_argument('--max-fetches', type=int, default=12)
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    asof = dt.date.fromisoformat(args.asof) if args.asof else dt.datetime.now(TZ).date()
    if asof > dt.datetime.now(TZ).date() or not 0 <= args.max_fetches <= 40:
        p.error('No future asof; max-fetches must be 0..40')
    early_result = early_watch_9802(asof, args.offline)
    print('EARLY_9802_Q3_WATCH',json.dumps(early_result,ensure_ascii=False))
    result = scan(asof, args.max_fetches, args.offline)
    print(json.dumps({k: result[k] for k in ('status', 'verified_batches', 'missing_batches',
                                            'new_batches_this_run', 'formal_Aplus_count')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
