#!/usr/bin/env python3
"""Bounded original-byte MOPS query6_1 probe for the footwear research branch.

The resulting compressed raw response is an actual response obtained *now*;
it is NOT proof that the content was public on an earlier historical date.
No official stock-trade signal is certified without independent account/role,
corporate-action, shares, filing publication/revision and PIT reconciliation.
This probe never writes rankings, A+ grades, EPS/PE, or broker orders.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import pathlib
import re
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

URL = "https://mops.twse.com.tw/mops/api/query6_1"
UA = "Mozilla/5.0 (compatible; public issuer filing archival research)"
DEFAULT_ISSUERS = ("9802", "6965")
DEFAULT_MONTHS = ("2026-07", "2026-08", "2026-09")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def month_parts(month):
    if not isinstance(month, str) or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", month):
        raise ValueError("INVALID_REPORTING_MONTH")
    year, m = map(int, month.split("-"))
    if year <= 1911:
        raise ValueError("INVALID_ROC_YEAR")
    return str(year - 1911), str(m)


def validate_issuer(code):
    if not isinstance(code, str) or not re.fullmatch(r"[1-9][0-9]{3}", code):
        raise ValueError("INVALID_ISSUER_CODE")
    return code


def parse_api(raw, code, month):
    """Strict row parser, no assumed holder identity deduplication.

    Official query6_1 cells are *shares*, unlike most third-party tables
    expressed in 1000-share lots. Published time is not included in response.
    """
    validate_issuer(code)
    month_parts(month)
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("NOT_VALID_UTF8_JSON") from exc
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise ValueError("API_DID_NOT_RETURN_SUCCESS_RESULT")
    records = (payload.get("result") or {}).get("data")
    if not isinstance(records, list) or not records:
        raise ValueError("API_HAS_NO_REPORT_ROWS")
    out = []
    for row in records:
        if not isinstance(row, list) or len(row) < 19:
            raise ValueError("UNEXPECTED_MOPS_REPORT_SCHEMA")
        # No CSV or silent conversion: market buys/sells MUST be integer shares.
        amounts = {}
        for field, index in [("market_buy_shares", 8), ("market_sell_shares", 13),
                             ("opening_own_shares", 4), ("closing_own_shares", 18),
                             ("other_buy_shares", 9), ("other_sell_shares", 14)]:
            value = str(row[index] or "0").replace(",", "").strip()
            if not re.fullmatch(r"[0-9]+", value):
                raise ValueError("NONINTEGER_OR_NEGATIVE_MOPS_SHARE_AMOUNT")
            amounts[field] = int(value)
        identity = str(row[0] or "").strip()
        name = str(row[1] or "").strip()
        if not identity or not name:
            raise ValueError("MISSING_HOLDER_ROLE_OR_NAME")
        out.append({"role": identity, "name": name,
                    "security_class": str(row[2] or "").strip(),
                    "source_row_sha256": digest(json_bytes(row)),
                    **amounts,
                    "market_net_shares": amounts["market_buy_shares"]-amounts["market_sell_shares"]})
    return out


def capture_single(code, month, output_root, *, opener=None, timeout=25):
    validate_issuer(code)
    year, m = month_parts(month)
    opener = opener or urllib.request.urlopen
    query = {"companyId": code, "dataType": "2", "subsidiaryCompanyId": "",
             "year": year, "month": m}
    req = urllib.request.Request(URL, data=json.dumps(query).encode("utf-8"),
          headers={"User-Agent": UA, "Accept": "application/json",
                   "Content-Type": "application/json",
                   "Origin": "https://mops.twse.com.tw",
                   "Referer": "https://mops.twse.com.tw/"}, method="POST")
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    status, raw, error = None, b"", None
    try:
        with opener(req, timeout=timeout) as response:
            status = getattr(response, "status", response.getcode())
            raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError("MOPS_RESPONSE_SIZE_LIMIT")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        error = type(exc).__name__ + ": " + str(exc)[:160]
    output_root = pathlib.Path(output_root)
    directory = output_root / month / code
    directory.mkdir(parents=True, exist_ok=True)
    if raw:
        original_path = directory / "original_http_response.gz"
        original_path.write_bytes(gzip.compress(raw, mtime=0))
    else:
        original_path = None
    rows, parse_error = None, None
    if status == 200 and error is None:
        try:
            rows = parse_api(raw, code, month)
        except ValueError as exc:
            parse_error = str(exc)
    else:
        parse_error = "HTTP_OR_TRANSPORT_FAILED"
    receipt = {"schema": "MOPS_INSIDER_POST_TRADE_ORIGINAL_PROBE_V1",
               "reporting_month": month, "company_code": code, "source_url": URL,
               "request_data_type": "2", "http_status": status,
               "first_observed_at_utc": stamp,
               "official_historical_published_at": None,
               "original_response_sha256": digest(raw) if raw else None,
               "original_response_archive": str(original_path.relative_to(output_root)) if original_path else None,
               "raw_octets": len(raw), "raw_error": error, "parse_error": parse_error,
               "raw_report_rows": len(rows) if rows else None,
               "role_deduplication_certified": False,
               "holder_stable_account_identity_certified": False,
               "holdings_rollforward_certified": False,
               "irb110_reconciled": False,
               "pit_backtest_admitted": False,
               "formal_a_plus_or_valuation_change": False}
    (directory / "receipt.json").write_bytes(json_bytes(receipt))
    if rows is not None:
        (directory / "unverified_rows.json").write_bytes(json_bytes({
            "reporting_month": month, "issuer": code,
            "no_role_deduplication_performed": True,
            "net_sum_is_not_certified": True, "rows": rows}))
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path,
                        default=pathlib.Path("mops_insider_probe_artifact"))
    parser.add_argument("--codes", default=",".join(DEFAULT_ISSUERS))
    parser.add_argument("--months", default=",".join(DEFAULT_MONTHS))
    args = parser.parse_args(argv)
    codes = tuple(x.strip() for x in args.codes.split(","))
    months = tuple(x.strip() for x in args.months.split(","))
    if not codes or not months or len(codes)*len(months) > 6 or len(set(codes)) != len(codes) or len(set(months)) != len(months):
        raise ValueError("BOUNDED_PROBE_LIMIT_SIX_REPORTS")
    records = []
    for code in codes:
        for month in months:
            if records:
                time.sleep(1.5)  # Respect public source; six bounded requests maximum.
            receipt = capture_single(code, month, args.out)
            records.append(receipt)
            print(json.dumps({"issuer": code, "month": month, "status": receipt["http_status"],
                              "raw_original_received": receipt["original_response_sha256"] is not None,
                              "parse_status": "ROWS_UNVERIFIED" if receipt["raw_report_rows"] else receipt["parse_error"],
                              "original_historical_publication_verified": False},
                             ensure_ascii=False))
    report = {"schema": "MOPS_INSIDER_SIX_REPORT_PROBE_SUMMARY_V1",
              "original_response_captures": sum(bool(r["original_response_sha256"]) for r in records),
              "reports_parsed_but_uncertified": sum(bool(r["raw_report_rows"]) for r in records),
              "reports_attempted": len(records),
              "historically_verifiable_insider_buy_signals": 0,
              "fully_pit_certified_reports": 0,
              "genuine_one_year_outcomes": 0,
              "records": records}
    (args.out / "summary.json").write_bytes(json_bytes(report))
    # A failed network source does not report success, nor stop other issuers.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
