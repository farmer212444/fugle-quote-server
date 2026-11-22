"""Capture original TWSE HTML for dated 0050 split/dividend notices.

Retrospectively downloading a dated notice is *not* proof the same bytes were
publicly available at its displayed publication timestamp. This module never
emits a certified PIT feature, adjusted return, backtest or investment signal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlparse, urlencode
from urllib.request import Request, urlopen

SCHEMA = "ALPHAMAX_0050_RETROSPECTIVE_NOTICE_RECEIPTS_V1"
BASE = "https://www.twse.com.tw/zh/ETFortune/announcement"
# One official retrospective filing for each known 2025/26 split/dividend event.
# Dates/amounts are references to reconcile, not invented source timestamps.
NOTICES = (
    ("split_request_20250509", "20250509", "other", "split", None, None, None),
    ("split_final_20250617", "20250617", "other", "split", None, None, None),
    ("dividend_20250115", "20250115", "distribution", "distribution", "114/01/17", "114/02/20", "2.7"),
    ("dividend_20250717", "20250717", "distribution", "distribution", "114/07/21", "114/08/08", "0.36"),
    ("dividend_20260120", "20260120", "distribution", "distribution", "115/01/22", "115/02/11", "1"),
    ("dividend_20260717", "20260717", "all", "distribution", "115/07/21", "115/08/10", "0.6"),
)


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def _url(day, kind):
    return BASE + "?" + urlencode({
        "company": "A00005", "date": day, "fund": "0050",
        "seq": "1", "type": kind,
    })


def _get(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; official-research-archive)",
                                 "Accept": "text/html,application/xhtml+xml"})
    with urlopen(req, timeout=25) as resp:
        host = urlparse(resp.url).hostname
        if resp.status != 200 or host not in ("www.twse.com.tw", "wwwc.twse.com.tw"):
            raise ValueError("TWSE_NOTICE_NOT_FROM_OFFICIAL_HOST")
        raw = resp.read(2_000_001)
    if len(raw) < 200 or len(raw) > 2_000_000 or b"<html" not in raw[:500].lower():
        raise ValueError("TWSE_NOTICE_UNEXPECTED_HTML_PAYLOAD")
    return raw


def parse_notice(raw, event):
    """Validate exact pinned issuer, speaker's date, event type and event economics."""
    if not isinstance(raw, bytes) or len(raw) > 2_000_000:
        raise ValueError("NOTICE_BYTES_INVALID")
    p = _VisibleText()
    try:
        p.feed(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("NOTICE_ENCODING_INVALID") from exc
    compact = re.sub(r"\s+", "", "".join(p.parts))
    event_id, day, _typ, kind, ex_date, pay_date, cash = event
    if ("0050" not in compact or
            not any(name in compact for name in ("元大台灣卓越50", "元大台灣50"))):
        raise ValueError("NOTICE_WRONG_SECURITY")
    report_day = f"{day[:4]}.{day[4:6]}.{day[6:]}"
    if "發言日期" + report_day not in compact:
        raise ValueError("NOTICE_REPORT_DATE_NOT_MATCHED")
    match = re.search(r"發言時間(\d{2}:\d{2}:\d{2})", compact)
    if not match:
        raise ValueError("NOTICE_REPORT_TIME_MISSING")
    reported_at = datetime.fromisoformat(day[:4] + "-" + day[4:6] + "-" +
                                        day[6:] + "T" + match.group(1) + "+08:00")
    if kind == "split":
        if "分割" not in compact or not re.search(r"(?:分割比率.{0,80}?4|4[：:]1)", compact):
            raise ValueError("NOTICE_SPLIT_RATIO_NOT_CONFIRMED")
        if not (("114年6月10日" in compact or "114/06/10" in compact)
                and ("114年6月18日" in compact or "114/06/18" in compact)):
            raise ValueError("NOTICE_SPLIT_TRADING_DATES_NOT_CONFIRMED")
    else:
        if "每受益權單位" not in compact or "收益分配" not in compact:
            raise ValueError("NOTICE_DISTRIBUTION_SUBJECT_NOT_CONFIRMED")
        amounts = re.findall(r"每受益權單位(?:實際)?配發金額(?:為|[:：])新臺幣([0-9]+(?:\.[0-9]+)?)元", compact)
        if not amounts or not any(float(x) == float(cash) for x in amounts):
            raise ValueError("NOTICE_DISTRIBUTION_CASH_NOT_CONFIRMED")
        for field, value in (("EX_DATE", ex_date), ("PAY_DATE", pay_date)):
            roc = value.replace("/", "年", 1).replace("/", "月", 1) + "日"
            if value not in compact and roc not in compact:
                raise ValueError("NOTICE_DISTRIBUTION_" + field + "_NOT_CONFIRMED")
    return {
        "event": event_id,
        "reported_at_taipei": reported_at.isoformat(),
        "reported_at_is_recovered_page_field_not_archived_asof_receipt": True,
        "issuer": "0050",
        "source_type": "TWSE_RETROSPECTIVE_OFFICIAL_ANNOUNCEMENT",
        "event_economics_from_known_reference_matched": True,
    }


def capture_notices(output, fetch=None, captured_at=None):
    """Persist exact received bytes with SHA receipts; never fabricate a missing notice."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    fetch = fetch or _get
    stamp = captured_at or datetime.now(timezone.utc).isoformat()
    events = []
    for event in NOTICES:
        event_id, day, typ = event[:3]
        url = _url(day, typ)
        entry = {"event": event_id, "url": url}
        try:
            raw = fetch(url)
            parsed = parse_notice(raw, event)
            path = output / "originals" / (event_id + "-" + sha256(raw).hexdigest() + ".html")
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.read_bytes() != raw:
                raise ValueError("ORIGINAL_NOTICE_ARCHIVE_CONFLICT")
            path.write_bytes(raw)
            entry.update(parsed)
            entry.update({
                "status": "RETROSPECTIVE_NOTICE_BYTES_AND_FIELDS_MATCHED",
                "original_sha256": sha256(raw).hexdigest(),
                "original_relative_path": path.relative_to(output).as_posix(),
                "bytes": len(raw),
                "captured_at_utc": stamp,
                "independent_asof_publication_snapshot_verified": False,
            })
        except (ValueError, OSError, TimeoutError) as exc:
            entry.update({"status": "BLOCKED_NOTICE_CAPTURE_OR_VALIDATION",
                          "reason": str(exc)[:180]})
        events.append(entry)
    complete = all(e["status"] == "RETROSPECTIVE_NOTICE_BYTES_AND_FIELDS_MATCHED"
                   for e in events)
    report = {
        "schema": SCHEMA, "issuer": "0050", "captured_at_utc": stamp,
        "status": ("RETROSPECTIVE_NOTICE_RECEIPTS_CAPTURED_NOT_PIT"
                   if complete else "BLOCKED_0050_NOTICE_SOURCE_INCOMPLETE"),
        "attempted": len(events),
        "receipt_verified_count": sum(e["status"] == "RETROSPECTIVE_NOTICE_BYTES_AND_FIELDS_MATCHED"
                                      for e in events),
        "events": events,
        "asof_publication_snapshot_verified": False,
        "investor_total_return_verified": False,
        "split_and_dividend_adjusted": False,
        "matured_12m_costed_oos_verified": 0,
        "formal_a_plus": False,
        "critical_notice": "Original bytes recovered today are NOT a contemporaneously "
                           "archived as-of release; payment proof and holdings/split "
                           "adjustment, issuer PIT master and verified OOS remain BLOCKED.",
    }
    (output / "capture-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return report
