"""Dated issuer earnings events, reconciled against archived original PDF bytes.

Research may use a company self-report without calling it an audited quarter.
Unsupported layouts and changed documents remain explicit blockers. No signed
quality certificate is manufactured by this module.
"""
import hashlib
import copy
import json
import math
import re
from pathlib import Path
from urllib.parse import urlparse

from .evidence import timestamp
from .math import quarter_key

RECIPE = "9802_2026Q3_ISSUER_PRESS_TABLE_V1"
FIELDS = (
    ("revenue_k", "合併營收"), ("gross_profit_k", "營業毛利"),
    ("opex_k", "營業費用"), ("operating_profit_k", "營業利益"),
    ("nonoperating_k", "營業外收支"), ("pretax_profit_k", "稅前淨利"),
    ("net_income_k", "稅後淨利"), ("parent_net_income_k", "歸屬母公司稅後淨利"),
    ("basic_eps", "稅後EPS（元）"),
)


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def pdf_text(path):
    import pymupdf
    with pymupdf.open(path) as document:
        return [page.get_text() for page in document]


def parse_press(pages):
    """One explicitly supported table, with all eight column positions checked."""
    if len(pages) != 2:
        raise ValueError("EARNINGS_PDF_PAGE_COUNT_CHANGED")
    joined = "".join(pages)
    compact = re.sub(r"\s+", "", joined)
    if not all(x in compact for x in ("鈺齊國際(9802)2026年第三季自結財報新聞稿",
                                      "新台幣仟元", "2026/Q3", "2025/Q3")):
        raise ValueError("EARNINGS_ISSUER_PERIOD_OR_UNIT_NOT_MATCHED")
    table = re.sub(r"\s+", " ", pages[1]).strip()
    columns = {}
    for i, (key, label) in enumerate(FIELDS):
        end = FIELDS[i + 1][1] if i + 1 < len(FIELDS) else "業外匯兌評價影響數"
        match = re.search(re.escape(label) + r"\s+(.*?)\s+" + re.escape(end), table)
        if not match:
            raise ValueError("EARNINGS_TABLE_LABEL_MISSING_" + key)
        tokens = match[1].split()
        if len(tokens) != 8:
            raise ValueError("EARNINGS_TABLE_COLUMN_COUNT_" + key)
        values = []
        for token in tokens:
            if token == "-":
                values.append(None)
                continue
            if not re.fullmatch(r"\(?-?[\d,]+(?:\.\d+)?\)?", token):
                raise ValueError("EARNINGS_TABLE_NUMBER_INVALID_" + key)
            value = float(token.replace(",", "").replace("(", "-").replace(")", ""))
            if not math.isfinite(value):
                raise ValueError("EARNINGS_NUMBER_NOT_FINITE")
            values.append(value)
        columns[key] = values
    current = {key: values[3] for key, values in columns.items()}
    prior = {key: values[4] for key, values in columns.items()}
    single = {key: values[0] for key, values in columns.items()}
    for facts in (current, prior, single):
        if any(v is None for v in facts.values()) or facts["revenue_k"] <= 0:
            raise ValueError("EARNINGS_REQUIRED_FACT_MISSING")
        if abs(facts["gross_profit_k"] - facts["opex_k"] - facts["operating_profit_k"]) > 1:
            raise ValueError("EARNINGS_OPERATING_RECONCILIATION")
        if abs(facts["operating_profit_k"] + facts["nonoperating_k"] - facts["pretax_profit_k"]) > 1:
            raise ValueError("EARNINGS_PRETAX_RECONCILIATION")
        if not -1 <= facts["gross_profit_k"] / facts["revenue_k"] <= 1:
            raise ValueError("EARNINGS_MARGIN_IMPLAUSIBLE")
    return dict(current=current, prior=prior, single_quarter=single)


def press_text_sha256(pages):
    return digest([re.sub(r"\s+", " ", page).strip() for page in pages])


def _press_receipt(event):
    return dict(source_sha256=event['source_sha256'],source_url=event['source_url'],
                archive_path=event['archive_path'],bytes=event['source_bytes'],
                captured_at=event['source_captured_at'])


def reconcile_press_versions(root,previous,candidate,cutoff):
    """Admit only exact original files covered by a dated full-content review."""
    path=root/'evidence/v880/earnings_version_reviews/9802_2026-Q3.json'
    if not path.is_file():raise ValueError('EARNINGS_MULTIPLE_ORIGINAL_VERSIONS_REVIEW_REQUIRED')
    raw=path.read_bytes();review=json.loads(raw)
    if (review.get('schema')!='ISSUER_EARNINGS_VERSION_REVIEW_V1' or
        review.get('issuer')!='9802' or review.get('financial_period')!='2026-Q3' or
        review.get('extraction_recipe')!=RECIPE or
        review.get('decision')!='EQUIVALENT_FINANCIAL_CONTENT_REVIEWED_COLOUR_CHANGE_ONLY' or
        review.get('full_two_page_text_and_table_reviewed') is not True or
        review.get('formal_quality_pass') is not False or
        review.get('historical_issuer_publication_PIT_verified') is not False):
        raise ValueError('EARNINGS_VERSION_REVIEW_IDENTITY_OR_SCOPE_INVALID')
    reviewed=timestamp(review['reviewed_at'])
    if reviewed>cutoff:raise ValueError('EARNINGS_VERSION_REVIEW_FROM_FUTURE')
    versions=review['versions'];allowed={v['sha256']:v for v in versions}
    if len(allowed)!=2 or len(versions)!=2 or review['canonical_source_sha256'] not in allowed:
        raise ValueError('EARNINGS_VERSION_REVIEW_VERSION_SET_INVALID')
    for event in (previous,candidate):
        if (event['code']!='9802' or event['financial_period']!='2026-Q3' or
            event['extraction_recipe']!=RECIPE or
            event.get('normalized_press_text_sha256')!=review['normalized_all_pages_sha256'] or
            event.get('parsed_facts_sha256')!=review['parsed_facts_sha256']):
            raise ValueError('EARNINGS_VERSION_REVIEW_CONTENT_MISMATCH')
    receipts=previous.get('equivalent_originals',[_press_receipt(previous)])+[_press_receipt(candidate)]
    unique={}
    for receipt in receipts:
        version=allowed.get(receipt['source_sha256'])
        if version is None or any(receipt[k]!=version[v] for k,v in
            (('source_url','source_url'),('archive_path','archive_path'),('bytes','bytes'))):
            raise ValueError('EARNINGS_UNREVIEWED_ORIGINAL_VERSION')
        if timestamp(receipt['captured_at'])>cutoff:raise ValueError('EARNINGS_VERSION_CAPTURE_FROM_FUTURE')
        old=unique.get(receipt['source_sha256'])
        if old is None or timestamp(receipt['captured_at'])<timestamp(old['captured_at']):
            unique[receipt['source_sha256']]=receipt
    if set(unique)!=set(allowed):raise ValueError('EARNINGS_VERSION_REVIEW_VERSION_SET_MISMATCH')
    canonical=review['canonical_source_sha256']
    selected=previous if previous['source_sha256']==canonical else candidate
    event=copy.deepcopy(selected);event.pop('event_sha256',None)
    event['equivalent_originals']=[unique[key] for key in sorted(unique)]
    event['source_version_review']=dict(archive_path=path.relative_to(root).as_posix(),
        sha256=hashlib.sha256(raw).hexdigest(),reviewed_at=review['reviewed_at'],decision=review['decision'])
    # Do not backdate the admission to an earlier issuer capture.
    event['available_at']=max([reviewed]+[timestamp(r['captured_at']) for r in unique.values()]).isoformat()
    event['event_sha256']=digest(event)
    return event


def condensed_event(root, code, doc, cutoff, financial_period, reader):
    """Issuer-specific adapter; a rounded summary never certifies full notes."""
    from .tsmc_earnings import RECIPE as TSMC_RECIPE, SOURCE_KIND, parse_tsmc
    period = doc['financial_period']
    if quarter_key(period) <= quarter_key(financial_period):
        return None, None
    if timestamp(doc['captured_at_utc']) > cutoff:
        return None, dict(status='FUTURE_CAPTURE_NOT_USED', blocks_current_decision=False)
    if code != '2330' or period != '2026-Q3' or doc.get('extraction_recipe') != TSMC_RECIPE:
        raise ValueError('NEW_ISSUER_EARNINGS_EXTRACTION_RECIPE_REQUIRED')
    url = doc['source_url']
    if urlparse(url).scheme != 'https' or urlparse(url).hostname != 'investor.tsmc.com':
        raise ValueError('EARNINGS_PUBLISHER_HOST_MISMATCH')
    rel = Path(doc['archive_path'])
    original = (root / rel).resolve()
    if rel.is_absolute() or '..' in rel.parts or root not in original.parents:
        raise ValueError('EARNINGS_UNSAFE_ARCHIVE_PATH')
    raw = original.read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc.get('sha256') or len(raw) != doc.get('bytes'):
        raise ValueError('EARNINGS_ORIGINAL_BYTES_MISMATCH')
    if not raw.startswith(b'%PDF-'):
        raise ValueError('EARNINGS_NOT_A_PDF')
    facts = parse_tsmc(reader(original))
    event = dict(code=code, financial_period=period, prior_period='2025-Q3',
                 source_kind=SOURCE_KIND, available_at=doc['captured_at_utc'],
                 source_url=url, archive_path=doc['archive_path'], source_sha256=doc['sha256'],
                 extraction_recipe=TSMC_RECIPE, document_pages=[1, 2, 3, 4], **facts,
                 original_numeric_table_reconciled=True,
                 historical_issuer_publication_PIT_verified=False, formal_quality_pass=False)
    event['event_sha256'] = digest(event)
    return event, dict(status='NEW_ORIGINAL_EARNINGS_RECONCILED', period=period,
                       event_sha256=event['event_sha256'], blocks_current_decision=False)


def load_earnings_events(root, asof, financial_period, reader=pdf_text):
    """Return usable original events and per-company failure/isolation records."""
    root = Path(root).resolve()
    cutoff = timestamp(asof)
    events, states = {}, {}
    for path in sorted((root / "evidence/v880/originals").glob("*/manifest.json")):
        code = path.parent.name
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
            if bundle.get("issuer") != code:
                raise ValueError("EARNINGS_ARCHIVE_ISSUER_MISMATCH")
            for doc in bundle.get('documents', []):
                if doc.get('document_kind') != 'quarterly_condensed_financial_statements':
                    continue
                event, state = condensed_event(root, code, doc, cutoff, financial_period, reader)
                if state is not None:
                    states[code] = state
                if event is not None:
                    if code in events and events[code]['event_sha256'] != event['event_sha256']:
                        raise ValueError('EARNINGS_MULTIPLE_ORIGINAL_VERSIONS_REVIEW_REQUIRED')
                    events[code] = event
            documents = [d for d in bundle.get("documents", []) if
                         d.get("document_kind") == "news" and "自結財報" in d.get("title", "")]
            for doc in documents:
                # Later quarterly formal filings supersede this press event.
                if code != "9802" or doc.get("title") != "2026年第三季自結財報新聞稿":
                    title=doc.get('title','')
                    match=re.search(r'(20\d{2})年?第([一二三四])季',title)
                    if match:
                        newer=f"{match[1]}-Q{'一二三四'.index(match[2])+1}"
                        if quarter_key(newer)>quarter_key(financial_period) and timestamp(doc['captured_at_utc'])<=cutoff:
                            raise ValueError('NEW_ISSUER_EARNINGS_EXTRACTION_RECIPE_REQUIRED')
                    continue
                period = "2026-Q3"
                if quarter_key(period) <= quarter_key(financial_period):
                    continue
                captured = timestamp(doc["captured_at_utc"])
                if captured > cutoff:
                    if code not in events:
                        states[code] = dict(status="FUTURE_CAPTURE_NOT_USED", blocks_current_decision=False)
                    continue
                url = doc["source_url"]
                if urlparse(url).scheme != "https" or urlparse(url).hostname != "www.fulgentsun.com":
                    raise ValueError("EARNINGS_PUBLISHER_HOST_MISMATCH")
                rel = Path(doc["archive_path"])
                original = (root / rel).resolve()
                if rel.is_absolute() or ".." in rel.parts or root not in original.parents:
                    raise ValueError("EARNINGS_UNSAFE_ARCHIVE_PATH")
                raw = original.read_bytes()
                if hashlib.sha256(raw).hexdigest() != doc.get("sha256") or len(raw) != doc.get("bytes"):
                    raise ValueError("EARNINGS_ORIGINAL_BYTES_MISMATCH")
                if not raw.startswith(b"%PDF-"):
                    raise ValueError("EARNINGS_NOT_A_PDF")
                pages=reader(original)
                facts = parse_press(pages)
                event = dict(code=code, financial_period=period, prior_period="2025-Q3",
                             source_kind="ISSUER_SELF_REPORTED_UNAUDITED", available_at=doc["captured_at_utc"],
                             source_url=url, archive_path=doc["archive_path"], source_sha256=doc["sha256"],
                             source_bytes=doc['bytes'],source_captured_at=doc['captured_at_utc'],
                             extraction_recipe=RECIPE, document_page=2, **facts,
                             normalized_press_text_sha256=press_text_sha256(pages),parsed_facts_sha256=digest(facts),
                             original_numeric_table_reconciled=True,
                             historical_issuer_publication_PIT_verified=False,
                             formal_quality_pass=False)
                event["event_sha256"] = digest(event)
                if code in events and events[code]["event_sha256"] != event["event_sha256"]:
                    event=reconcile_press_versions(root,events[code],event,cutoff)
                events[code] = event
                states[code] = dict(status="NEW_ORIGINAL_EARNINGS_RECONCILED", period=period,
                                    event_sha256=event["event_sha256"], blocks_current_decision=False,
                                    reviewed_equivalent_original_count=len(event.get('equivalent_originals',[])))
        except (ValueError, KeyError, OSError, TypeError, ImportError) as exc:
            events.pop(code, None)
            states[code] = dict(status="NEW_EARNINGS_REVIEW_BLOCKED", reason=str(exc),
                                blocks_current_decision=True)
    return events, states
