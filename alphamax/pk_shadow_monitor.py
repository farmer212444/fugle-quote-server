"""Prospective *price-only* shadow PK from the first post-freeze session.

This code never emits net investment returns or a real model-vs-model winner:
Alpha side is an analyst research queue and official open is not a broker fill.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha1
import json
from math import isfinite

from alphamax.pk_exhibition import BENCHMARK, PKContractError, frozen_digest, validate_freeze

# Original GitHub blob, obtained from main when the 2026-11-12 session was
# first inspected. Drift in this baseline MUST fail closed, not rebase returns.
SHADOW_ENTRY_DATE = "2026-11-12"
SHADOW_ENTRY_PATH = "tw-market-data/prices/2026-11-12.json"
SHADOW_ENTRY_BLOB_SHA = "58231b3ee3e6fcd3a96aa02c379eb40496c9d8d6"


def git_blob_sha(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        raise PKContractError("SOURCE_BYTES_REQUIRED")
    return sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def _date_str(x):
    if not isinstance(x, str):
        raise PKContractError("INVALID_SNAPSHOT_DATE")
    try:
        dt = date.fromisoformat(x)
    except ValueError as exc:
        raise PKContractError("INVALID_SNAPSHOT_DATE") from exc
    if dt.isoformat() != x:
        raise PKContractError("INVALID_SNAPSHOT_DATE")
    return dt


def _number(v):
    return type(v) in (int, float) and isfinite(v) and v > 0


def _unique_rows(raw: bytes, expect_date: str, *, field: str):
    try:
        rows = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PKContractError("INVALID_QUOTE_JSON_BYTES") from exc
    if not isinstance(rows, list):
        raise PKContractError("QUOTE_SNAPSHOT_MUST_BE_LIST")
    idx = {}
    for row in rows:
        if not isinstance(row, dict):
            raise PKContractError("INVALID_QUOTE_ROW")
        if row.get("date") != expect_date:
            raise PKContractError("MIXED_SNAPSHOT_DATES")
        key = (row.get("market"), row.get("code"))
        if key in idx:
            raise PKContractError("DUPLICATE_MARKET_CODE")
        if key[0] not in ("TWSE", "TPEX") or not isinstance(key[1], str):
            raise PKContractError("INVALID_MARKET_CODE")
        idx[key] = row
    return idx


def shadow_price_only(freeze, entry_raw: bytes, last_raw: bytes, last_manifest,
                      *, expected_entry_blob_sha: str = SHADOW_ENTRY_BLOB_SHA):
    """Validate provenance, then report equal-initial-NTD *unadjusted* price changes.

    Source receipts and entry execution are not proven by this function.
    The expected entry digest is hard-coded by the CLI and workflow, never
    taken from a mutable manifest. Tests may pass a synthetic fixture digest.
    """
    validate_freeze(freeze)
    if not isinstance(last_manifest, dict):
        raise PKContractError("LATEST_MANIFEST_REQUIRED")
    today = _date_str(last_manifest.get("date"))
    entrydate = _date_str(SHADOW_ENTRY_DATE)
    if today < entrydate:
        raise PKContractError("LATEST_BEFORE_FROZEN_ENTRY_DATE")
    if last_manifest.get("path") != f"tw-market-data/prices/{today.isoformat()}.json":
        raise PKContractError("LATEST_PRICE_MANIFEST_PATH_INVALID")
    if last_manifest.get("unadjusted_quotes") is not True:
        raise PKContractError("LATEST_SNAPSHOT_ADJUSTMENT_STATUS_UNKNOWN")
    if git_blob_sha(entry_raw) != expected_entry_blob_sha:
        raise PKContractError("SHADOW_ENTRY_BLOB_TAMPERED")
    entry = _unique_rows(entry_raw, SHADOW_ENTRY_DATE, field="open")
    last = _unique_rows(last_raw, today.isoformat(), field="close")

    # A rewritten snapshot for the *entry session itself* is not a new trading
    # session. Cross-vintage same-day differences must not be scored as gains.
    if today == entrydate and git_blob_sha(last_raw) != expected_entry_blob_sha:
        return {
            "schema": "ALPHAMAX_PK_SHADOW_PRICE_ONLY_V1",
            "status": "BLOCKED_SAME_SESSION_SNAPSHOT_REVISED",
            "freeze_date": freeze["comparator_vintage_date"],
            "frozen_lineup_digest_sha256": frozen_digest(freeze),
            "entry_price_date": SHADOW_ENTRY_DATE,
            "entry_price_source_git_blob_sha": git_blob_sha(entry_raw),
            "last_price_date": today.isoformat(),
            "last_snapshot_git_blob_sha": git_blob_sha(last_raw),
            "lanes": {
                lane: {
                    "complete_quote_count": None,
                    "security_count": 10,
                    "equal_initial_capital_unadjusted_price_change_pct": None,
                    "unadjusted_excess_vs_0050_pct_points": None,
                    "positions": [],
                } for lane in ("alpha_lane", "v8_lane")
            },
            "benchmark_0050": {"raw_price_only_change_pct": None},
            "verified_executable_returns": None,
            "verified_after_cost_total_returns": None,
            "dividend_corporate_action_adjusted": False,
            "official_winner": None,
            "is_model_vs_model": False,
            "reason": "The pinned entry and current main snapshot for the same "
                      "trading date differ. No later session exists; return "
                      "diagnostics are BLOCKED, not rebased to revised prices.",
        }
    required = {BENCHMARK}
    for lane in ("alpha_lane", "v8_lane"):
        required.update((r["market"], r["code"]) for r in freeze[lane]["rows"])

    # An official opening auction quote is not evidence that a large investor
    # could fill their entire desired position at that exact opening price.
    missing_entry = []
    for key in sorted(required):
        row = entry.get(key)
        if row is None or not _number(row.get("open")) or not _number(row.get("close")):
            missing_entry.append("%s:%s" % key)
    if missing_entry:
        raise PKContractError("FROZEN_ENTRY_QUOTE_COVERAGE_INCOMPLETE:" + ",".join(missing_entry))

    lanes = {}
    for lane in ("alpha_lane", "v8_lane"):
        positions = []
        for original in freeze[lane]["rows"]:
            key = (original["market"], original["code"])
            first = entry[key]
            last_row = last.get(key)
            close = last_row.get("close") if last_row else None
            valid = _number(close)
            ratio = close / first["open"] if valid else None
            positions.append({
                "code": key[1],
                "market": key[0],
                "frozen_rank": original["rank"],
                "postfreeze_official_open_proxy": first["open"],
                "last_official_unadjusted_close": close if valid else None,
                "raw_price_only_change_pct": round(100 * (ratio - 1), 6) if valid else None,
                "entry_actual_fill_verified": False,
                "last_quote_fill_verified": False,
            })
        changes = [r["raw_price_only_change_pct"] for r in positions if r["raw_price_only_change_pct"] is not None]
        lanes[lane] = {
            "complete_quote_count": len(changes),
            "security_count": 10,
            "equal_initial_capital_unadjusted_price_change_pct":
                round(sum(changes) / 10, 6) if len(changes) == 10 else None,
            "positions": positions,
        }
    first_benchmark = entry[BENCHMARK]["open"]
    last_benchmark_row = last.get(BENCHMARK)
    bclose = last_benchmark_row.get("close") if last_benchmark_row else None
    b = round(100 * (bclose / first_benchmark - 1), 6) if _number(bclose) else None
    if b is not None:
        for v in lanes.values():
            val = v["equal_initial_capital_unadjusted_price_change_pct"]
            v["unadjusted_excess_vs_0050_pct_points"] = round(val - b, 6) if val is not None else None
    else:
        for v in lanes.values():
            v["unadjusted_excess_vs_0050_pct_points"] = None
    return {
        "schema": "ALPHAMAX_PK_SHADOW_PRICE_ONLY_V1",
        "status": "PROSPECTIVE_RAW_PRICE_ONLY_UNEXECUTABLE_NO_WINNER",
        "freeze_date": freeze["comparator_vintage_date"],
        "frozen_lineup_digest_sha256": frozen_digest(freeze),
        "entry_price_date": SHADOW_ENTRY_DATE,
        "entry_price_source_git_blob_sha": git_blob_sha(entry_raw),
        "last_price_date": today.isoformat(),
        "last_source_normalized_sha256_unverified": last_manifest.get("normalized_sha256"),
        "lanes": lanes,
        "benchmark_0050": {
            "entry_open_price_proxy": first_benchmark,
            "last_close": bclose if _number(bclose) else None,
            "raw_price_only_change_pct": b,
        },
        "verified_executable_returns": None,
        "verified_after_cost_total_returns": None,
        "dividend_corporate_action_adjusted": False,
        "official_winner": None,
        "is_model_vs_model": False,
        "reason": "Reference post-freeze exchange opening quotations are NOT verified broker fills. "
                  "All output changes omit cash dividends, corporate actions, fees and "
                  "slippage; Alpha selection was a human queue, not trained AlphaMax.",
    }
