#!/usr/bin/env python3
"""Bounded, archival TWSE IRB110 monthly share ownership census probe.

IRB110 is a *balance/monthly summary* and cannot prove centralized-market
purchases. Keep published_at unknown; saving current original bytes cannot
establish historical point-in-time availability.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import html
import json
import pathlib
import re
import time
import urllib.request

ENDPOINT = "https://siis.twse.com.tw/publish/listed/{roc}IRB110_{month}.HTM"
CODES = ("9802", "6965")
MONTHS = ("2026-07", "2026-08", "2026-09")
TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
TD = re.compile(r"<td\b[^>]*>(.*?)</td>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
CODE = re.compile(r"^([1-9][0-9]{3})(?![0-9])")
MTH = re.compile(r"^20[0-9]{2}-(0[1-9]|1[0-2])$")


def serial(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse_irb110(raw, *, requested_issuers=CODES):
    """Numeric fields kept in original shares, never silently converted to lots.

    The seven numeric fields follow official tabular layout; checked
    owner balances and market trade classifications need additional sources.
    """
    if not isinstance(raw, bytes) or not raw:
        raise ValueError("MISSING_OFFICIAL_HTTP_BYTES")
    try:
        page = raw.decode("big5")
    except UnicodeDecodeError as exc:
        raise ValueError("OFFICIAL_IRB110_CHARSET_NOT_BIG5") from exc
    if "<html" not in page.lower() or "IRB110" not in page.upper():
        raise ValueError("NOT_EXPECTED_IRB110_PAGE")
    issuers = {}
    for tr in TR.findall(page):
        cells = [html.unescape(TAG.sub("", c)).replace("\xa0", "").strip()
                 for c in TD.findall(tr)]
        if len(cells) < 8:
            continue
        match = CODE.match(re.sub(r"\s+", "", cells[0]))
        if not match:
            continue
        code = match.group(1)
        if code not in requested_issuers:
            continue
        if code in issuers:
            raise ValueError("DUPLICATE_IRB110_COMPANY")
        values = []
        for value in cells[1:8]:
            cleaned = re.sub(r"\s+", "", value).replace(",", "")
            if not re.fullmatch(r"[0-9]+", cleaned):
                raise ValueError("NON_NUMERIC_IRB110_COMPANY_FIELD")
            values.append(int(cleaned))
        issued, director_increase, director_decrease, director_balance, director_pledge, manager_balance, major_holder_balance = values
        if issued <= 0:
            raise ValueError("NO_OFFICIAL_ISSUED_SHARE_COUNT")
        issuers[code] = {
            "issued_shares": issued, "director_gross_increase_shares": director_increase,
            "director_gross_decrease_shares": director_decrease,
            "director_own_shares": director_balance,
            "director_pledge_shares": director_pledge,
            "manager_own_shares": manager_balance,
            "major_holder_own_shares": major_holder_balance,
            "source_row_sha256": sha(serial(cells)),
            "irb110_is_not_post_trade_market_buys": True,
        }
    if not issuers:
        raise ValueError("TARGET_ISSUERS_NOT_FOUND_OR_IRB110_HTML_LAYOUT_CHANGED")
    return issuers


def capture_month(month, out, opener=None):
    if not MTH.fullmatch(month):
        raise ValueError("INVALID_MONTH")
    year, num = map(int, month.split("-"))
    if year <= 1911:
        raise ValueError("INVALID_ROC_YEAR")
    url = ENDPOINT.format(roc=year - 1911, month=num)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (public historic exchange filing research)",
                                               "Accept": "text/html,*/*"})
    observed = dt.datetime.now(dt.timezone.utc).isoformat()
    opener = opener or urllib.request.urlopen
    result, error, status = None, None, None
    raw = b""
    try:
        with opener(req, timeout=25) as handle:
            status = getattr(handle, "status", handle.getcode())
            raw = handle.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ValueError("IRB110_MAX_BYTES_EXCEEDED")
        if status == 200:
            result = parse_irb110(raw)
        else:
            error = "HTTP_NON_200"
    except (OSError, ValueError) as exc:
        error = type(exc).__name__ + ": " + str(exc)[:160]
    folder = pathlib.Path(out) / month
    folder.mkdir(parents=True, exist_ok=True)
    raw_name = "original_irb110_response.gz" if raw else None
    if raw:
        (folder / raw_name).write_bytes(gzip.compress(raw, mtime=0))
    receipt = {
        "schema": "TWSE_IRB110_MONTHLY_HOLDINGS_SOURCE_PROBE_V1",
        "month": month, "source_url": url, "http_status": status,
        "captured_at_utc": observed, "historical_first_publication_at": None,
        "raw_sha256": sha(raw) if raw else None, "raw_response_archive": raw_name,
        "raw_octets": len(raw), "parse_error": error,
        "found_target_issuers": sorted(result) if result else [],
        "not_proof_of_market_purchase": True,
        "holder_account_identity_confirmed": False,
        "mops_market_trades_reconciled": False,
        "official_source_pit_certified": False,
        "formal_quality_gate_changed": False,
    }
    (folder / "receipt.json").write_bytes(serial(receipt))
    if result is not None:
        (folder / "unverified_balance_summary.json").write_bytes(serial({
            "data_status": "OFFICIAL_ORIGINAL_BYTES_PARSED_BALANCES_NOT_INSIDER_TRADE_CERTIFIED",
            "month": month, "issuers": result, "asof_first_observed": observed,
            "previously_public_asof_month_end": False,
        }))
    return receipt


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("irb110_original_probe_artifact"))
    args = p.parse_args(argv)
    receipts = []
    for month in MONTHS:
        if receipts:
            time.sleep(1.5)
        r = capture_month(month, args.out)
        receipts.append(r)
        print(json.dumps({"month": month,
                          "source": r["source_url"], "http": r["http_status"],
                          "raw_captured": r["raw_sha256"] is not None,
                          "target_codes_parsed": r["found_target_issuers"],
                          "parse_error": r["parse_error"],
                          "historic_pit_verified": False}, ensure_ascii=False))
    (args.out / "summary.json").write_bytes(serial({
        "schema": "TWSE_IRB110_THREE_MONTH_PROBE_SUMMARY_V1",
        "source_family": "TWSE_SIIS_LISTED_IRB110",
        "records": receipts,
        "captured_originals": sum(bool(r["raw_sha256"]) for r in receipts),
        "parsed_months": sum(bool(r["found_target_issuers"]) for r in receipts),
        "formal_quality_gate_changed": False,
        "real_historical_one_year_win_rate": None,
    }))


if __name__ == "__main__":
    main()
