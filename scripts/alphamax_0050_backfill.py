#!/usr/bin/env python3
"""Bounded 0050 TWSE monthly source-backfill for prospective AlphaMax comparison.

Collect archived, raw *price-only* history for the investable 0050 comparison
benchmark. Source capture today NEVER certifies a historical PIT signal, an
investor total return, a broker fill, or a delisting-adjusted outcome.

Runs through existing TWSE STOCK_DAY parser + on-disk original archive receipts.
No source data is downloaded when imported.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re

from scripts.history_archive import digest, quote_source_ready
from scripts.tw_history_backfill import process, request

BEGIN_MONTH = "2025-01"
CODE = "0050"
REPORT_SCHEMA = "ALPHAMAX_0050_12M_RAW_HISTORY_BACKFILL_V1"


def preceding_months(start_month, asof, saved, max_new_months, root):
    """Earliest unverified completed 0050 months first, immutable original receipts.

    Restrict to completed calendar months; the standing prospective 0050
    collector handles the current incomplete month separately.
    """
    if type(max_new_months) is not int or not 0 <= max_new_months <= 12:
        raise ValueError("0050_INVALID_SOURCE_REQUEST_BUDGET")
    if not isinstance(saved, dict):
        raise ValueError("0050_INVALID_OLD_MONTHLY_ARCHIVE")
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", start_month):
        raise ValueError("0050_INVALID_MONTH_START")
    ref_date = date.fromisoformat(asof)
    sy, sm = map(int, start_month.split("-"))
    start = date(sy, sm, 1)
    if start > ref_date:
        raise ValueError("0050_START_AFTER_OFFICIAL_PRICE_REFERENCE")
    year, month = start.year, start.month
    pending = []
    while date(year, month, 1) < date(ref_date.year, ref_date.month, 1):
        part = f"{year}-{month:02d}"
        old = saved.get(part)
        # quote_source_ready verifies durable raw source + signed-to-receipt
        # normalized hash. A self-reported original SHA alone is insufficient.
        present = False
        if isinstance(old, dict):
            try:
                present = quote_source_ready(root, old)
            except (OSError, ValueError, TypeError, KeyError):
                present = False
        if not present:
            pending.append(part)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return {
        "all_incomplete_months": pending,
        "source_request_months": pending[:max_new_months],
        "pending_after_this_budget": pending[max_new_months:],
    }


def run(root, max_requests=4, start_month=BEGIN_MONTH, *, fetch=request, sleep=0.4):
    root = Path(root)
    manifest_path = root / "prices/latest_manifest.json"
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    asof = m["date"]
    date.fromisoformat(asof)
    original_snapshot = (root / "prices" / (asof + ".json")).read_bytes()
    if digest(original_snapshot) != m.get("normalized_sha256"):
        raise ValueError("0050_REFERENCE_PRICE_SOURCE_HASH_MISMATCH")
    snapshot = json.loads(original_snapshot)
    q = [x for x in snapshot if x.get("market") == "TWSE" and x.get("code") == CODE]
    if len(q) != 1 or type(q[0].get("close")) not in (float, int) or q[0]["close"] <= 0:
        raise ValueError("0050_MISSING_OFFICIAL_REFERENCE_QUOTE")
    dest = root / "prices/issuer_history/TWSE"
    path = dest / (CODE + ".json")
    prior = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if prior and (prior.get("issuer") != CODE or prior.get("market") != "TWSE"):
        raise ValueError("0050_HISTORICAL_IDENTITY_CHANGED")
    queue = preceding_months(start_month, asof, prior.get("by_month", {}),
                             max_requests, root)
    months = queue["source_request_months"]
    result = None
    if months:
        result = process(
            CODE, asof, months, fetch=fetch, out=dest,
            root=root, max_new_months=max_requests,
            reference_close=q[0]["close"], sleep=sleep,
        )
    after = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    reread = preceding_months(start_month, asof, after.get("by_month", {}),
                              0, root)
    return {
        "schema": REPORT_SCHEMA,
        "asof": asof,
        "benchmark": CODE,
        "start_month": start_month,
        "requested_completed_months": len(queue["all_incomplete_months"]),
        "requested_months_this_run": months,
        "retrieval": result,
        "remaining_completed_months_without_durable_original_receipts": reread["all_incomplete_months"],
        "available_unadjusted_sessions": len(after.get("sessions", [])),
        "price_only_backfill": True,
        "pit_training_certified": False,
        "dividend_and_corporate_actions_verified": False,
        "investor_total_return_certified": False,
        "model_backtest_completed": False,
        "status": ("RAW_SOURCE_PRICE_HISTORY_COMPLETE_TOTAL_RETURN_BLOCKED"
                   if not reread["all_incomplete_months"]
                   else "RAW_SOURCE_BACKFILL_INCOMPLETE"),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("tw-market-data"))
    p.add_argument("--max-requests", type=int, default=4)
    p.add_argument("--start-month", default=BEGIN_MONTH)
    p.add_argument("--output", type=Path, default=Path("tw-market-data/rankings/alphamax_0050_backfill_progress.json"))
    a = p.parse_args()
    data = run(a.data_root, a.max_requests, a.start_month)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: data[k] for k in (
        "status", "asof", "benchmark", "requested_months_this_run",
        "remaining_completed_months_without_durable_original_receipts",
        "available_unadjusted_sessions")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
