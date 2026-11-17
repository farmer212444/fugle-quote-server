"""Fail-closed 0050 historical share-split and cash-distribution gap audit.

The exchange's dated event notice is a research reference, not a saved,
independently authenticated original receipt. Raw prices are NOT total returns.
No adjusted return, model label, probability, rank, weight, or buy signal
may be computed by this module.
"""
from __future__ import annotations

from datetime import date
from math import isfinite

SCHEMA = "ALPHAMAX_0050_ACTION_GAP_AUDIT_V1"
SPLIT_NOTICE_URL = (
    "https://www.twse.com.tw/zh/ETFortune/announcement"
    "?company=A00005&date=20250509&fund=0050&seq=1&type=other"
)
DISTRIBUTION_REFERENCE_URL = "https://www.twse.com.tw/zh/ETFortune/etfInfo/0050"
SPLIT_ANNOUNCED_AT = "2025-05-09T15:14:16+08:00"
PRE_SPLIT_LAST_TRADING_DATE = date(2025, 6, 10)
SPLIT_REOPEN_DATE = date(2025, 6, 18)
POST_SPLIT_UNITS_PER_PRE_SPLIT_UNIT = 4

# Dates and values are public historical *reference observations*.
# Ex-dates require further reconciliation to the dated fund notices.
# The 2025-01 payment is in pre-split units (2.70), not the split-
# normalized 0.675 that some historical display services show.
CASH_DISTRIBUTION_REFERENCES = (
    ("2025-01-17", "2025-02-20", 2.70, "PRE_2025_SPLIT_UNIT"),
    ("2025-07-21", "2025-08-08", 0.36, "POST_2025_SPLIT_UNIT"),
    ("2026-01-22", "2026-02-11", 1.00, "POST_2025_SPLIT_UNIT"),
    ("2026-07-21", "2026-08-10", 0.60, "POST_2025_SPLIT_UNIT"),
)


def _iso(x):
    if not isinstance(x, str):
        raise ValueError("0050_DATE_STRING_REQUIRED")
    try:
        value = date.fromisoformat(x)
    except ValueError as exc:
        raise ValueError("0050_DATE_INVALID") from exc
    if value.isoformat() != x:
        raise ValueError("0050_DATE_NONCANONICAL")
    return value


def audit_0050_corporate_action_gaps(packet):
    if not isinstance(packet, dict) or packet.get("issuer") != "0050" or packet.get("market") != "TWSE":
        raise ValueError("0050_ACTION_AUDIT_SECURITY_IDENTITY_MISMATCH")
    asof = _iso(packet.get("price_reference_asof"))
    sessions = packet.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("0050_ACTION_AUDIT_PRICE_SESSIONS_MISSING")
    dates = []
    seen = set()
    for row in sessions:
        if not isinstance(row, dict) or row.get("market") != "TWSE" or row.get("code") != "0050":
            raise ValueError("0050_ACTION_AUDIT_SESSION_IDENTITY_MISMATCH")
        day = _iso(row.get("date"))
        if day in seen:
            raise ValueError("0050_ACTION_AUDIT_DUPLICATE_SESSION")
        if day > asof:
            raise ValueError("0050_ACTION_AUDIT_FUTURE_SESSION")
        close = row.get("close")
        if type(close) not in (float, int) or not isfinite(close) or close <= 0:
            raise ValueError("0050_ACTION_AUDIT_INVALID_RAW_CLOSE")
        if PRE_SPLIT_LAST_TRADING_DATE < day < SPLIT_REOPEN_DATE:
            raise ValueError("0050_ACTION_AUDIT_PRICE_ON_OFFICIAL_SPLIT_SUSPENSION")
        dates.append(day)
        seen.add(day)
    dates.sort()
    before_split = any(d <= PRE_SPLIT_LAST_TRADING_DATE for d in dates)
    after_split = any(d >= SPLIT_REOPEN_DATE for d in dates)
    crosses = before_split and after_split
    return {
        "schema": SCHEMA,
        "status": "BLOCKED_0050_SPLIT_AND_CASH_DISTRIBUTION_TOTAL_RETURN_LEDGER",
        "issuer": "0050",
        "market": "TWSE",
        "price_reference_asof": asof.isoformat(),
        "raw_price_session_count": len(dates),
        "first_raw_session": dates[0].isoformat(),
        "last_raw_session": dates[-1].isoformat(),
        "raw_prices_span_split_date": crosses,
        "split_event": {
            "announced_at_taipei": SPLIT_ANNOUNCED_AT,
            "announcement_reference_url": SPLIT_NOTICE_URL,
            "pre_split_last_trading_date": PRE_SPLIT_LAST_TRADING_DATE.isoformat(),
            "resumed_trading_date": SPLIT_REOPEN_DATE.isoformat(),
            "post_split_units_per_pre_split_unit": POST_SPLIT_UNITS_PER_PRE_SPLIT_UNIT,
            "raw_quote_at_last_pre_split_session": PRE_SPLIT_LAST_TRADING_DATE in seen,
            "raw_quote_at_first_post_split_session": SPLIT_REOPEN_DATE in seen,
            "original_announcement_bytes_archived_and_verified": False,
            "price_and_holdings_split_adjustment_ledger_verified": False,
        },
        "distribution_reference_url": DISTRIBUTION_REFERENCE_URL,
        "cash_distribution_reference_candidates": [
            {
                "ex_dividend_date": ex_date,
                "payment_date": payment_date,
                "cash_paid_ntd_per_unit_at_event_vintage": cash,
                "unit_basis": basis,
                "original_fund_notice_bytes_and_payment_verified": False,
                "reconciled_to_adjusted_total_return": False,
            }
            for ex_date, payment_date, cash, basis in CASH_DISTRIBUTION_REFERENCES
            if _iso(ex_date) <= asof
        ],
        "historical_source_announced_at_vintages_verified": False,
        "cash_dividend_and_split_ledger_complete": False,
        "daily_adjusted_investor_total_returns_verified": False,
        "oos_12m_after_cost_cohorts_verified": 0,
        "official_model_winner": None,
        "formal_Aplus": False,
        "live_buy_authorized": False,
        "blockers": [
            "0050_OFFICIAL_SPLIT_ORIGINAL_ANNOUNCEMENT_BYTES_NOT_ARCHIVED",
            "0050_2025_4_FOR_1_SPLIT_ADJUSTED_HOLDINGS_AND_PRICE_LEDGER_MISSING",
            "0050_CASH_DISTRIBUTION_ORIGINAL_NOTICES_AND_UNIT_VINTAGES_NOT_RECONCILED",
            "0050_DIVIDEND_INCLUSIVE_TOTAL_RETURN_SERIES_NOT_INDEPENDENTLY_VERIFIED",
            "PIT_SECURITY_MASTER_AND_RESTATEMENT_RECEIPTS_MISSING",
        ],
        "notice": "Reference event chronology is not an independently certified "
                  "corporate-action ledger. Never divide pre/post-split raw prices "
                  "or infer performance, model rankings, or investable returns.",
    }
