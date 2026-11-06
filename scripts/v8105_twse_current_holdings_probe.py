#!/usr/bin/env python3
"""Archive source-backed current official TWSE director holdings and share base.

Two current TWSE open data snapshots; no statement that historic July 2026
data was accessible. Director balances and role rows are not market trades.
"""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import json
import pathlib
import urllib.request

BASE = "https://openapi.twse.com.tw/v1/opendata/"
SOURCES = ("t187ap11_L", "t187ap03_L")
ISSUERS = ("9802", "6965")
MAX_BYTES = 20_000_000


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def capture(src, out, opener=None):
    if src not in SOURCES:
        raise ValueError("UNSUPPORTED_PUBLIC_TWSE_ENDPOINT")
    opener = opener or urllib.request.urlopen
    url = BASE + src
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (public securities research)",
                                               "Accept": "application/json"})
    observed = dt.datetime.now(dt.timezone.utc).isoformat()
    raw, status, err, rows = b"", None, None, None
    try:
        with opener(req, timeout=40) as response:
            status = getattr(response, "status", response.getcode())
            raw = response.read(MAX_BYTES+1)
        if len(raw) > MAX_BYTES:
            raise ValueError("OFFICIAL_RESPONSE_SIZE_EXCEEDED")
        if status == 200:
            data = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(data, list) or not data:
                raise ValueError("OFFICIAL_OPENAPI_NOT_A_DATA_ARRAY")
            if any(not isinstance(row, dict) for row in data):
                raise ValueError("OFFICIAL_OPENAPI_ROW_SCHEMA_CHANGED")
            rows = [item for item in data if str(item.get("公司代號", "")) in ISSUERS]
            if not rows:
                raise ValueError("NO_TARGET_ISSUER_CURRENT_ROWS")
        else:
            raise ValueError("OFFICIAL_HTTP_NOT_200")
    except (OSError, ValueError, UnicodeError) as exc:
        err = type(exc).__name__ + ": " + str(exc)[:160]
    folder = pathlib.Path(out)/src
    folder.mkdir(parents=True, exist_ok=True)
    if raw:
        (folder/"original_response.gz").write_bytes(gzip.compress(raw, mtime=0))
    rec = {"schema": "TWSE_OFFICIAL_OPENAPI_CURRENT_SNAPSHOT_V1",
           "endpoint": url, "source_family": src, "first_observed_at_utc": observed,
           "http_status": status, "original_response_sha256": digest(raw) if raw else None,
           "original_response_octets": len(raw), "parse_error": err,
           "target_issuer_count": len({x.get("公司代號") for x in (rows or [])}),
           "target_row_count": len(rows) if rows is not None else None,
           "historical_publication_month_reconstructed": False,
           "account_holder_roles_deduplicated": False,
           "market_purchases_not_inferred_from_balances": True,
           "formal_13_gate_passed": False, "original_2026_07_08_09_reconstruction_complete": False}
    (folder/"receipt.json").write_bytes(canonical(rec))
    if rows is not None:
        (folder/"issuer_rows_unverified.json").write_bytes(canonical({
            "source": url, "observed_at_utc": observed, "rows": rows,
            "historical_PIT_validated": False, "shares_units_verified": False,
            "market_buy_sell_flow_verified": False}))
    return rec


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("twse_holdings_probe_artifact"))
    args = p.parse_args(argv)
    records = [capture(src, args.out) for src in SOURCES]
    (args.out/"summary.json").write_bytes(canonical({
        "schema": "TWSE_TWO_CURRENT_OFFICIAL_HOLDINGS_PROBES_V1", "records": records,
        "source_originals_captured": sum(bool(x["original_response_sha256"]) for x in records),
        "historical_inside_trade_signals_certified": 0,
        "one_year_outperformance_win_rate": None,
    }))
    for rec in records:
        print(json.dumps({"source": rec["source_family"], "http": rec["http_status"],
                          "rows": rec["target_row_count"], "error": rec["parse_error"],
                          "historical_PIT": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
