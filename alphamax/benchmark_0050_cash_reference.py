"""0050 source-linked, non-reinvesting gross entitlement reference *not* total return.

Theoretical continuous owner of ONE 0050 unit before the 2025 4-for-1 split:
- 1 raw-price unit until 2025-06-10 inclusive, 4 starting 2025-06-18;
- cash entitlement accrues on the official ex-dividend session;
- its *scheduled* payment date is only a bookkeeping date, not bank evidence.

The reference can sanity-check financial-accounting mechanics but is NOT
investor P&L, executable performance, an independently archived as-of PIT
history, a costed benchmark, model label, candidate rank or buy authorization.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from pathlib import Path

from alphamax.benchmark_0050_action_audit import (
    POST_SPLIT_UNITS_PER_PRE_SPLIT_UNIT,
    PRE_SPLIT_LAST_TRADING_DATE,
    SPLIT_REOPEN_DATE,
    audit_0050_corporate_action_gaps,
)
from alphamax.benchmark_0050_milestone_audit import (
    audit_0050_milestones, _decimal_price,
)
from scripts.alphamax_0050_restore import RELATIVE_PACKET, _packet

SCHEMA = "ALPHAMAX_0050_UNREINVESTED_GROSS_ENTITLEMENT_REFERENCE_V1"


def _fmt(value):
    return str(value)


def build_cash_reference(price_root, notice_root):
    """Revalidate original quote and notice receipts; fail closed on any gap."""
    milestone = audit_0050_milestones(price_root, notice_root)
    if milestone["status"] != "RETROSPECTIVE_MILESTONE_PRICE_UNITS_ALIGNED_NOT_PIT":
        return {
            "schema": SCHEMA,
            "status": "BLOCKED_0050_REFERENCE_SOURCE_OR_EVENT_GAPS",
            "milestone_status": milestone["status"],
            "missing_events": milestone["missing_or_unverified_milestones"],
            "rows": [],
            "eligible_for_pit_or_oos_training": False,
            "investor_total_return_certified": False,
            "after_cost_12m_cohorts_verified": 0,
        }
    packet = _packet(Path(price_root) / RELATIVE_PACKET)
    latest_raw_day = max(r["date"] for r in packet["sessions"])
    if latest_raw_day != packet["price_reference_asof"]:
        return {
            "schema": SCHEMA,
            "status": "BLOCKED_0050_REFERENCE_LAST_RAW_QUOTE_STALE",
            "source_price_reference_asof": packet["price_reference_asof"],
            "latest_raw_quote_day": latest_raw_day,
            "missing_events": ["0050_RAW_PRICE_NOT_AT_PINNED_ASOF"],
            "rows": [],
            "eligible_for_pit_or_oos_training": False,
            "investor_total_return_certified": False,
            "after_cost_12m_cohorts_verified": 0,
        }
    action = audit_0050_corporate_action_gaps(packet, notice_root=notice_root)
    entitlements = action["continuous_holding_reference_cash_entitlements"]
    if len(entitlements) != 4 or not action["raw_prices_span_split_date"]:
        return {
            "schema": SCHEMA,
            "status": "BLOCKED_0050_REFERENCE_ENTITLEMENTS_OR_SPLIT",
            "missing_events": ["SPLIT_OR_FOUR_DISTRIBUTIONS_UNVERIFIED"],
            "rows": [],
            "eligible_for_pit_or_oos_training": False,
            "investor_total_return_certified": False,
            "after_cost_12m_cohorts_verified": 0,
        }
    days = sorted(packet["sessions"], key=lambda row: row["date"])
    payout_by_ex = {x["ex_dividend_date"]: x for x in entitlements}
    if len(payout_by_ex) != 4:
        raise ValueError("0050_DUPLICATE_EX_DIVIDEND_EVENTS")
    split_date = SPLIT_REOPEN_DATE.isoformat()
    last_pre_split = PRE_SPLIT_LAST_TRADING_DATE.isoformat()
    accrued = Decimal("0")
    rows = []
    processed = set()
    for row in days:
        day = row["date"]
        if last_pre_split < day < split_date:
            raise ValueError("0050_SPLIT_SUSPENSION_QUOTE_PRESENT")
        if day in payout_by_ex:
            if day in processed:
                raise ValueError("0050_CASH_ENTITLEMENT_DUPLICATED")
            accrued += Decimal(payout_by_ex[day]["reference_gross_cash_per_original_pre_split_unit_ntd"])
            processed.add(day)
        unit_count = (1 if day <= last_pre_split else POST_SPLIT_UNITS_PER_PRE_SPLIT_UNIT)
        price = _decimal_price(row["close"])
        market_value = price * unit_count
        # The announcement's scheduled payment date is not proof of cash
        # receipt. Keep accrued reference rights distinct from that schedule.
        scheduled = sum(
            (Decimal(item["reference_gross_cash_per_original_pre_split_unit_ntd"])
             for item in entitlements
             if item["ex_dividend_date"] <= day and
                item["scheduled_payment_date"] <= day),
            Decimal("0"))
        if scheduled > accrued:
            raise ValueError("0050_SCHEDULE_EXCEEDS_GROSS_ENTITLEMENT")
        rows.append({
            "date": day,
            "source_price_only_close_ntd": _fmt(price),
            "mechanical_units_per_original_pre_split_unit": unit_count,
            "mechanical_raw_quote_market_value_reference_ntd": _fmt(market_value),
            "cumulative_gross_dividend_rights_reference_ntd": _fmt(accrued),
            "of_which_scheduled_payment_date_passed_reference_ntd": _fmt(scheduled),
            "remaining_notional_payment_scheduled_reference_ntd": _fmt(accrued - scheduled),
            "mechanical_market_value_plus_gross_rights_reference_ntd": _fmt(market_value + accrued),
            "dividend_event_source_sha256": (
                payout_by_ex[day]["source_original_sha256"] if day in payout_by_ex else None),
            "actual_payment_received_verified": False,
            "historical_pit_available_verified": False,
        })
    if len(processed) != 4:
        # Exact ex-date quotation already required by milestone audit.
        raise ValueError("0050_GROSS_ENTITLEMENT_EVENT_NOT_APPLIED")
    return {
        "schema": SCHEMA,
        "status": "RETROSPECTIVE_GROSS_CASH_RIGHTS_REFERENCE_NOT_PIT_OR_TOTAL_RETURN",
        "assumption": "ONE_0050_PRE_2025_SPLIT_UNIT_CONTINUOUSLY_HELD_NO_REINVESTMENT",
        "price_asof": packet["price_reference_asof"],
        "notice_originals_reverified": action["retrospective_notice_reverification"]["verified_count"],
        "source_verified_ex_date_events": len(processed),
        "days": len(rows),
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
        "last_reference": rows[-1],
        "rows": rows,
        "recorded_scheduled_payment_is_actual_bank_payment": False,
        "after_tax_cash_receipts_verified": False,
        "actual_historical_position_verified": False,
        "independently_archived_original_pit_announcement_versions_verified": False,
        "independent_total_return_benchmark_certified": False,
        "reinvestment_prices_verified": False,
        "transaction_costs_verified": False,
        "eligible_for_pit_or_oos_training": False,
        "investor_total_return_certified": False,
        "after_cost_12m_cohorts_verified": 0,
        "official_model_winner": None,
        "formal_a_plus": False,
        "notice": "Not a return/wealth index, investable P&L or PIT signal. "
                  "Gross rights accrue on ex-dates; scheduled payment is not bank receipt. "
                  "No taxes, fees, reinvestment or actual trade execution proven.",
    }


def save_cash_reference(price_root, notice_root, output):
    report = build_cash_reference(price_root, notice_root)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True,
                                 indent=2) + "\n", encoding="utf-8")
    return report
