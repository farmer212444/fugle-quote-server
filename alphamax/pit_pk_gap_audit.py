"""PIT-aware AlphaMax-vs-V8 historical evidence *gap* inventory.

Examines original frozen participants against archived quote records and manifests.
Does not calculate/award investment performance or mark raw quotes as total returns.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import json
from math import isfinite

from alphamax.pk_exhibition import PKContractError, validate_freeze

SCHEMA = "ALPHAMAX_PK_TRAINING_GAP_AUDIT_V1"
BENCHMARK_KEY = ("TWSE", "0050")
ONE_YEAR_CALENDAR_DAYS = 365
MIN_ILLUSTRATIVE_SESSION_COUNT = 252


def _iso(value):
    if not isinstance(value, str):
        raise PKContractError("DATE_STRING_REQUIRED")
    try:
        d = date.fromisoformat(value)
    except ValueError as exc:
        raise PKContractError("INVALID_DATE") from exc
    if d.isoformat() != value:
        raise PKContractError("NONCANONICAL_DATE")
    return d


def _priced_sessions(packet, market, code, cutoff):
    if not isinstance(packet, dict) or packet.get("issuer") != code or packet.get("market") != market:
        raise PKContractError("HISTORICAL_SECURITY_IDENTITY_MISMATCH")
    sessions = packet.get("sessions")
    if not isinstance(sessions, list):
        raise PKContractError("HISTORY_SESSIONS_MISSING")
    all_dates = set()
    quoted = []
    bad_closes = 0
    for row in sessions:
        if not isinstance(row, dict):
            raise PKContractError("INVALID_HISTORICAL_SESSION")
        when = _iso(row.get("date"))
        if when in all_dates:
            raise PKContractError("DUPLICATE_HISTORICAL_SESSION")
        if when > cutoff:
            raise PKContractError("FUTURE_PRICE_OBSERVATION")
        if row.get("market") not in (None, market) or row.get("code") not in (None, code):
            raise PKContractError("HISTORICAL_SESSION_IDENTITY_MISMATCH")
        all_dates.add(when)
        price = row.get("close")
        if type(price) in (float, int) and isfinite(price) and price > 0:
            quoted.append(when)
        else:
            bad_closes += 1
    return sorted(quoted), bad_closes


def _bool_evidence(packet, name):
    """A self-asserted Boolean is still NOT an independent source authentication."""
    return packet.get(name) is True


def _issuer_report(root, market, code, cutoff):
    file = root / market / (code + ".json")
    if not file.is_file():
        return {"market": market, "code": code, "status": "HISTORY_FILE_MISSING",
                "priced_sessions": 0, "calendar_span_days": None,
                "potential_12m_price_only_span": False,
                "historical_PIT_universe_verified": False,
                "dividend_corporate_actions_verified": False,
                "executable_fills_verified": False}
    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
        sessions, gaps = _priced_sessions(doc, market, code, cutoff)
    except (ValueError, TypeError, OSError) as exc:
        return {"market": market, "code": code,
                "status": "INVALID_HISTORICAL_PACKET",
                "reason": str(exc)[:180], "priced_sessions": 0,
                "calendar_span_days": None, "potential_12m_price_only_span": False,
                "historical_PIT_universe_verified": False,
                "dividend_corporate_actions_verified": False,
                "executable_fills_verified": False}
    span = (sessions[-1] - sessions[0]).days if sessions else None
    possible = bool(span is not None and span >= ONE_YEAR_CALENDAR_DAYS
                    and len(sessions) >= MIN_ILLUSTRATIVE_SESSION_COUNT)
    membership = (_bool_evidence(doc, "issuer_PIT_history_verified") and
                  bool(doc.get("official_dated_security_master_receipt")))
    dividend = (_bool_evidence(doc, "share_adjusted_history") and
                _bool_evidence(doc, "dividend_total_return_verified") and
                _bool_evidence(doc, "corporate_actions_verified"))
    execution = doc.get("formal_tradability_gate") == "VERIFIED_EXECUTABLE"
    return {
        "market": market, "code": code, "status": "RAW_HISTORICAL_QUOTES_NOT_A_TRAINING_LABEL",
        "priced_sessions": len(sessions), "unpriced_sessions": gaps,
        "first_priced_session": sessions[0].isoformat() if sessions else None,
        "last_priced_session": sessions[-1].isoformat() if sessions else None,
        "calendar_span_days": span,
        "potential_12m_price_only_span": possible,
        "historical_PIT_universe_verified": membership,
        "dividend_corporate_actions_verified": dividend,
        "executable_fills_verified": execution,
        "issuer_specific_original_publication_PIT_verified": False,
    }


def audit_frozen_pit_gaps(freeze, history_root, price_manifest, financial_manifest,
                          historical_financial_status=None):
    """Count exactly what evidence is present, not forecast/return outcomes.

    A >=365-day archive is a *necessary*, never sufficient, condition.
    No signal-date PIT public-company filing receipts or adjusted executable
    investor total returns can be inferred from retrospective quote data.
    """
    ids = validate_freeze(freeze)
    if not isinstance(price_manifest, dict):
        raise PKContractError("OFFICIAL_QUOTE_MANIFEST_MISSING")
    asof = _iso(price_manifest.get("date"))
    if asof <= _iso(freeze["comparator_vintage_date"]):
        raise PKContractError("NO_POST_FREEZE_REFERENCE_SESSION")
    if price_manifest.get("unadjusted_quotes") is not True:
        raise PKContractError("QUOTE_ADJUSTMENT_STATUS_UNKNOWN")
    if not isinstance(financial_manifest, dict):
        raise PKContractError("FINANCIAL_MANIFEST_MISSING")
    historical_financial_status = historical_financial_status or {}
    root = Path(history_root)
    all_ids = ids["alpha_lane"] | ids["v8_lane"] | {BENCHMARK_KEY}
    detailed = {key: _issuer_report(root, *key, asof) for key in sorted(all_ids)}
    benchmark = detailed[BENCHMARK_KEY]
    lanes = {}
    for lane in ("alpha_lane", "v8_lane"):
        records = [detailed[(r["market"], r["code"])] for r in freeze[lane]["rows"]]
        lanes[lane] = {
            "count": len(records),
            "history_files": sum(r["status"] == "RAW_HISTORICAL_QUOTES_NOT_A_TRAINING_LABEL" for r in records),
            "raw_quote_spans_at_least_12m": sum(r["potential_12m_price_only_span"] for r in records),
            "historical_PIT_universe_verified_count": sum(r["historical_PIT_universe_verified"] for r in records),
            "adjusted_dividend_return_verified_count": sum(r["dividend_corporate_actions_verified"] for r in records),
            "executable_fill_verified_count": sum(r["executable_fills_verified"] for r in records),
            "stocks": records,
        }
    benchmark_one_year = benchmark["potential_12m_price_only_span"]
    financial_pit_ok = (financial_manifest.get("issuer_exact_publication_time_verified") is True and
                        historical_financial_status.get("original_publication_and_revision_PIT_verified") is True and
                        historical_financial_status.get("admitted_historical_PIT_batches", 0) > 0)
    entire_universe_verified = all(
        r["historical_PIT_universe_verified"] for r in detailed.values())
    investor_returns_verified = all(
        r["dividend_corporate_actions_verified"] for r in detailed.values())
    executions_verified = all(r["executable_fills_verified"] for r in detailed.values())
    admitted = (benchmark_one_year and financial_pit_ok and entire_universe_verified
                and investor_returns_verified and executions_verified)
    reasons = []
    if not benchmark_one_year:
        reasons.append("0050_12M_QUOTE_BASELINE_INCOMPLETE")
    if not financial_pit_ok:
        reasons.append("ISSUER_PUBLICATION_AND_REVISION_PIT_NOT_ADMITTED")
    if not entire_universe_verified:
        reasons.append("HISTORICAL_SURVIVOR_AND_SECURITY_MASTER_PROOF_MISSING")
    if not investor_returns_verified:
        reasons.append("DIVIDENDS_SPLITS_DELISTING_TOTAL_RETURN_LEDGER_MISSING")
    if not executions_verified:
        reasons.append("TRADE_EXECUTION_AND_COST_RECEIPTS_NOT_VERIFIED")
    return {
        "schema": SCHEMA,
        "status": "BLOCKED_NO_AUDITED_TRAINING_LABELS" if not admitted
                  else "INPUT_FIELDS_SELF_REPORTED_REQUIRE_INDEPENDENT_AUDIT",
        "asof_price_date": asof.isoformat(),
        "freeze_vintage_date": freeze["comparator_vintage_date"],
        "benchmark_0050": benchmark,
        "lanes": lanes,
        "issuer_publication_pit_admitted": financial_pit_ok,
        "admitted_historical_PIT_batches": historical_financial_status.get("admitted_historical_PIT_batches", 0),
        "self_assertions_are_not_independent_audit": True,
        "verified_12m_after_cost_walk_forward_cohorts": 0,
        "independent_model_alpha_training_ready": False,
        "winner": None,
        "blockers": reasons,
        "priority": [
            "Backfill 0050 official raw monthly OHLC to at least 2025-01 and audit ETF splits/dividends; raw quotes alone remain unadjusted.",
            "Collect as-published issuer financial original filings with true first-release and revision timestamps, not current batch mirrors.",
            "Extend histories for the same investable issuer universe incl. delisted stocks, with dividend, corporate-action and executable trade paths.",
            "Only then reconstruct lagged features and matched matured 12m total-return labels; train AlphaMax using purged OOS folds.",
        ],
        "note": ("A 365-day raw quoted span never certifies an investable 12m total return. "
                 "The 2025/2026 financial mirrors can be retrospectively revised; "
                 "they are NOT valid pre-2026 as-published PIT feature vintages."),
    }
