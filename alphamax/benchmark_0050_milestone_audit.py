"""Check 0050 raw-quote coverage at split and ex-dividend milestones.

This audits original-source integrity and mechanical units only. It NEVER
exports return labels, realized investor P&L, a certified total-return index
or a PIT/backtest-ready feature. Retroactively obtained official announcements
are not independently timestamped as-published snapshots.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from alphamax.benchmark_0050_action_audit import (
    CASH_DISTRIBUTION_REFERENCES, PRE_SPLIT_LAST_TRADING_DATE,
    SPLIT_REOPEN_DATE, POST_SPLIT_UNITS_PER_PRE_SPLIT_UNIT,
    audit_0050_corporate_action_gaps,
)
from scripts.alphamax_0050_restore import (
    RELATIVE_PACKET, _packet, _validate_cached_source,
)

SCHEMA = "ALPHAMAX_0050_SPLIT_DIVIDEND_MILESTONES_V1"


def _decimal_price(value):
    if type(value) not in (int, float):
        raise ValueError("0050_MILESTONE_CLOSE_TYPE_INVALID")
    try:
        out = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("0050_MILESTONE_CLOSE_INVALID") from exc
    if not out.is_finite() or out <= 0:
        raise ValueError("0050_MILESTONE_CLOSE_INVALID")
    return out


def _event_milestones(packet, source_audit):
    by_date = {row["date"]: row for row in packet["sessions"]}
    cutoff = packet["price_reference_asof"]
    # Each date is from source-checked official announcements. A missing date
    # is a provenance gap, never silently substituted by adjacent prices.
    events = [
        ("LAST_PRE_SPLIT_SESSION", PRE_SPLIT_LAST_TRADING_DATE.isoformat(), 1, None),
        ("FIRST_POST_SPLIT_SESSION", SPLIT_REOPEN_DATE.isoformat(),
         POST_SPLIT_UNITS_PER_PRE_SPLIT_UNIT, None),
    ]
    if source_audit["retrospective_notice_reverification"]["verified_count"] != 6:
        return [], ["0050_NOTICE_RECEIPTS_INCOMPLETE"]
    for i, (exdate, paydate, cash, basis) in enumerate(CASH_DISTRIBUTION_REFERENCES):
        if exdate > cutoff:
            continue
        units = 1 if basis == "PRE_2025_SPLIT_UNIT" else POST_SPLIT_UNITS_PER_PRE_SPLIT_UNIT
        events.append(("EX_DIVIDEND_" + str(i + 1), exdate, units,
                       {"scheduled_payment_date": paydate,
                        "per_unit_reference_ntd": str(Decimal(str(cash))),
                        "reference_gross_cash_per_original_unit_ntd":
                            str(Decimal(str(cash)) * units)}))
    missing = []
    milestones = []
    for name, day, units, cash in sorted(events, key=lambda x: (x[1], x[0])):
        if day > cutoff:
            continue
        raw = by_date.get(day)
        if raw is None:
            missing.append(name + ":" + day)
            continue
        value = _decimal_price(raw["close"])
        milestones.append({
            "event": name, "date": day, "raw_close_ntd_per_current_unit": str(value),
            "reference_units_per_pre_split_unit": units,
            "mechanical_market_value_ntd_per_pre_split_unit": str(value * units),
            "cash_reference": cash,
            "price_and_holding_unit_alignment_only": True,
            "historical_pit_event_or_trade_certified": False,
        })
    return milestones, missing


def audit_0050_milestones(price_root, notice_root):
    """Recheck TWSE monthly originals and notices before publishing milestones."""
    price_root = Path(price_root)
    packet = _packet(price_root / RELATIVE_PACKET)
    # Explicitly verify source archive bytes and normalized monthly rows:
    # a convenient packet alone is not evidence.
    _validate_cached_source(price_root, packet, packet["price_reference_asof"])
    action = audit_0050_corporate_action_gaps(packet, notice_root=notice_root)
    milestones, missing = _event_milestones(packet, action)
    verified_six = action["retrospective_notice_reverification"]["verified_count"] == 6
    aligned = verified_six and not missing and len(milestones) == 6
    return {
        "schema": SCHEMA,
        "status": ("RETROSPECTIVE_MILESTONE_PRICE_UNITS_ALIGNED_NOT_PIT"
                   if aligned else "BLOCKED_0050_MILESTONE_SOURCE_OR_PRICE_GAPS"),
        "source_price_reference_asof": packet["price_reference_asof"],
        "raw_quote_session_count": action["raw_price_session_count"],
        "notices_rechecked": action["retrospective_notice_reverification"]["verified_count"],
        "milestones": milestones,
        "missing_or_unverified_milestones": missing,
        "aligned_milestones": len(milestones),
        "investor_total_return_certified": False,
        "adjusted_benchmark_certified": False,
        "bank_payment_receipts_verified": False,
        "historical_pit_publication_copy_verified": False,
        "execution_costs_verified": False,
        "verified_12m_after_cost_oos_cohorts": 0,
        "official_pk_winner": None,
        "notice": "Mechanical 1-to-4 unit normalization is a reference only. "
                  "Do not use these raw-quote milestone values as total returns, "
                  "actual investor wealth, historical PIT labels or buy signals.",
    }


def audit_0050_milestones_json(price_root, notice_root, output):
    report = audit_0050_milestones(price_root, notice_root)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")
    return report
