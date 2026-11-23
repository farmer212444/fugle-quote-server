#!/usr/bin/env python3
"""Refresh 0050 *current partial month* in isolated AlphaMax source cache.

The completed-month backfill intentionally skips the live partial month.
This separately fetches TWSE STOCK_DAY, re-verifies original response bytes,
reparses the exact exchange JSON, and checks the date/close against the
SHA-256-pinned official daily snapshot already staged in isolated scratch.
No synthetic trading dates, PIT timestamps, total returns or labels.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

from scripts.alphamax_0050_restore import (
    RELATIVE_PACKET, _packet, _validate_cached_source,
)
from scripts.history_archive import (
    canonical, digest, quote_source_ready, verify_original,
)
from scripts.tw_history_backfill import combine, parse, process, request

CODE = "0050"
SCHEMA = "ALPHAMAX_0050_CURRENT_PARTIAL_MONTH_ORIGINAL_SOURCE_V1"


def run_current_month(root, *, fetch=request, sleep=0):
    root = Path(root)
    manifest = json.loads((root / "prices/latest_manifest.json").read_text(encoding="utf-8"))
    asof = date.fromisoformat(manifest["date"]).isoformat()
    if manifest.get("path") != f"tw-market-data/prices/{asof}.json":
        raise ValueError("0050_REFERENCE_MANIFEST_PATH_INVALID")
    raw = (root / "prices" / f"{asof}.json").read_bytes()
    if digest(raw) != manifest.get("normalized_sha256"):
        raise ValueError("0050_OFFICIAL_REFERENCE_PRICE_HASH_MISMATCH")
    snapshot = json.loads(raw)
    candidates = [q for q in snapshot if isinstance(q, dict)
                  and q.get("market") == "TWSE" and q.get("code") == CODE]
    if len(candidates) != 1:
        raise ValueError("0050_REFERENCE_PRICE_ROW_IDENTITY_MISMATCH")
    official_close = candidates[0].get("close")
    if type(official_close) not in (int, float) or not 0 < official_close < float("inf"):
        raise ValueError("0050_OFFICIAL_DAILY_CLOSE_INVALID")
    monthly_path = root / RELATIVE_PACKET
    old = _packet(monthly_path) if monthly_path.is_file() else None
    if old:
        _validate_cached_source(root, old, old["price_reference_asof"])
    month = asof[:7]
    source_errors = []
    try:
        process(
            CODE, asof, [month], fetch=fetch,
            out=root / "prices/issuer_history/TWSE",
            rawdir=root / "raw-current-month/TWSE",
            root=root, max_new_months=1,
            reference_close=official_close, sleep=sleep,
        )
    except (ValueError, OSError, TypeError, KeyError) as exc:
        source_errors.append(type(exc).__name__ + ":" + str(exc)[:180])
    packet = _packet(monthly_path) if monthly_path.is_file() else None
    if packet is None:
        return {
            "schema": SCHEMA, "status": "BLOCKED_0050_PARTIAL_MONTH_PACKET_MISSING",
            "source_errors": source_errors, "asof": asof,
            "raw_current_month_verified": False, "price_only": True,
            "investor_total_return_certified": False,
        }
    cached = packet["by_month"].get(month)
    receipt_ok = isinstance(cached, dict) and quote_source_ready(root, cached)
    normalized_ok = False
    if receipt_ok:
        original = verify_original(root, cached["original_archive"])
        full_rows = parse(original, CODE, month)
        expected = [x for x in full_rows if x["date"] <= asof]
        normalized_ok = (cached.get("rows") == expected and
                         cached["original_archive"].get("parsed_rows_sha256")
                         == digest(canonical(full_rows)) and
                         packet["sessions"] == combine(
                             {m: x["rows"] for m, x in packet["by_month"].items()},
                             asof, CODE))
    _validate_cached_source(root, packet, asof)
    current_rows = cached.get("rows", []) if isinstance(cached, dict) else []
    latest = max(current_rows, key=lambda x: x["date"]) if current_rows else {}
    matched = (receipt_ok and normalized_ok and
               packet["price_reference_asof"] == asof and
               latest.get("date") == asof and
               type(latest.get("close")) in (float, int) and
               abs(latest["close"] - float(official_close)) <= 0.011 and
               not source_errors)
    return {
        "schema": SCHEMA,
        "status": ("ISOLATED_CURRENT_MONTH_OFFICIAL_PRICE_SOURCE_ALIGNED_NOT_PIT"
                   if matched else "BLOCKED_0050_CURRENT_MONTH_PRICE_SOURCE_STALE_OR_INVALID"),
        "asof": asof,
        "current_month": month,
        "reference_close": official_close,
        "latest_current_month_quote_date": latest.get("date"),
        "normalized_session_count": len(packet["sessions"]),
        "source_errors": source_errors,
        "current_month_source_receipt_verified": receipt_ok,
        "reparsed_month_matches_saved_rows": normalized_ok,
        "raw_current_month_verified": matched,
        "source_exchange_signature_verified": False,
        "historical_pit_issuer_universe_verified": False,
        "price_only": True,
        "investor_total_return_certified": False,
        "after_cost_oos_12m_verified": 0,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("alphamax-0050-data"))
    p.add_argument("--output", type=Path, default=Path("alphamax-0050-current-month.json"))
    a = p.parse_args()
    result = run_current_month(a.data_root)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, ensure_ascii=False,
                                   sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "asof": result["asof"],
        "last_raw_date": result.get("latest_current_month_quote_date"),
        "raw_current_month_verified": result["raw_current_month_verified"],
        "session_count": result.get("normalized_session_count", 0),
        "pit_certified": False,
        "investor_total_return_certified": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
