"""Dated issuer earnings events, reconciled against archived original PDF bytes.

Research may use a company self-report without calling it an audited quarter.
Unsupported layouts and changed documents remain explicit blockers. No signed
quality certificate is manufactured by this module.
"""
import hashlib
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
                facts = parse_press(reader(original))
                event = dict(code=code, financial_period=period, prior_period="2025-Q3",
                             source_kind="ISSUER_SELF_REPORTED_UNAUDITED", available_at=doc["captured_at_utc"],
                             source_url=url, archive_path=doc["archive_path"], source_sha256=doc["sha256"],
                             extraction_recipe=RECIPE, document_page=2, **facts,
                             original_numeric_table_reconciled=True,
                             historical_issuer_publication_PIT_verified=False,
                             formal_quality_pass=False)
                event["event_sha256"] = digest(event)
                if code in events and events[code]["event_sha256"] != event["event_sha256"]:
                    raise ValueError("EARNINGS_MULTIPLE_ORIGINAL_VERSIONS_REVIEW_REQUIRED")
                events[code] = event
                states[code] = dict(status="NEW_ORIGINAL_EARNINGS_RECONCILED", period=period,
                                    event_sha256=event["event_sha256"], blocks_current_decision=False)
        except (ValueError, KeyError, OSError, TypeError, ImportError) as exc:
            events.pop(code, None)
            states[code] = dict(status="NEW_EARNINGS_REVIEW_BLOCKED", reason=str(exc),
                                blocks_current_decision=True)
    return events, states
