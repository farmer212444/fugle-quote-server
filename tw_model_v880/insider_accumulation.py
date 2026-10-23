"""Fail-closed research overlay for identified insider *market trades*.

This module never upgrades formal issuer quality gates, A+/A++, EPS/PE, or Exit.
Inputs are archived evidence assertions requiring separate source audit; even a
research watch is NOT a verified purchase recommendation or backtest signal.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_ORIGINAL = "OFFICIAL_MOPS_POST_TRADE_ORIGINAL"


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_EVIDENCE_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TIMESTAMP_MUST_HAVE_OFFSET")
    return parsed


def _period(value: str) -> int:
    if not isinstance(value, str) or not _MONTH.fullmatch(value):
        raise ValueError("INVALID_REPORTING_MONTH")
    year, month = map(int, value.split("-"))
    return year * 12 + month


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _pending(reason: str, **context: Any) -> dict:
    return {
        "status": reason,
        "signal_lane": "UNPROMOTED_RESEARCH_SHADOW",
        "formal_insider_quality_gate": "PENDING_INDEPENDENT_MOPS_AUDIT",
        "new_formal_Aplus": False,
        "eps_pe_override": False,
        "automatic_exit": False,
        "backtest_eligible": False,
        "independently_certified": False,
        **context,
    }


def evaluate_insider_accumulation(
    records: list[dict],
    *,
    decision_at: str,
    issued_shares: int | None,
    issued_shares_asof: str | None = None,
    issued_shares_original_sha256: str | None = None,
    minimum_three_month_fraction: float = 0.0005,
) -> dict:
    """Assess a three-consecutive-month accumulation research candidate.

    issued_shares are individual *shares*, trade inputs are 1000-share lots.
    Minimum three-month buy-minus-sell materiality defaults to 0.05% of stock
    capital, an UNCALIBRATED heuristic. A negative month breaks persistence.
    Every reporting month must have original market-trade declarations, receipt
    and publication timestamps, stable holder reconciliation, and market-vs-
    transfer classification. No derived secondary summary can become PASS.
    """
    decision = _time(decision_at)
    if not 0 < minimum_three_month_fraction < 1:
        raise ValueError("INVALID_HEURISTIC_FRACTION")
    if not isinstance(records, list):
        raise ValueError("INVALID_RECORDS")
    if not _nonnegative_int(issued_shares) or not issued_shares:
        return _pending("PENDING_OFFICIAL_SHARES_DENOMINATOR")
    if (not isinstance(issued_shares_original_sha256, str)
            or not _SHA256.fullmatch(issued_shares_original_sha256)
            or not issued_shares_asof):
        return _pending("PENDING_SHARES_SOURCE_OR_DATE")
    if _time(issued_shares_asof) > decision:
        return _pending("PENDING_FUTURE_SHARES_SOURCE")

    seen: dict[int, dict] = {}
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("INVALID_RECORD_ROW")
        month = _period(row.get("month"))
        if month in seen:
            return _pending("PENDING_DUPLICATE_REPORTING_MONTH")
        seen[month] = row

    # Restrict to the last fully ended calendar month as of a decision.
    latest_ended = decision.year * 12 + decision.month - 1
    needed = (latest_ended - 2, latest_ended - 1, latest_ended)
    if any(month not in seen for month in needed):
        return _pending("PENDING_THREE_CONSECUTIVE_MONTHS",
                        missing_month_count=sum(month not in seen for month in needed))

    net_lots: list[int] = []
    for month in needed:
        row = seen[month]
        if row.get("source_kind") != _ORIGINAL:
            return _pending("PENDING_OFFICIAL_MARKET_TRADE_ORIGINAL")
        if (not isinstance(row.get("original_sha256"), str)
                or not _SHA256.fullmatch(row["original_sha256"])):
            return _pending("PENDING_ORIGINAL_BYTES_HASH")
        if (row.get("holder_identity_reconciled") is not True
                or row.get("holdings_rollforward_reconciled") is not True
                or row.get("market_vs_transfer_reconciled") is not True):
            return _pending("PENDING_IDENTITY_TRANSFER_OR_ROLLFORWARD")
        if not all(_nonnegative_int(row.get(k)) for k in
                   ("market_buy_lots", "market_sell_lots")):
            return _pending("PENDING_MARKET_TRADE_QUANTITIES")
        if not row.get("published_at") or not row.get("receipt_at"):
            return _pending("PENDING_PUBLICATION_RECEIPT")
        published = _time(row["published_at"])
        receipt = _time(row["receipt_at"])
        if published > decision or receipt > decision or receipt < published:
            return _pending("PENDING_PIT_PUBLICATION_OR_RECEIPT")
        net_lots.append(row["market_buy_lots"] - row["market_sell_lots"])

    three_month_net = sum(net_lots)
    share_fraction = three_month_net * 1000 / issued_shares
    base = {"three_month_net_lots": three_month_net,
            "three_month_net_fraction_of_shares": round(share_fraction, 8),
            "report_months_checked": [f"{(m-1)//12:04d}-{((m-1)%12)+1:02d}" for m in needed],
            "minimum_fraction_uncalibrated": minimum_three_month_fraction}
    if any(n <= 0 for n in net_lots):
        return _pending("NO_THREE_MONTH_PERSISTENCE", **base)
    if share_fraction < minimum_three_month_fraction:
        return _pending("POSITIVE_BUT_LOW_MATERIALITY", **base)
    return _pending("RESEARCH_WATCH_REQUIRES_INDEPENDENT_AUDIT", **base)
