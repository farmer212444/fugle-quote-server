"""Replay partial official early-quarter income tables without promoting sources.

An issuer missing from a partial table is unknown, never zero or proof that it
has not announced results. Prior cashflow, peer and quality reviews stay dated.
"""
import csv
import gzip
import hashlib
import io
import json
import math
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from .evidence import timestamp
from .math import number, quarter_end, quarter_key

FOLDER = 'evidence/v880/early_bulk'
SCHEMA = 'OFFICIAL_EARLY_QUARTER_INCOME_INTAKE_V1'
SOURCE_KIND = 'OFFICIAL_EARLY_QUARTER_BULK_INCOME_RESEARCH'
ANNOUNCEMENT_KIND = 'MOPS_ISSUER_EARNINGS_ANNOUNCEMENT_RESEARCH'
MOPS = 'https://mopsov.twse.com.tw/mops/web/ajax_t05st01'
URLS = {
    'TWSE': 'https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci',
    'TPEX': 'https://mopsfin.twse.com.tw/opendata/t187ap06_O_ci.csv',
}
FIELDS = {
    'revenue_k': '營業收入', 'gross_profit_k': '營業毛利（毛損）淨額',
    'operating_profit_k': '營業利益（損失）', 'pretax_profit_k': '稅前淨利（淨損）',
    'net_income_k': '本期淨利（淨損）',
    'parent_net_income_k': '淨利（淨損）歸屬於母公司業主',
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class HtmlText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ignored = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def announcement(raw, receipt):
    parser = HtmlText()
    parser.feed(raw.decode('utf-8-sig'))
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', ' '.join(parser.parts)))
    code, market = receipt['code'], receipt['market']
    label = '上市公司' if market == 'TWSE' else '上櫃公司'
    require(re.search(re.escape('本資料由(' + label + ')' + code) + r'(?!\d)', text), 'EARLY_ANNOUNCEMENT_ISSUER_MISMATCH')
    window = re.findall(r'起訖日期\(XXX/XX/XX~XXX/XX/XX\):(\d{3})/01/01[~-](\d{3})/(03/31|06/30|09/30|12/31)', text)
    require(len(window) == 1 and window[0][0] == window[0][1], 'EARLY_ANNOUNCEMENT_REPORT_WINDOW_INVALID')
    year, _, end = window[0]
    quarter = {'03/31': 1, '06/30': 2, '09/30': 3, '12/31': 4}[end]
    query = parse_qs(urlsplit(receipt['source_url']).query)
    date = query['spoke_date'][0]
    time = query['spoke_time'][0]
    local_release = timestamp(f'{date[:4]}-{date[4:6]}-{date[6:]}T{time[:2]}:{time[2:4]}:{time[4:]}+08:00')
    require(local_release <= timestamp(receipt['captured_at']), 'EARLY_ANNOUNCEMENT_RELEASE_FROM_FUTURE')
    roc_date = f'{int(date[:4])-1911}/{date[4:6]}/{date[6:]}'
    require('發言日期' in text and roc_date in text and f'{time[:2]}:{time[2:4]}:{time[4:]}' in text,
            'EARLY_ANNOUNCEMENT_RELEASE_IDENTITY_MISMATCH')
    row = {'公司代號': code, '年度': year, '季別': str(quarter),
           '出表日期': timestamp(receipt['captured_at']).astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y%m%d')}
    row['出表日期'] = str(int(row['出表日期'][:4])-1911) + row['出表日期'][4:]
    labels = ['營業收入', '營業毛利', '營業利益', '稅前淨利', '本期淨利', '歸屬於母公司業主', '基本每股盈餘']
    targets = list(FIELDS.values()) + ['基本每股盈餘（元）']
    for index, (label, target) in enumerate(zip(labels, targets), 4):
        match = re.findall(str(index) + r'\.(1月1日累計至本期止.*?)(?=' + str(index+1) + r'\.)', text)
        require(len(match) == 1 and label in match[0] and ('(仟元)' if index < 10 else '(元)') in match[0],
                'EARLY_ANNOUNCEMENT_NUMBERED_FIELD_MISSING_' + str(index))
        value = re.search(r':([\d,]+(?:\.\d+)?|\([\d,]+(?:\.\d+)?\)|-[\d,]+(?:\.\d+)?)$', match[0])
        numeric = number(value[1].replace('(', '-').replace(')', '')) if value else None
        require(numeric is not None, 'EARLY_ANNOUNCEMENT_VALUE_INVALID')
        row[target] = numeric
    row['營業費用'] = row[FIELDS['gross_profit_k']] - row[FIELDS['operating_profit_k']]
    row['營業外收入及支出'] = row[FIELDS['pretax_profit_k']] - row[FIELDS['operating_profit_k']]
    row['所得稅費用（利益）'] = row[FIELDS['pretax_profit_k']] - row[FIELDS['net_income_k']]
    row['淨利（淨損）歸屬於非控制權益'] = row[FIELDS['net_income_k']] - row[FIELDS['parent_net_income_k']]
    facts(row)
    return {code: row}


def parse(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= 8_000_000, 'EARLY_BULK_SIZE_INVALID')
    text = raw.decode('utf-8-sig')
    rows = json.loads(text) if text.lstrip().startswith('[') else list(csv.DictReader(io.StringIO(text)))
    require(isinstance(rows, list) and 0 < len(rows) <= 5000, 'EARLY_BULK_TABLE_INVALID')
    found = {}
    for row in rows:
        code = str(row.get('公司代號', ''))
        require(re.fullmatch(r'\d{4}', code), 'EARLY_BULK_ISSUER_IDENTITY_INVALID')
        require(code not in found, 'EARLY_BULK_DUPLICATE_ISSUER')
        found[code] = row
    return found


def period(row):
    year, q = int(row['年度']), int(row['季別'])
    year = year + 1911 if year < 1911 else year
    require(2000 <= year <= 2100 and 1 <= q <= 4, 'EARLY_BULK_PERIOD_INVALID')
    return f'{year}-Q{q}'


def facts(row):
    result = {}
    for key, label in FIELDS.items():
        raw = row.get(label)
        if key == 'gross_profit_k' and number(raw) is None:
            raw = row.get('營業毛利（毛損）')
        value = None if isinstance(raw, bool) else number(raw)
        require(value is not None and math.isfinite(value), 'EARLY_BULK_FIELD_MISSING_' + key)
        result[key] = value
    require(result['revenue_k'] > 0, 'EARLY_BULK_REVENUE_NONPOSITIVE')
    optional_gaps=[]
    other_operating = number(row.get('其他收益及費損淨額'))
    for label, expected in (
        ('營業費用', result['gross_profit_k'] - result['operating_profit_k'] + (other_operating if other_operating is not None else 0)),
        ('營業外收入及支出', result['pretax_profit_k'] - result['operating_profit_k']),
        ('所得稅費用（利益）', result['pretax_profit_k'] - result['net_income_k']),
        ('淨利（淨損）歸屬於非控制權益', result['net_income_k'] - result['parent_net_income_k']),
    ):
        raw = row.get(label)
        value = None if isinstance(raw, bool) else number(raw)
        if label=='淨利（淨損）歸屬於非控制權益' and (raw is None or str(raw).strip()==''):
            optional_gaps.append('NONCONTROLLING_COMPONENT_UNREPORTED_NOT_VERIFIED_ZERO')
            continue
        require(value is not None and abs(value - expected) <= 1,
                'EARLY_BULK_ACCOUNTING_RECONCILIATION_' + label)
    result['optional_reconciliation_gaps']=optional_gaps
    result['opex_k'] = result['gross_profit_k'] - result['operating_profit_k']
    result['reported_opex_k'] = number(row.get('營業費用'))
    result['other_operating_gains_k'] = other_operating
    result['nonoperating_k'] = result['pretax_profit_k'] - result['operating_profit_k']
    eps = number(row.get('基本每股盈餘（元）'))
    require(eps is not None, 'EARLY_BULK_REPORTED_EPS_MISSING')
    result['basic_eps'] = eps
    return result


def verified_source(root, receipt, cutoff):
    is_announcement = receipt.get('source_kind') == ANNOUNCEMENT_KIND
    if is_announcement:
        url = urlsplit(receipt['source_url'])
        query = parse_qs(url.query)
        require(url.scheme+'://'+url.netloc+url.path == MOPS and not url.fragment
                and query.get('co_id') == [receipt['code']] and query.get('step') == ['2']
                and query.get('TYPEK') == [{'TWSE': 'sii', 'TPEX': 'otc'}[receipt['market']]],
                'EARLY_BULK_UNTRUSTED_SOURCE')
    else:
        require(receipt['source_url'] == URLS[receipt['market']], 'EARLY_BULK_UNTRUSTED_SOURCE')
    require(timestamp(receipt['captured_at']) <= cutoff, 'EARLY_BULK_FUTURE_CAPTURE')
    rel = Path(receipt['archive_path'])
    path = (root / rel).resolve()
    require(not rel.is_absolute() and '..' not in rel.parts and root in path.parents,
            'EARLY_BULK_UNSAFE_ARCHIVE_PATH')
    packed = path.read_bytes()
    require(sha(packed) == receipt['gzip_sha256'], 'EARLY_BULK_GZIP_HASH_MISMATCH')
    # Bound decompression before parsing or trusting the declared byte count.
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        raw = stream.read(8_000_001)
    require(len(raw) <= 8_000_000 and len(raw) == receipt['bytes']
            and sha(raw) == receipt['raw_sha256'], 'EARLY_BULK_ORIGINAL_HASH_MISMATCH')
    return announcement(raw, receipt) if is_announcement else parse(raw)


def load(data, asof):
    root, cutoff = Path(data.root).resolve(), timestamp(asof)
    manifest = root / FOLDER / 'manifest.json'
    if not manifest.is_file():
        return {}, {}
    doc = json.loads(manifest.read_bytes())
    require(doc.get('schema') == SCHEMA and doc.get('formal_quality_pass') is False,
            'EARLY_BULK_MANIFEST_INVALID')
    scope = doc['requested_issuers']
    require(isinstance(scope, list) and 0 < len(scope) <= 2004
            and len({(x['market'], x['code']) for x in scope}) == len(scope),
            'EARLY_BULK_SCOPE_INVALID')
    receipts = doc['captures']
    require(len({r['market'] for r in receipts}) == len(receipts), 'EARLY_BULK_DUPLICATE_MARKET')
    tables, failures = {}, {}
    for receipt in receipts:
        try:
            tables[receipt['market']] = (verified_source(root, receipt, cutoff), receipt)
        except (ValueError, KeyError, OSError, TypeError, EOFError) as exc:
            failures[receipt.get('market')] = str(exc)
    notices, notice_failures = {}, {}
    for receipt in doc.get('announcements', []):
        code = receipt['code']
        try:
            require(code not in notices, 'EARLY_ANNOUNCEMENT_DUPLICATE_ISSUER')
            notices[code] = (verified_source(root, receipt, cutoff)[code], receipt)
        except (ValueError, KeyError, OSError, TypeError, EOFError) as exc:
            notice_failures[code] = str(exc)
    events, states = {}, {}
    for issuer in scope:
        code, market = issuer['code'], issuer['market']
        try:
            if code in notice_failures:
                reason = notice_failures[code]
                states[code] = dict(status=reason, blocks_current_decision=reason != 'EARLY_BULK_FUTURE_CAPTURE')
                continue
            if market in failures:
                reason = failures[market]
                states[code] = dict(status=reason, blocks_current_decision=reason != 'EARLY_BULK_FUTURE_CAPTURE')
                continue
            if market not in tables:
                states[code] = dict(status='EARLY_BULK_MARKET_SOURCE_MISSING', blocks_current_decision=False)
                continue
            table, receipt = tables[market]
            row = table.get(code)
            corroborating_bulk = None
            if code in notices:
                notice_row, notice_receipt = notices[code]
                require(notice_receipt['market'] == market, 'EARLY_ANNOUNCEMENT_MARKET_MISMATCH')
                if row is not None and period(row) == period(notice_row):
                    require(all(abs(facts(row)[k]-facts(notice_row)[k]) <= 1 for k in FIELDS),
                            'EARLY_ANNOUNCEMENT_OFFICIAL_TABLE_CONFLICT')
                    corroborating_bulk = facts(row)
                if row is None or quarter_key(period(notice_row)) >= quarter_key(period(row)):
                    row, receipt = notice_row, notice_receipt
            if row is None:
                states[code] = dict(status='NOT_OBSERVED_IN_PARTIAL_OFFICIAL_TABLE', blocks_current_decision=False,
                                    absence_is_not_zero_or_proof_unannounced=True)
                continue
            latest = period(row)
            if quarter_key(latest) <= quarter_key(data.period):
                states[code] = dict(status='EARLY_BULK_SUPERSEDED_BY_COMPLETE_PERIOD', blocks_current_decision=False)
                continue
            require(quarter_end(latest) <= cutoff.date(), 'EARLY_BULK_FUTURE_PERIOD')
            y, q = quarter_key(latest)
            require((y, q - 1) == quarter_key(data.period), 'EARLY_BULK_NONADJACENT_PERIOD')
            master = data.evidence['master'].get(code, {})
            require(master.get('market') == market and (market, code) in data.history,
                    'EARLY_BULK_MASTER_IDENTITY_MISMATCH')
            stamp = str(row['出表日期'])
            require(re.fullmatch(r'\d{7}', stamp), 'EARLY_BULK_SOURCE_DATE_MISSING')
            date = f'{int(stamp[:3])+1911}-{stamp[3:5]}-{stamp[5:7]}'
            require(timestamp(receipt['captured_at']).astimezone(ZoneInfo('Asia/Taipei')).date().isoformat() >= date,
                    'EARLY_BULK_SOURCE_DATE_FROM_FUTURE')
            current = facts(row)
            if corroborating_bulk:
                current.update({k:corroborating_bulk[k] for k in ('reported_opex_k','other_operating_gains_k')})
                current['optional_reconciliation_gaps']=corroborating_bulk['optional_reconciliation_gaps']
            previous = data.detailed_values((market, code), data.period)
            prior = data.detailed_values((market, code), f'{y-1}-Q{q}')
            for name, values in (('PREVIOUS', previous), ('PRIOR_YEAR', prior)):
                require(values and all(number(values.get(k)) is not None for k in FIELDS),
                        'EARLY_BULK_' + name + '_YTD_COMPONENTS_MISSING')
            # This is an explicitly derived standalone quarter, not a second
            # independent original statement or a published quarterly EPS.
            single = {k: current[k] - previous[k] for k in FIELDS}
            single['nonoperating_k'] = single['pretax_profit_k'] - single['operating_profit_k']
            prior = dict(prior)
            prior['nonoperating_k'] = prior['pretax_profit_k'] - prior['operating_profit_k']
            event = dict(code=code, financial_period=latest, prior_period=f'{y-1}-Q{q}',
                         current=current, prior=prior, single_quarter=single,
                         source_kind=receipt.get('source_kind', SOURCE_KIND), source_url=receipt['source_url'],
                         archive_path=receipt['archive_path'], source_sha256=receipt['raw_sha256'],
                         available_at=receipt['captured_at'], extraction_recipe=SCHEMA,
                         standalone_quarter_derived_by_ytd_difference=True,
                         prior_year_detail_is_not_original_certified=True,
                         original_numeric_table_reconciled=False,
                         historical_issuer_publication_PIT_verified=False, formal_quality_pass=False)
            event['event_sha256'] = sha(json.dumps(event, sort_keys=True, ensure_ascii=False).encode())
            events[code] = event
            states[code] = dict(status='MOPS_ISSUER_ANNOUNCEMENT_RESEARCH_ADMITTED' if code in notices else 'OFFICIAL_PARTIAL_QUARTER_INCOME_RESEARCH_ADMITTED',
                                period=latest, blocks_current_decision=False)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            states[code] = dict(status='EARLY_BULK_ISSUER_RECONCILIATION_REQUIRED',
                                reason=str(exc), blocks_current_decision=True)
    return events, states
