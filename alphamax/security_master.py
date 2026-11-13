"""Prospective official issuer snapshot intake. Never a historical PIT master.

Current TWSE and TPEx company profiles are captured with raw-byte receipts,
batch dates and timestamps; they cannot prove past listing/delisting membership.
"""
from __future__ import annotations
import csv
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
from alphamax.core import ContractError

TAIPEI = timezone(timedelta(hours=8))
SOURCES = {
    "TWSE": ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L",),
    "TPEX": ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
             "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv"),
}
FIELDS = {
    "TWSE": {"code": ("公司代號",), "name": ("公司簡稱", "公司名稱"),
             "industry": ("產業別",), "date": ("出表日期",),
             "listed": ("上市日期",)},
    "TPEX": {"code": ("SecuritiesCompanyCode", "公司代號"),
             "name": ("CompanyAbbreviation", "公司簡稱", "CompanyName", "公司名稱"),
             "industry": ("SecuritiesIndustryCode", "產業別"),
             "date": ("Date", "出表日期"),
             "listed": ("DateofListing", "DateOfListing", "DateofOTCListing",
                        "DateOfOTCListing", "ListingDate", "上櫃日期")},
}


def parse_official_date(value):
    if value is None or str(value).strip() in ("", "-", "－"):
        return None
    raw = str(value).strip().replace("/", "").replace("-", "").replace(".", "")
    if not re.fullmatch(r"\d{7}|\d{8}", raw):
        raise ContractError("INVALID_PROFILE_DATE")
    if len(raw) == 7:
        raw = f"{int(raw[:3]) + 1911:04d}" + raw[3:]
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).isoformat()
    except ValueError as exc:
        raise ContractError("IMPOSSIBLE_PROFILE_DATE") from exc


def _get(row, options):
    for key in options:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip(), key
    return None, None


def parse_profiles(raw, market, url, captured_at_utc, *, min_rows=1):
    if market not in SOURCES or url not in SOURCES[market]:
        raise ContractError("UNTRUSTED_PROFILE_URL")
    if type(min_rows) is not int or min_rows < 1:
        raise ContractError("INVALID_MIN_ROWS")
    if not isinstance(raw, bytes) or len(raw) < 30 or len(raw) > 20_000_000:
        raise ContractError("INVALID_SOURCE_BYTES")
    try:
        captured = datetime.fromisoformat(captured_at_utc.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContractError("INVALID_CAPTURE_TIME") from exc
    if captured.tzinfo is None:
        raise ContractError("NAIVE_CAPTURE_TIME")
    local_day = captured.astimezone(TAIPEI).date()
    try:
        enc = "utf-8-sig"
        decoded = raw.decode(enc)
    except UnicodeDecodeError:
        enc = "cp950"
        decoded = raw.decode(enc)
    if decoded.lstrip().lower().startswith(("<html", "<!doctype")):
        raise ContractError("HTML_INSTEAD_OF_OFFICIAL_DATA")
    if url.endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(decoded)))
    else:
        try:
            rows = json.loads(decoded)
        except ValueError as exc:
            raise ContractError("PROFILE_SOURCE_BAD_JSON") from exc
    if not isinstance(rows, list) or len(rows) < min_rows:
        raise ContractError("PROFILE_SOURCE_TOO_FEW_ROWS")
    mapping, seen, batches, out = FIELDS[market], set(), set(), []
    unsupported_codes = []
    for r in rows:
        if not isinstance(r, dict):
            raise ContractError("NON_OBJECT_PROFILE")
        code, _ = _get(r, mapping["code"])
        name, _ = _get(r, mapping["name"])
        industry, _ = _get(r, mapping["industry"])
        batch_raw, _ = _get(r, mapping["date"])
        listed_raw, listed_key = _get(r, mapping["listed"])
        if not code or not re.fullmatch(r"\d{4,6}", code) or not name:
            raise ContractError("PROFILE_IDENTITY_MISSING")
        if code in seen:
            raise ContractError("DUPLICATE_PROFILE_CODE")
        seen.add(code)
        batch = parse_official_date(batch_raw)
        listed = parse_official_date(listed_raw)
        if batch is None:
            raise ContractError("PROFILE_BATCH_DATE_MISSING")
        if date.fromisoformat(batch) > local_day or (listed and date.fromisoformat(listed) > local_day):
            raise ContractError("PROFILE_DATE_IN_FUTURE")
        batches.add(batch)
        if len(code) != 4:
            # Official company profiles include 6-digit DRs. Retain provenance
            # and code in an exclusion ledger; do not force them into 4-digit
            # common-equity price/tradability or issuer score coverage.
            unsupported_codes.append({
                "market": market, "code": code,
                "reason": "NON_FOUR_DIGIT_ISSUER_CODE_SEPARATE_SECURITY_CLASS_REVIEW",
            })
            continue
        out.append({
            "market": market, "code": code, "name": name,
            "industry": industry, "profile_batch_date": batch,
            "reported_listing_date": listed, "reported_listing_date_field": listed_key,
            "past_membership_verified": False, "delisting_verified": False,
            "security_class_verified": False
        })
    if len(batches) != 1:
        raise ContractError("PROFILE_MIXED_BATCH_DATES")
    batch = next(iter(batches))
    if (local_day - date.fromisoformat(batch)).days > 14:
        raise ContractError("PROFILE_SOURCE_STALE")
    out.sort(key=lambda x: x["code"])
    return {"market": market, "source_url": url, "raw_sha256": sha256(raw).hexdigest(),
            "raw_bytes": len(raw), "encoding": enc,
            "captured_at_utc": captured.astimezone(timezone.utc).isoformat(),
            "batch_date": batch, "count": len(out),
            "source_row_count": len(rows),
            "excluded_source_rows": len(unsupported_codes),
            "excluded_unsupported_code_sample": unsupported_codes[:25],
            "missing_reported_listing_dates": sum(x["reported_listing_date"] is None for x in out),
            "rows": out}


def reconcile(issuer_rows, quotes):
    if not isinstance(quotes, list):
        raise ContractError("QUOTES_NOT_LIST")
    k, days = set(), set()
    for row in quotes:
        if not isinstance(row, dict):
            raise ContractError("QUOTES_NOT_OBJECTS")
        key = (row.get("market"), row.get("code"))
        if key[0] not in ("TWSE", "TPEX") or not isinstance(key[1], str):
            raise ContractError("BAD_QUOTE_ID")
        if key in k:
            raise ContractError("DUPLICATE_QUOTE")
        k.add(key)
        days.add(row.get("date"))
    if len(days) != 1:
        raise ContractError("MIXED_QUOTE_DATES")
    profiles = [(x["market"], x["code"]) for x in issuer_rows]
    if len(set(profiles)) != len(profiles):
        raise ContractError("DUPLICATE_MARKET_PROFILE")
    p = set(profiles)
    return {
        "quote_date": next(iter(days)), "market_profile_rows": len(p),
        "market_quote_rows": len(k), "matched": len(k & p),
        "quote_only": len(k - p), "profile_only": len(p - k),
        "quote_only_sample": [f"{m}:{c}" for m, c in sorted(k - p)[:20]],
        "profile_only_sample": [f"{m}:{c}" for m, c in sorted(p - k)[:20]],
        "notice": "Quote-only is NOT delisted and may represent ETF, special class or scope mismatch."
    }


def _download(url):
    if url not in {x for v in SOURCES.values() for x in v}:
        raise ContractError("UNTRUSTED_PROFILE_DOWNLOAD")
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (AlphaMax archival research)"})
    with urlopen(req, timeout=35) as resp:
        if resp.status != 200:
            raise ContractError("ISSUER_SOURCE_HTTP_FAILURE")
        raw = resp.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ContractError("PROFILE_RESPONSE_TOO_LARGE")
    return raw


def capture_profiles(output, *, captured_at_utc=None, downloader=None, min_rows=300,
                     quote_rows=None):
    output = Path(output)
    try:
        now = (datetime.now(timezone.utc) if captured_at_utc is None
               else datetime.fromisoformat(captured_at_utc.replace("Z", "+00:00")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContractError("INVALID_CAPTURE_TIME") from exc
    if now.tzinfo is None:
        raise ContractError("NAIVE_CAPTURE_TIME")
    stamp = now.astimezone(timezone.utc).isoformat()
    fetch = downloader or _download
    receipt, attempts, allrows = [], [], []
    for market, urls in SOURCES.items():
        for url in urls:
            try:
                raw = fetch(url)
                parsed = parse_profiles(raw, market, url, stamp, min_rows=min_rows)
                output.mkdir(parents=True, exist_ok=True)
                name = f"{market.lower()}-original." + ("csv" if url.endswith(".csv") else "json")
                (output / name).write_bytes(raw)
                receipt.append({k: v for k, v in parsed.items() if k != "rows"} |
                               {"original_path": name})
                allrows += parsed["rows"]
                attempts.append({"market": market, "url": url, "status": "CAPTURED"})
                break
            except (ValueError, TypeError, OSError, UnicodeError) as exc:
                attempts.append({"market": market, "url": url, "status": "REJECTED",
                                 "reason": str(exc)[:220]})
        else:
            attempts.append({"market": market, "status": "SOURCE_UNAVAILABLE"})
    allrows.sort(key=lambda x: (x["market"], x["code"]))
    complete = {x["market"] for x in receipt} == set(SOURCES)
    report = {
        "schema": "ALPHAMAX_PROSPECTIVE_ISSUER_SNAPSHOT_V1",
        "capture_time_utc": stamp,
        "status": ("PROSPECTIVE_ROSTER_RESEARCH_ONLY" if complete
                   else "BLOCKED_PARTIAL_OFFICIAL_ROSTER"),
        "sources": receipt, "attempts": attempts,
        "profile_count": len(allrows),
        "historical_PIT_universe_approved": False,
        "delisted_securities_covered": False,
        "investment_certified": False,
        "blocking_reasons": [
            "CURRENT_PROFILES_NOT_HISTORICAL_LISTING_DELISTING_MASTER",
            "NO_EVIDENCED_PAST_SECURITY_CLASS_MEMBERSHIP",
            "NO_HISTORICAL_DELISTER_ANNOUNCEMENT_LEDGER"
        ],
    }
    if quote_rows is not None and allrows:
        report["quote_crosscheck"] = reconcile(allrows, quote_rows)
    output.mkdir(parents=True, exist_ok=True)
    (output / "normalized-profiles.json").write_text(
        json.dumps(allrows, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    (output / "capture-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return report
