"""Retrospective TWSE delisting events, with explicit source/record caveats.

This is NOT an entire historical universe: a delisting-date table is not
a list of all securities that could be bought at each earlier timestamp.
Historical events reconstructed today were not necessarily knowable on a
past trade date; never add them as historical pre-announcement features.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from alphamax.core import ContractError

SOURCE_HTML = "https://www.twse.com.tw/company/suspendListingCsvAndHtml?lang=zh&type=html"
SOURCE_CSV = "https://www.twse.com.tw/company/suspendListingCsvAndHtml?lang=zh&type=csv"
SOURCES = (SOURCE_CSV, SOURCE_HTML)
TAIPEI = timezone(timedelta(hours=8))
ROC_LONG = re.compile(r"^\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*$")
NUMERIC_DATE = re.compile(r"^\s*(\d{7}|\d{8})\s*$")
CODE_RE = re.compile(r"^\d{4}|\d{6}$")


class _TableParser(HTMLParser):
    """Minimal stdlib HTML extraction; avoids untrusted web JS execution."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None
    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("th", "td") and self._row is not None:
            self._cell = []
    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
    def handle_endtag(self, tag):
        if tag in ("th", "td") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _event_date(value):
    value = str(value).strip()
    match = ROC_LONG.fullmatch(value)
    if match:
        y, m, d = map(int, match.groups())
        y += 1911
    else:
        digits = NUMERIC_DATE.fullmatch(value.replace("/", "").replace("-", ""))
        if not digits:
            raise ContractError("INVALID_DELIST_EVENT_DATE")
        s = digits.group(1)
        if len(s) == 7:
            y, m, d = int(s[:3]) + 1911, int(s[3:5]), int(s[5:])
        else:
            y, m, d = int(s[:4]), int(s[4:6]), int(s[6:])
    try:
        return date(y, m, d).isoformat()
    except ValueError as exc:
        raise ContractError("IMPOSSIBLE_DELIST_EVENT_DATE") from exc


def _parse_rows(raw, url):
    if not isinstance(raw, bytes) or not 40 <= len(raw) <= 10_000_000:
        raise ContractError("INVALID_DELIST_SOURCE_BYTES")
    if url not in SOURCES:
        raise ContractError("UNTRUSTED_DELIST_URL")
    try:
        encoding, text = "utf-8-sig", raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        encoding, text = "cp950", raw.decode("cp950")
    if url == SOURCE_CSV:
        rows = list(csv.reader(io.StringIO(text)))
    else:
        parser = _TableParser()
        parser.feed(text)
        rows = parser.rows
    if not rows:
        raise ContractError("NO_OFFICIAL_DELIST_ROWS")
    return rows, encoding


def parse_twse_delist(raw, url, captured_at_utc, *, min_events=1):
    """Reconstruct historical effective dates only, retaining vintage ambiguity."""
    if type(min_events) is not int or min_events < 1:
        raise ContractError("INVALID_MIN_EVENTS")
    if url not in SOURCES:
        raise ContractError("UNTRUSTED_DELIST_URL")
    try:
        captured = datetime.fromisoformat(captured_at_utc.replace("Z", "+00:00"))
    except (TypeError, AttributeError, ValueError) as exc:
        raise ContractError("BAD_CAPTURE_TIMESTAMP") from exc
    if captured.tzinfo is None:
        raise ContractError("CAPTURE_TIMESTAMP_NEEDS_ZONE")
    local_date = captured.astimezone(TAIPEI).date()
    rows, encoding = _parse_rows(raw, url)
    events, seen, skipped, unexpected = [], set(), 0, []
    for cells in rows:
        fields = [str(x).replace("\ufeff", "").strip() for x in cells]
        # Official columns: termination date, company name, listed code.
        # Ignore known header/title/preamble rows, never infer missing dates.
        if len(fields) < 3 or not fields[0] or not (
            ROC_LONG.fullmatch(fields[0]) or NUMERIC_DATE.fullmatch(
                fields[0].replace("/", "").replace("-", "")
            )
        ):
            skipped += 1
            continue
        effective = _event_date(fields[0])
        name, code = fields[1].strip(), fields[2].strip()
        if not name or not re.fullmatch(r"(?:\d{4}|\d{6})", code):
            unexpected.append({"fields": fields[:3], "reason": "DELIST_IDENTITY_INVALID"})
            continue
        if date.fromisoformat(effective) > local_date:
            raise ContractError("DELIST_EFFECTIVE_DATE_AFTER_CAPTURE")
        key = (code, effective)
        if key in seen:
            raise ContractError("DUPLICATE_DELIST_EVENT")
        seen.add(key)
        events.append({
            "market": "TWSE", "code": code, "company_name": name,
            "event_type": "TERMINATED_LISTING",
            "effective_date": effective,
            "date_source": "OFFICIAL_RETROSPECTIVE_TERMINATION_TABLE",
            "announcement_publication_time_verified": False,
            "original_last_tradable_day_verified": False,
            "corporate_action_settlement_verified": False,
            "security_class_verified": False,
        })
    if unexpected:
        raise ContractError("UNEXPECTED_DELIST_EVENT_ROWS:" + str(len(unexpected)))
    if len(events) < min_events:
        raise ContractError("OFFICIAL_DELIST_EVENTS_BELOW_MINIMUM")
    events.sort(key=lambda x: (x["effective_date"], x["code"]))
    return {
        "schema": "ALPHAMAX_TWSE_DELIST_RECONSTRUCTION_V1",
        "source_url": url,
        "captured_at_utc": captured.astimezone(timezone.utc).isoformat(),
        "raw_sha256": sha256(raw).hexdigest(),
        "raw_bytes": len(raw), "encoding": encoding,
        "total_html_csv_rows": len(rows), "skipped_header_rows": skipped,
        "market": "TWSE", "event_count": len(events),
        "events_4digit": sum(len(x["code"]) == 4 for x in events),
        "events_6digit": sum(len(x["code"]) == 6 for x in events),
        "events_since_2024": sum(x["effective_date"] >= "2024-01-01" for x in events),
        "first_effective_date": events[0]["effective_date"],
        "last_effective_date": events[-1]["effective_date"],
        "events": events,
        "historical_tpex_delistings_included": False,
        "complete_historical_trading_universe_verified": False,
        "historical_event_announcement_PIT_verified": False,
        "investment_certified": False,
    }


def _download(url):
    if url not in SOURCES:
        raise ContractError("UNTRUSTED_DELIST_FETCH")
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (AlphaMax official delist research)"})
    with urlopen(req, timeout=35) as res:
        if res.status != 200:
            raise ContractError("DELIST_HTTP_STATUS_INVALID")
        raw = res.read(10_000_001)
    if len(raw) > 10_000_000:
        raise ContractError("DELIST_DOWNLOAD_TOO_LARGE")
    return raw


def capture_twse_delist(output_dir, *, captured_at_utc=None, downloader=None, min_events=10):
    """Capture original TWSE bytes and audit its retrospective event ledger."""
    try:
        stamp = datetime.now(timezone.utc) if captured_at_utc is None else datetime.fromisoformat(
            captured_at_utc.replace("Z", "+00:00")
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise ContractError("BAD_CAPTURE_TIMESTAMP") from exc
    if stamp.tzinfo is None:
        raise ContractError("CAPTURE_TIMESTAMP_NEEDS_ZONE")
    stamp = stamp.astimezone(timezone.utc).isoformat()
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    attempts = []
    fetch = downloader or _download
    accepted = None
    for url in SOURCES:
        try:
            raw = fetch(url)
            parsed = parse_twse_delist(raw, url, stamp, min_events=min_events)
            name = "twse-delisted-original." + ("csv" if url == SOURCE_CSV else "html")
            (path / name).write_bytes(raw)
            parsed["raw_artifact"] = name
            accepted = parsed
            attempts.append({"url": url, "status": "ACCEPTED"})
            break
        except (ValueError, TypeError, UnicodeError, OSError) as exc:
            attempts.append({"url": url, "status": "REJECTED", "reason": str(exc)[:200]})
    status = ("RETROSPECTIVE_TWSE_EVENTS_RECONSTRUCTED_NOT_PIT"
              if accepted else "BLOCKED_NO_OFFICIAL_TWSE_DELIST_EVENTS")
    report = {
        "status": status, "captured_at_utc": stamp, "attempts": attempts,
        "event_count": accepted["event_count"] if accepted else 0,
        "twse_source_receipt": {k: v for k, v in accepted.items() if k != "events"} if accepted else None,
        "historical_tpex_delistings_included": False,
        "complete_historical_trading_universe_verified": False,
        "historical_announcement_asof_certified": False,
        "investor_total_return_certified": False,
        "investment_certified": False,
        "blockers": [
            "TPEX_HISTORICAL_DELIST_LEDGER_MISSING",
            "LISTING_TERMINATION_DATES_NOT_ANNOUNCEMENT_PIT",
            "HISTORICAL_LISTING_UNIVERSE_NOT_RECONSTRUCTED",
            "MERGER_CASH_STOCK_CONSIDERATION_AND_BANKRUPTCY_LOSS_UNVERIFIED",
            "DIVIDEND_SPLIT_RIGHTS_AND_EFFECTIVE_TRADE_HISTORY_MISSING",
        ],
    }
    if accepted:
        (path / "twse-delisted-events.json").write_text(
            json.dumps(accepted["events"], ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    (path / "capture-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
