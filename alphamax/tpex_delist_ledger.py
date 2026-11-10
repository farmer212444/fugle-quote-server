"""TPEx official terminated-OTC-history source probe, conservative and fail-closed.

A historical web table might include only a company and code; an absence of
the official effective termination date, source publication timestamp, transfer
type or final settlement is a hard blocker for a PIT universe. Never infer
delisting from absence in a current company list or a cessation of quotes.
"""
from __future__ import annotations
from datetime import datetime, date, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from alphamax.core import ContractError

TZ_TAIPEI = timezone(timedelta(hours=8))
OLD_URL = "https://www.tpex.org.tw/web/regular_emerging/deListed/de-listed_companies.php"
NEW_URL = "https://www.tpex.org.tw/www/zh-tw/company/deListed"
WEB_PAGE = "https://www.tpex.org.tw/zh-tw/mainboard/listed/delisted.html"
DATE_SHORT = re.compile(r"^(?:\d{2,3}[/-]\d{1,2}[/-]\d{1,2}|\d{7}|\d{8})$")
CODE = re.compile(r"^\d{4}$")


class _HtmlTables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        if tag == "tr" and self.table is not None:
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []
    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        if tag == "tr" and self.row is not None and self.table is not None:
            if self.row:
                self.table.append(self.row)
            self.row = None
        if tag == "table" and self.table is not None:
            if self.table:
                self.tables.append(self.table)
            self.table = None


def _roc_date(value):
    value = str(value).strip().replace("年", "/").replace("月", "/").replace("日", "")
    value = value.replace("-", "/")
    if not DATE_SHORT.fullmatch(value):
        return None
    parts = value.split("/")
    if len(parts) == 3:
        year, month, day = map(int, parts)
    else:
        year = int(value[:-4])
        month, day = int(value[-4:-2]), int(value[-2:])
    if year < 1911:
        year += 1911
    try:
        return date(year, month, day).isoformat()
    except ValueError as exc:
        raise ContractError("TPEX_DELIST_IMPOSSIBLE_DATE") from exc


def _decode(raw):
    if not isinstance(raw, bytes) or len(raw) < 20 or len(raw) > 20_000_000:
        raise ContractError("TPEX_DELIST_INVALID_SOURCE_BYTES")
    for enc in ("utf-8-sig", "cp950", "big5"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    raise ContractError("TPEX_DELIST_UNREADABLE_RESPONSE")


def parse_tpex_html(raw, source_url, captured_at_utc):
    """Capture only explicit history rows; missing dates are a visible deficit."""
    if source_url not in (OLD_URL, WEB_PAGE):
        raise ContractError("TPEX_DELIST_UNTRUSTED_HTML_SOURCE")
    try:
        captured = datetime.fromisoformat(captured_at_utc.replace("Z", "+00:00"))
    except (TypeError, AttributeError, ValueError) as exc:
        raise ContractError("TPEX_DELIST_BAD_CAPTURE_TIME") from exc
    if captured.tzinfo is None:
        raise ContractError("TPEX_DELIST_CAPTURE_TZ_REQUIRED")
    now = captured.astimezone(TZ_TAIPEI).date()
    text, enc = _decode(raw)
    tables = _HtmlTables()
    tables.feed(text)
    candidates = []
    for table in tables.tables:
        for row in table:
            cells = [re.sub(r"\s+", " ", c).strip() for c in row]
            if len(cells) < 3 or not CODE.fullmatch(cells[0]):
                continue
            if not cells[1]:
                raise ContractError("TPEX_DELIST_NAME_MISSING")
            # Search only subsequent cells for an explicit date. Never
            # interpolate termination from the first or last trade.
            found = []
            for cell in cells[2:]:
                parsed = _roc_date(cell)
                if parsed is not None:
                    found.append(parsed)
            if len(set(found)) > 1:
                raise ContractError("TPEX_DELIST_CONFLICTING_ROW_DATES")
            date_value = found[0] if found else None
            if date_value and date.fromisoformat(date_value) > now:
                raise ContractError("TPEX_DELIST_FUTURE_EFFECTIVE_DATE")
            candidates.append({
                "market": "TPEX", "code": cells[0], "company_name": cells[1],
                "termination_effective_date": date_value,
                "raw_cells": cells[:8],
                "announced_at_pit_verified": False,
                "transfer_vs_actual_death_verified": False,
                "settlement_or_consideration_verified": False,
                "last_trade_verified": False,
            })
    if not candidates:
        raise ContractError("TPEX_DELIST_TABLE_NO_RECOGNIZED_ROWS")
    seen = set()
    for row in candidates:
        key = (row["code"], row["termination_effective_date"])
        if key in seen:
            raise ContractError("TPEX_DELIST_DUPLICATE_KEY")
        seen.add(key)
    return {
        "status": "TPEX_OFFICIAL_HTML_ROWS_READ_NOT_FULLY_PIT",
        "source_url": source_url,
        "captured_at_utc": captured.astimezone(timezone.utc).isoformat(),
        "original_sha256": sha256(raw).hexdigest(), "bytes": len(raw),
        "encoding": enc,
        "record_count": len(candidates),
        "records_with_explicit_termination_date": sum(
            x["termination_effective_date"] is not None for x in candidates),
        "event_rows": candidates,
        "full_history_coverage_verified": False,
        "source_publication_time_verified": False,
        "investment_certified": False,
    }


def parse_tpex_json(raw, captured_at_utc):
    """Recognize a public table only with explicit named headers and real dates."""
    text, enc = _decode(raw)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ContractError("TPEX_DELIST_NOT_JSON") from exc
    if not isinstance(data, dict) or data.get("stat", "").lower() not in ("ok", ""):
        raise ContractError("TPEX_DELIST_JSON_INVALID_STATUS")
    tables = data.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ContractError("TPEX_DELIST_JSON_TABLES_MISSING")
    rows = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        headings, cells = table.get("fields"), table.get("data")
        if not isinstance(headings, list) or not isinstance(cells, list):
            continue
        possible_code = [i for i,k in enumerate(headings) if any(s in str(k) for s in ("代號", "代碼"))]
        possible_name = [i for i,k in enumerate(headings) if "名稱" in str(k) or "簡稱" in str(k)]
        possible_date = [i for i,k in enumerate(headings) if ("終止" in str(k) and ("日期" in str(k) or "上櫃" in str(k)))]
        if not possible_code or not possible_name or not possible_date:
            continue
        ci, ni, di = possible_code[0], possible_name[0], possible_date[0]
        reason_col = next((i for i,k in enumerate(headings) if "原因" in str(k)), None)
        for item in cells:
            if isinstance(item, dict):
                item = [item.get(k, "") for k in headings]
            if not isinstance(item, list) or max(ci, ni, di) >= len(item):
                raise ContractError("TPEX_DELIST_JSON_ROW_SHAPE")
            code, name = str(item[ci]).strip(), str(item[ni]).strip()
            date_value = _roc_date(item[di])
            if not re.fullmatch(r"(?:\d{4}|\d{6})", code) or not name or date_value is None:
                raise ContractError("TPEX_DELIST_JSON_EXPLICIT_DATE_OR_CODE_REQUIRED")
            rows.append({
                "market": "TPEX", "code": code, "company_name": name,
                "termination_effective_date": date_value,
                "termination_reason_source_text": (
                    str(item[reason_col]).strip()
                    if reason_col is not None and reason_col < len(item) else None
                ),
                # 6-digit records are not automatically regular common equity.
                # They require separate security-class evidence and must never
                # silently enter the ordinary-stock training universe.
                "security_class_review_required": len(code) != 4,
                "announced_at_pit_verified": False,
                "transfer_vs_actual_death_verified": False,
                "settlement_or_consideration_verified": False,
                "last_trade_verified": False,
            })
    if not rows:
        raise ContractError("TPEX_DELIST_JSON_NO_MATCHING_TERMINATION_TABLE")
    keys = [(x["code"],x["termination_effective_date"]) for x in rows]
    if len(keys) != len(set(keys)):
        raise ContractError("TPEX_DELIST_JSON_DUPLICATE")
    stamp = datetime.fromisoformat(captured_at_utc.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ContractError("TPEX_DELIST_CAPTURE_TZ_REQUIRED")
    if any(date.fromisoformat(r["termination_effective_date"]) > stamp.astimezone(TZ_TAIPEI).date() for r in rows):
        raise ContractError("TPEX_DELIST_FUTURE_EFFECTIVE_DATE")
    return {
        "status": "TPEX_OFFICIAL_JSON_ROWS_READ_NOT_FULLY_PIT",
        "original_sha256": sha256(raw).hexdigest(), "bytes": len(raw),
        "encoding": enc, "captured_at_utc": stamp.astimezone(timezone.utc).isoformat(),
        "record_count": len(rows), "records_with_explicit_termination_date": len(rows),
        "event_rows": rows, "full_history_coverage_verified": False,
        "source_publication_time_verified": False, "investment_certified": False,
    }


def _fetch_legacy(page):
    if type(page) is not int or page < 1 or page > 50:
        raise ContractError("TPEX_DELIST_BAD_PAGE")
    body = urlencode({"stk_code": "", "select_year": "ALL", "topage": str(page), "DELIST_REASON": "-1"}).encode()
    req = Request(OLD_URL, data=body, headers={
        "User-Agent": "Mozilla/5.0 AlphaMax evidence capture",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urlopen(req, timeout=30) as res:
        if res.status != 200:
            raise ContractError("TPEX_DELIST_OFFICIAL_HTTP_STATUS")
        return res.read(20_000_001)


def _fetch_modern():
    url = NEW_URL + "?response=json"
    req = Request(url, headers={"User-Agent":"Mozilla/5.0 AlphaMax evidence capture"})
    with urlopen(req, timeout=30) as res:
        if res.status != 200:
            raise ContractError("TPEX_DELIST_MODERN_HTTP_STATUS")
        return res.read(20_000_001)


def _fetch_year(year):
    if type(year) is not int or not 2000 <= year <= 2100:
        raise ContractError("TPEX_DELIST_BAD_PROBE_YEAR")
    # These names are taken from the official current page tables-form; this
    # is a *probe* until year filtering is verified against each record.
    url = NEW_URL + "?" + urlencode({
        "date": str(year), "reason": "-1", "response": "json"
    })
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 AlphaMax evidence audit"})
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ContractError("TPEX_DELIST_YEAR_HTTP_STATUS")
        return response.read(20_000_001)


def _fetch_page():
    req = Request(WEB_PAGE, headers={"User-Agent": "Mozilla/5.0 AlphaMax research"})
    with urlopen(req, timeout=30) as res:
        if res.status != 200:
            raise ContractError("TPEX_DELIST_OFFICIAL_PAGE_HTTP_STATUS")
        return res.read(20_000_001)


def capture_tpex_delist(output_dir, *, captured_at_utc=None, legacy_fetch=None, modern_fetch=None,
                       page_fetch=None, page_limit=15):
    """Try official historical pages; preserve parse failures for follow-up."""
    if type(page_limit) is not int or not 1 <= page_limit <= 50:
        raise ContractError("TPEX_DELIST_BAD_PAGE_LIMIT")
    try:
        now = datetime.now(timezone.utc) if captured_at_utc is None else datetime.fromisoformat(captured_at_utc.replace("Z","+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContractError("TPEX_DELIST_INVALID_CAPTURE_TIMESTAMP") from exc
    if now.tzinfo is None:
        raise ContractError("TPEX_DELIST_CAPTURE_TZ_REQUIRED")
    stamp = now.astimezone(timezone.utc).isoformat()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    attempts = []
    events = []
    captures = []
    discovery = {}
    fetch_legacy = legacy_fetch or _fetch_legacy
    found_legacy = False
    exhausted = False
    for page in range(1,page_limit + 1):
        try:
            raw = fetch_legacy(page)
            if not isinstance(raw, bytes) or len(raw) > 20_000_000:
                raise ContractError("TPEX_DELIST_BAD_RAW_PAGE")
            # Archive rejected official responses too, for reproducible
            # diagnosis of changing endpoint shape and parsing contracts.
            probe_name = f"tpex-legacy-probe-{page:02d}.html"
            (output / probe_name).write_bytes(raw)
            discovery["legacy_first_page"] = {
                "path": probe_name, "sha256": sha256(raw).hexdigest(),
                "bytes": len(raw),
                "public_response_preview": re.sub(
                    r"\\s+", " ", raw[:2200].decode("utf-8", "replace")
                )[:400],
            }
            parsed = parse_tpex_html(raw, OLD_URL, stamp)
            records = parsed["event_rows"]
            old_codes = {(r["code"], r["termination_effective_date"]) for r in events}
            new_codes = {(r["code"], r["termination_effective_date"]) for r in records}
            if not new_codes - old_codes:
                exhausted = True
                attempts.append({"path": "legacy", "page": page, "status": "REPEATED_PAGE_OR_NO_NEW_EVENTS"})
                break
            if old_codes & new_codes:
                raise ContractError("TPEX_DELIST_OVERLAPPING_PAGES")
            rawname = f"tpex-old-page-{page:02d}.html"
            (output / rawname).write_bytes(raw)
            captures.append({
                "path": rawname, "sha256": parsed["original_sha256"], "bytes": len(raw),
                "page": page, "records": len(records),
                "explicit_dates": parsed["records_with_explicit_termination_date"],
            })
            events.extend(records)
            found_legacy = True
            attempts.append({"path": "legacy", "page": page, "status": "PARSED"})
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            attempts.append({"path": "legacy", "page": page, "status": "REJECTED",
                             "reason": str(exc)[:220]})
            break
    if not found_legacy:
        try:
            raw = (modern_fetch or _fetch_modern)()
            if not isinstance(raw, bytes) or len(raw) > 20_000_000:
                raise ContractError("TPEX_DELIST_MODERN_SOURCE_INVALID")
            (output / "tpex-modern-probe.bin").write_bytes(raw)
            discovery["modern_candidate"] = {
                "path": "tpex-modern-probe.bin", "sha256": sha256(raw).hexdigest(),
                "bytes": len(raw),
                "public_response_preview": re.sub(
                    r"\\s+", " ", raw[:2200].decode("utf-8","replace")
                )[:400],
            }
            parsed = parse_tpex_json(raw, stamp)
            (output / "tpex-modern-raw.json").write_bytes(raw)
            captures.append({
                "path":"tpex-modern-raw.json", "sha256":parsed["original_sha256"],
                "bytes":len(raw), "records":len(parsed["event_rows"]),
                "explicit_dates":len(parsed["event_rows"]),
            })
            events = parsed["event_rows"]
            attempts.append({"path":"modern", "source_url":NEW_URL + "?response=json", "status":"PARSED"})
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            attempts.append({"path":"modern", "source_url":NEW_URL + "?response=json", "status":"REJECTED", "reason":str(exc)[:220]})
    if not events:
        try:
            raw = (page_fetch or _fetch_page)()
            if not isinstance(raw, bytes) or len(raw) > 20_000_000:
                raise ContractError("TPEX_DELIST_PUBLIC_PAGE_INVALID")
            (output / "tpex-current-public-page.html").write_bytes(raw)
            text, _ = _decode(raw)
            # Official page inline initialization may describe its actual
            # backend action; only report it, never auto-follow arbitrary URLs.
            actions = re.findall(
                r"""action\s*:\s*["']([^"']+)["']""", text
            )[:10]
            discovery["current_official_page"] = {
                "sha256": sha256(raw).hexdigest(), "bytes": len(raw),
                "path": "tpex-current-public-page.html", "embedded_actions": actions,
                "tables_init_context": (
                    re.sub(r"\s+", " ", text[max(0,text.find("tables.init")-90):text.find("tables.init")+500])[:550]
                    if "tables.init" in text else None
                ),
                "public_response_preview": re.sub(r"\s+", " ", text[:1500])[:400],
            }
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            discovery["current_official_page"] = {"status": "UNAVAILABLE", "reason": str(exc)[:200]}
    # Probe historical year controls but never concatenate snapshots whose
    # query semantics or pagination have not been proved. Official form has
    # input name=date; the API response also echoes its accepted year.
    annual_years_verified = []
    # The default official JSON is a *single current-year slice*.
    # Verify the source-reported year and totalCount before treating it as
    # complete, even if all returned rows are individually well-formed.
    if events and not found_legacy:
        source = json.loads(raw.decode("utf-8-sig"))
        current_year = int(str(source.get("date", "0")))
        expected = source.get("tables", [{}])[0].get("totalCount")
        year_matches = all(
            event["termination_effective_date"] is not None
            and event["termination_effective_date"].startswith(str(current_year))
            for event in events
        )
        current_complete = (type(expected) is int and expected == len(events)
                            and current_year == datetime.fromisoformat(stamp).astimezone(TZ_TAIPEI).year
                            and year_matches)
        discovery["current_year_source_verified"] = current_complete
        discovery["current_year_totalCount"] = expected
        discovery["current_year"] = current_year
        if current_complete:
            annual_years_verified.append(current_year)

    if events and modern_fetch is None and not found_legacy:
        discovery["year_filter_probes"] = []
        for year in (2025, 2024, 2023, 2022, 2021):
            try:
                year_raw = _fetch_year(year)
                if not isinstance(year_raw, bytes) or len(year_raw) > 20_000_000:
                    raise ContractError("TPEX_DELIST_YEAR_BAD_RESPONSE")
                name = f"tpex-year-{year}-probe.json"
                (output / name).write_bytes(year_raw)
                decoded = json.loads(year_raw.decode("utf-8-sig"))
                record = parse_tpex_json(year_raw, stamp)
                reported = str(decoded.get("date","")) if isinstance(decoded, dict) else ""
                date_years = sorted({
                    str(r["termination_effective_date"])[:4]
                    for r in record["event_rows"]
                })
                total = (
                    decoded.get("tables",[{}])[0].get("totalCount")
                    if isinstance(decoded,dict) and decoded.get("tables") else None
                )
                complete = type(total) is int and total == record["record_count"]
                verified = reported == str(year) and date_years == [str(year)] and complete
                discovery["year_filter_probes"].append({
                    "requested_year": year, "source_url": NEW_URL,
                    "raw_artifact": name, "sha256": sha256(year_raw).hexdigest(),
                    "reported_year": reported, "event_years": date_years,
                    "row_count": record["record_count"],
                    "year_filter_matches_exactly": reported == str(year) and date_years == [str(year)],
                    "source_totalCount": total,
                    "source_pagination_complete": complete,
                    "accepted_for_bounded_2021_to_2026_observation": verified,
                })
                if verified:
                    seen = {(r["code"], r["termination_effective_date"]) for r in events}
                    incoming = {(r["code"], r["termination_effective_date"]) for r in record["event_rows"]}
                    if seen & incoming:
                        raise ContractError("TPEX_DELIST_CROSS_YEAR_DUPLICATE")
                    events.extend(record["event_rows"])
                    annual_years_verified.append(year)
                    captures.append({
                        "path": name, "sha256": sha256(year_raw).hexdigest(),
                        "bytes": len(year_raw), "year": year,
                        "records": len(record["event_rows"]), "explicit_dates": len(record["event_rows"]),
                    })
            except (OSError, ValueError, TypeError, UnicodeError) as exc:
                discovery["year_filter_probes"].append({
                    "requested_year":year, "status":"UNVERIFIED",
                    "reason":str(exc)[:200],
                })
    annual_years_verified.sort()
    six_year_window_complete = annual_years_verified == [2021, 2022, 2023, 2024, 2025, 2026]
    events.sort(key=lambda x: (x["termination_effective_date"] or "", x["code"]))
    valid_dates = sum(x["termination_effective_date"] is not None for x in events)
    status = (
        "TPEX_2021_2026_ANNUAL_SLICES_VERIFIED_NOT_HISTORICAL_PIT"
        if six_year_window_complete else
        "TPEX_OFFICIAL_EVENT_ROWS_OBSERVED_NOT_FULLY_PIT"
        if events else "BLOCKED_TPEX_DELIST_SOURCE_NOT_PARSED"
    )
    report = {
        "status": status, "captured_at_utc": stamp, "attempts": attempts,
        "source_receipts": captures, "unparsed_source_discovery": discovery,
        "event_count": len(events),
        "four_digit_event_count": sum(len(r["code"]) == 4 for r in events),
        "non_four_digit_event_count": sum(len(r["code"]) != 4 for r in events),
        "verified_annual_slices": annual_years_verified,
        "bounded_2021_2026_window_complete": six_year_window_complete,
        "explicit_effective_dates": valid_dates,
        "page_limit": page_limit, "legacy_pagination_exhaustion_verified": exhausted,
        "full_history_coverage_verified": False,
        "company_level_historical_membership_certified": False,
        "announcement_time_PIT_certified": False,
        "delisted_final_investor_returns_certified": False,
        "investment_certified": False,
        "blockers": [
            "TPEX_HISTORICAL_SOURCE_COMPLETENESS_NOT_PROVEN",
            "TPEX_DELIST_ANNOUNCEMENT_PIT_NOT_RECONSTRUCTED",
            "TPEX_MERGERS_MARKET_TRANSFERS_AND_CONSIDERATION_MISSING",
            "TPEX_FINAL_TRADE_PRICES_AND_CORPORATE_ACTIONS_MISSING",
        ]
    }
    if events:
        (output / "tpex-delisted-events.json").write_text(
            json.dumps(events, ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    (output / "capture-manifest.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return report
