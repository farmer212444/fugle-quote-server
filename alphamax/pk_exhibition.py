"""Fail-closed, pre-registered exhibition scoreboard for two frozen research lists.

NOT model-vs-model performance: Alpha lane is human research triage, not the trained
AlphaMax model. Daily raw close changes are diagnostics, not investable P&L.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from math import isfinite

from alphamax.core import TradingCosts

FREEZE_SCHEMA = "ALPHAMAX_V8_RESEARCH_EXHIBITION_MATCH_V1"
EXECUTION_SCHEMA = "ALPHAMAX_PK_EXECUTIONS_V1"
ALLOWED_HORIZONS = (21, 63, 126, 252)
BENCHMARK = ("TWSE", "0050")
# Pre-registered, immutable original market/code/reference-price triples.
FROZEN_REFERENCE_TABLE = {
  "alpha_lane": [
    [
      "TPEX",
      "8299",
      1675
    ],
    [
      "TWSE",
      "6691",
      568
    ],
    [
      "TPEX",
      "6274",
      982
    ],
    [
      "TWSE",
      "2330",
      2285
    ],
    [
      "TWSE",
      "2383",
      4365
    ],
    [
      "TWSE",
      "2395",
      593
    ],
    [
      "TWSE",
      "2408",
      383
    ],
    [
      "TWSE",
      "2344",
      135
    ],
    [
      "TWSE",
      "2360",
      1310
    ],
    [
      "TPEX",
      "5274",
      11935
    ]
  ],
  "v8_lane": [
    [
      "TWSE",
      "6505",
      89.6
    ],
    [
      "TPEX",
      "6221",
      41.35
    ],
    [
      "TPEX",
      "3219",
      109
    ],
    [
      "TWSE",
      "4155",
      17.5
    ],
    [
      "TPEX",
      "3287",
      79.2
    ],
    [
      "TPEX",
      "6538",
      309.5
    ],
    [
      "TWSE",
      "2059",
      8565
    ],
    [
      "TPEX",
      "4979",
      383
    ],
    [
      "TPEX",
      "4721",
      68.8
    ],
    [
      "TPEX",
      "4931",
      185.5
    ]
  ]
}



class PKContractError(ValueError):
    """A comparison cannot be scored when any constituent or receipt is missing."""


def _date(value):
    if not isinstance(value, str):
        raise PKContractError("DATE_STRING_REQUIRED")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise PKContractError("INVALID_DATE") from exc
    if parsed.isoformat() != value:
        raise PKContractError("NONCANONICAL_DATE")
    return parsed


def _number(value, *, positive=False):
    if type(value) not in (float, int) or not isfinite(value):
        raise PKContractError("FINITE_NUMBER_REQUIRED")
    if positive and value <= 0:
        raise PKContractError("POSITIVE_NUMBER_REQUIRED")
    return float(value)


def validate_freeze(freeze):
    if not isinstance(freeze, dict) or freeze.get("schema") != FREEZE_SCHEMA:
        raise PKContractError("INVALID_FROZEN_EXHIBITION_SCHEMA")
    ref = _date(freeze.get("reference_price_date"))
    cutoff = _date(freeze.get("comparator_vintage_date"))
    if cutoff < ref:
        raise PKContractError("FREEZE_BEFORE_REFERENCE_DATE")
    names = {}
    for lane in ("alpha_lane", "v8_lane"):
        part = freeze.get(lane)
        if not isinstance(part, dict) or len(part.get("rows", [])) != 10:
            raise PKContractError("EACH_LANE_MUST_HAVE_TEN_UNMODIFIED_NAMES")
        unique = set()
        for i, row in enumerate(part["rows"], 1):
            if not isinstance(row, dict) or row.get("rank") != i:
                raise PKContractError("FROZEN_RANK_ORDER_CHANGED")
            key = (row.get("market"), row.get("code"))
            if key[0] not in ("TWSE", "TPEX") or not isinstance(key[1], str) or not key[1].isdigit():
                raise PKContractError("INVALID_SECURITY_ID")
            if key in unique:
                raise PKContractError("DUPLICATE_FROZEN_SECURITY")
            if row.get("price_date") != ref.isoformat():
                raise PKContractError("FROZEN_REFERENCE_DATE_MISMATCH")
            close = _number(row.get("reference_close"), positive=True)
            if (key[0], key[1], close) != tuple(FROZEN_REFERENCE_TABLE[lane][i - 1]):
                raise PKContractError("FROZEN_LINEUP_OR_PRICE_TAMPERED")
            unique.add(key)
        names[lane] = unique
    if names["alpha_lane"] & names["v8_lane"]:
        # Overlap is mathematically permissible, but this freeze explicitly had 0.
        raise PKContractError("FROZEN_OVERLAP_CHANGED")
    return names


def frozen_digest(freeze):
    canonical = json.dumps(freeze, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def observed_quotes(freeze, market_rows, snapshot_date, manifest=None):
    """Unadjusted quote coverage only. Must never emit a portfolio winner."""
    names = validate_freeze(freeze)
    session = _date(snapshot_date)
    ref = _date(freeze["reference_price_date"])
    if not isinstance(market_rows, list):
        raise PKContractError("PRICE_ROWS_LIST_REQUIRED")
    if manifest is not None:
        if manifest.get("date") != session.isoformat():
            raise PKContractError("MANIFEST_SNAPSHOT_DATE_MISMATCH")
        if manifest.get("unadjusted_quotes") is not True:
            raise PKContractError("ONLY_RAW_QUOTE_DIAGNOSTIC_SUPPORTED")
    prices = {}
    for row in market_rows:
        if not isinstance(row, dict):
            raise PKContractError("INVALID_PRICE_ROW")
        key = (row.get("market"), row.get("code"))
        if key in prices:
            raise PKContractError("DUPLICATE_MARKET_CODE_IN_SNAPSHOT")
        if row.get("date") != session.isoformat():
            raise PKContractError("MIXED_PRICE_SESSION_DATES")
        close = row.get("close")
        valid = type(close) in (int, float) and isfinite(close) and close > 0
        prices[key] = close if valid else None
    lanes = {}
    for lane, keys in names.items():
        recs = []
        for row in freeze[lane]["rows"]:
            key = (row["market"], row["code"])
            now = prices.get(key)
            recs.append({
                "code": key[1], "market": key[0],
                "reference_close": row["reference_close"],
                "observed_unadjusted_close": now,
                "raw_close_change_pct": (round(100 * (now / row["reference_close"] - 1), 5)
                                         if now is not None and session > ref else None),
            })
        changes = [z["raw_close_change_pct"] for z in recs if z["raw_close_change_pct"] is not None]
        lanes[lane] = {
            "quote_coverage": sum(z["observed_unadjusted_close"] is not None for z in recs),
            "constituent_count": 10,
            "raw_equal_weight_close_change_pct": (round(sum(changes) / 10, 5)
                                                   if len(changes) == 10 else None),
            "positions": recs,
        }
    return {
        "schema": "ALPHAMAX_PK_OBSERVATION_V1",
        "status": "UNADJUSTED_REFERENCE_PRICE_DIAGNOSTIC_ONLY",
        "frozen_digest_sha256": frozen_digest(freeze),
        "freeze_date": freeze["comparator_vintage_date"],
        "reference_price_date": freeze["reference_price_date"],
        "observation_price_date": session.isoformat(),
        "lanes": lanes,
        "benchmark_quote_present": prices.get(BENCHMARK) is not None,
        "fair_executable_entry_approved": False,
        "dividends_corporate_actions_approved": False,
        "is_model_vs_model": False,
        "verified_net_returns": None,
        "official_winner": None,
        "reason": ("Alpha lane is a human triage list; reference closes are not verified "
                   "post-freeze execution, raw closes omit investor total-return "
                   "adjustments and the snapshot has no independent fill evidence."),
    }


def _validate_sessions(source, freeze):
    horizon = source.get("holding_sessions")
    if type(horizon) is not int or horizon not in ALLOWED_HORIZONS:
        raise PKContractError("UNREGISTERED_HOLDING_HORIZON")
    sessions = source.get("trading_sessions")
    if not isinstance(sessions, list) or len(sessions) != horizon + 1:
        raise PKContractError("UNVERIFIED_TRADING_SESSION_COUNT")
    dates = [_date(s) for s in sessions]
    if dates != sorted(set(dates)) or dates[0] <= _date(freeze["comparator_vintage_date"]):
        raise PKContractError("SESSION_START_NOT_STRICTLY_AFTER_FREEZE")
    if dates[0].isoformat() != source.get("entry_session") or dates[-1].isoformat() != source.get("exit_session"):
        raise PKContractError("ENTRY_EXIT_SESSION_MISMATCH")
    if _date(source.get("data_matured_at")) < dates[-1]:
        raise PKContractError("FUTURE_OUTCOME_LEAKAGE")
    return horizon


def evidence_scorecard(freeze, source):
    """Computable *illustration* after strict coverage gates; never self-certify audit.

    Gross factors are supplied by an outside, independently audited ledger; this
    contract checks internal consistency, NOT original-source authenticity.
    """
    ids = validate_freeze(freeze)
    if not isinstance(source, dict) or source.get("schema") != EXECUTION_SCHEMA:
        raise PKContractError("EXECUTION_EVIDENCE_SCHEMA_MISSING")
    horizon = _validate_sessions(source, freeze)
    receipts = source.get("source_receipts")
    if not isinstance(receipts, list) or not receipts or any(not isinstance(r, str) or not r.strip() for r in receipts):
        raise PKContractError("EXTERNAL_RECEIPTS_REQUIRED")
    rows = source.get("total_return_factors")
    if not isinstance(rows, list) or len(rows) != 21:
        raise PKContractError("TWENTY_STOCKS_PLUS_ETF_REQUIRED")
    factors = {}
    for row in rows:
        key = (row.get("market"), row.get("code"))
        if key in factors:
            raise PKContractError("DUPLICATED_TOTAL_RETURN_FACTOR")
        if not row.get("source_receipt_id") or row["source_receipt_id"] not in receipts:
            raise PKContractError("UNRECONCILED_SOURCE_RECEIPT")
        factor = _number(row.get("investor_total_return_factor"))
        if factor < 0:
            raise PKContractError("NEGATIVE_WEALTH_FACTOR")
        if row.get("entry_session") != source.get("entry_session") or row.get("exit_session") != source.get("exit_session"):
            raise PKContractError("MISMATCHED_EVALUATION_WINDOW")
        if row.get("corporate_actions_and_cash_dividends_reviewed") is not True:
            raise PKContractError("CORPORATE_ACTIONS_OR_DIVIDENDS_MISSING")
        factors[key] = factor
    needed = ids["alpha_lane"] | ids["v8_lane"] | {BENCHMARK}
    if set(factors) != needed:
        raise PKContractError("CONSTITUENT_OR_ETF_COVERAGE_MISMATCH")
    stock = TradingCosts()
    etf = TradingCosts(sell_tax=0.001)
    lanestats = {}
    for lane in ("alpha_lane", "v8_lane"):
        values = [stock.net(factors[(r["market"], r["code"])] - 1)
                  for r in freeze[lane]["rows"]]
        lanestats[lane] = {"unverified_equal_weight_net_total_return_pct":
                           round(100 * sum(values) / 10, 5), "count": len(values)}
    etf_result = 100 * etf.net(factors[BENCHMARK] - 1)
    return {
        "schema": "ALPHAMAX_PK_UNVERIFIED_SCORECARD_V1",
        "status": "CONTRACT_ONLY_EXTERNAL_AUDIT_REQUIRED",
        "horizon_sessions": horizon,
        "entry_session": source["entry_session"],
        "exit_session": source["exit_session"],
        "lanes": lanestats,
        "benchmark_0050_unverified_net_total_return_pct": round(etf_result, 5),
        "official_winner": None,
        "is_model_vs_model": False,
        "external_audit_complete": False,
        "note": "Input self-assertions and receipt strings are NOT independent evidence. "
                "Manual verification of original receipts, trade fills, corporate "
                "actions, ETF benchmark and trading calendar remains required.",
    }
