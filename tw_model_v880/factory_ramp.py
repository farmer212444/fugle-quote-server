"""V8.9.9 factory ramp vs structural margin pressure — independent audit.

Accounting gross margins do not identify factory causality. A detailed
manufacturing-cost bridge can support, but not *prove*, a ramp hypothesis.
This module never changes the official Base, EPS, PE, or certification gates.
"""
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re
from urllib.parse import urlparse

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[0-9]{4}\Z")
_PERIOD = re.compile(r"\d{4}-Q[1-4]\Z")
REQUIRED = ("revenue_twd", "gross_profit_twd", "material_cogs_twd",
            "labor_cogs_twd", "other_variable_cogs_twd", "fixed_manufacturing_cogs_twd",
            "units_sold", "good_units_produced", "capacity_units", "yield_rate",
            "inventory_delta_good_units")
FIELDS = ("material_cogs_twd", "labor_cogs_twd",
          "other_variable_cogs_twd", "fixed_manufacturing_cogs_twd")
ALLOWED_PERIODS = ("prior_comparable", "current")


def _num(value, *, strictly_positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("FACTORY_NONFINITE_OR_MISSING_NUMBER")
    n = float(value)
    if strictly_positive and n <= 0:
        raise ValueError("FACTORY_NONPOSITIVE_DENOMINATOR")
    if nonnegative and n < 0:
        raise ValueError("FACTORY_NEGATIVE_INPUT")
    return n


def _time(raw):
    if not isinstance(raw, str):
        raise ValueError("FACTORY_TIMESTAMP_REQUIRED")
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("FACTORY_TIMESTAMP_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("FACTORY_TIMEZONE_REQUIRED")
    return result.astimezone(timezone.utc)


def _receipt(receipt, *, cutoff, archive_root):
    if not isinstance(receipt, dict) or receipt.get("original_publisher_verified") is not True:
        raise ValueError("FACTORY_ORIGINAL_PUBLISHER_UNVERIFIED")
    url = urlparse(str(receipt.get("url", "")))
    if url.scheme != "https" or not url.hostname:
        raise ValueError("FACTORY_SOURCE_URL_INVALID")
    available = _time(receipt.get("available_at"))
    verified_at = _time(receipt.get("verified_at"))
    if available > cutoff or verified_at > cutoff or verified_at < available:
        raise ValueError("FACTORY_PIT_OR_VERIFICATION_TIME_INVALID")
    digest = str(receipt.get("sha256", ""))
    if not _SHA.fullmatch(digest):
        raise ValueError("FACTORY_SOURCE_SHA_MISSING")
    name = receipt.get("relative_original_path")
    if not isinstance(name, str):
        raise ValueError("FACTORY_RAW_ORIGINAL_NOT_ARCHIVED")
    root = Path(archive_root).resolve()
    actual = (root / name).resolve()
    if not actual.is_relative_to(root) or not actual.is_file():
        raise ValueError("FACTORY_ORIGINAL_PATH_INVALID")
    if hashlib.sha256(actual.read_bytes()).hexdigest() != digest:
        raise ValueError("FACTORY_ORIGINAL_SHA_MISMATCH")
    return dict(url=receipt["url"], sha256=digest, available_at=receipt["available_at"],
                verified_at=receipt["verified_at"], relative_original_path=name)


def _unit_economics(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("FACTORY_COST_SCOPE_MISSING")
    vals = {k: _num(snapshot.get(k), nonnegative=True) for k in REQUIRED}
    revenue = vals["revenue_twd"]
    units = vals["units_sold"]
    good = vals["good_units_produced"]
    cap = vals["capacity_units"]
    if min(revenue, units, good, cap) <= 0:
        raise ValueError("FACTORY_REQUIRED_POSITIVE_INPUT_MISSING")
    y = vals["yield_rate"]
    if not 0 < y <= 1 or good > cap * (1 + 1e-8):
        raise ValueError("FACTORY_YIELD_OR_CAPACITY_INVALID")
    if abs(good - vals["inventory_delta_good_units"] - units) > max(1e-6, units * 0.005):
        raise ValueError("FACTORY_INVENTORY_TO_REVENUE_NOT_RECONCILED")
    cogs = sum(vals[k] for k in FIELDS)
    # Inputs must represent sold-inventory COGS, not production expenditures
    # booked as inventory; otherwise capex/stock-build costs are double counted.
    gross = revenue - cogs
    if abs(gross - vals["gross_profit_twd"]) > max(1., revenue * .001):
        raise ValueError("FACTORY_REVENUE_COGS_BRIDGE_NOT_RECONCILED")
    if gross < 0 or gross > revenue:
        raise ValueError("FACTORY_REVENUE_GROSS_PROFIT_INVALID")
    variable = sum(vals[k] for k in FIELDS[:3])
    fixed = vals["fixed_manufacturing_cogs_twd"]
    return dict(gm=gross/revenue, revenue=revenue, gross_profit=gross,
                variable_cogs=variable, fixed_cogs=fixed,
                variable_burden=variable/revenue, fixed_burden=fixed/revenue,
                units_sold=units, utilization=good/cap,
                realized_asp_twd=revenue/units,
                variable_cost_per_sold_unit_twd=variable/units,
                fixed_cost_per_sold_unit_twd=fixed/units,
                yield_rate=y)


def assess_factory_ramp(case, *, asof, archive_root, accounting):
    """Require two matched-quarter consolidated period bridges with original bytes.

    'accounting' is {prior_comparable:{revenue_twd,gross_profit_twd},
                     current:{...}} for the *same* consolidated issuer.
    This does not certify plant-level causality or forecast Base recovery.
    """
    cutoff = _time(asof)
    if not isinstance(case, dict) or not _CODE.fullmatch(str(case.get("code", ""))):
        raise ValueError("FACTORY_ISSUER_INVALID")
    periods = case.get("periods", {})
    if not isinstance(periods, dict) or set(periods) != set(ALLOWED_PERIODS):
        raise ValueError("FACTORY_PERIODS_MISSING")
    for which in ALLOWED_PERIODS:
        if not _PERIOD.fullmatch(str(periods[which])):
            raise ValueError("FACTORY_PERIOD_INVALID")
    py, pq = periods["prior_comparable"].split("-Q")
    cy, cq = periods["current"].split("-Q")
    if int(cy) != int(py) + 1 or cq != pq:
        raise ValueError("FACTORY_YOY_PERIOD_NOT_COMPARABLE")
    if case.get("scope") != "CONSOLIDATED_MATCHED_PRODUCT_UNITS":
        raise ValueError("FACTORY_SCOPE_NOT_COMPARABLE")
    if case.get("complete_product_mix_and_cost_allocation_verified") is not True:
        raise ValueError("FACTORY_PRODUCT_MIX_COST_ALLOCATION_UNVERIFIED")
    if case.get("inventory_cost_recognition_verified") is not True:
        raise ValueError("FACTORY_INVENTORY_COST_RECOGNITION_UNVERIFIED")
    if case.get("product_unit_definition_unchanged") is not True:
        raise ValueError("FACTORY_MEASUREMENT_UNITS_INCONSISTENT")
    receipts = case.get("original_sources")
    if not isinstance(receipts, list) or len(receipts) < 2:
        raise ValueError("FACTORY_ORIGINAL_SOURCE_COVERAGE_INSUFFICIENT")
    verified = [_receipt(r, cutoff=cutoff, archive_root=archive_root) for r in receipts]
    if len({r["sha256"] for r in verified}) < 2:
        raise ValueError("FACTORY_PRIOR_AND_CURRENT_SOURCE_NOT_DISTINCT")
    if not isinstance(accounting, dict) or set(accounting) != set(ALLOWED_PERIODS):
        raise ValueError("FACTORY_CONSOLIDATED_ACCOUNTING_UNAVAILABLE")
    snapshots = case.get("observations")
    if not isinstance(snapshots, dict) or set(snapshots) != set(ALLOWED_PERIODS):
        raise ValueError("FACTORY_OBSERVATIONS_MISSING")
    calculated = {}
    for period in ALLOWED_PERIODS:
        snap = snapshots[period]
        item = _unit_economics(snap)
        official = accounting[period]
        if not isinstance(official, dict):
            raise ValueError("FACTORY_OFFICIAL_ACCOUNTING_MISSING")
        revenue = _num(official.get("revenue_twd"), strictly_positive=True)
        gross = _num(official.get("gross_profit_twd"))
        if abs(revenue - item["revenue"]) > max(1, revenue*.005) or abs(gross-item["gross_profit"]) > max(1,revenue*.005):
            raise ValueError("FACTORY_ACCOUNTING_ORIGINAL_MIRROR_MISMATCH")
        calculated[period] = item
    old, new = calculated["prior_comparable"], calculated["current"]
    delta_gm = new["gm"]-old["gm"]
    delta_fixed = new["fixed_burden"]-old["fixed_burden"]
    delta_variable = new["variable_burden"]-old["variable_burden"]
    delta_util = new["utilization"]-old["utilization"]
    if abs(delta_gm + delta_fixed + delta_variable) > 1e-7:
        raise ValueError("FACTORY_GM_DECOMPOSITION_NOT_BALANCED")
    # Classification is diagnostic consistency, not proof of a temporary or
    # irreversible factor. The 'structural' hypothesis needs other cycles.
    if delta_gm >= .005 and delta_fixed <= -.005 and delta_util >= .05 and delta_variable <= .005:
        verdict = "RAMP_ABSORPTION_RECOVERY_CONSISTENT"
    elif delta_gm <= -.005 and delta_fixed >= .005 and delta_util <= -.03:
        verdict = "RAMP_FIXED_COST_DILUTION_CONSISTENT"
    elif delta_gm <= -.005 and delta_variable >= .01 and delta_fixed <= .005:
        verdict = "VARIABLE_COST_OR_PRICING_PRESSURE_CONSISTENT"
    elif delta_gm > 0 and delta_fixed >= .005:
        verdict = "RAMP_DILUTION_MASKED_BY_OTHER_IMPROVEMENTS"
    elif abs(delta_variable)>=.005 and abs(delta_fixed)>=.005:
        verdict = "MIXED_FIXED_AND_VARIABLE_DRIVERS"
    else:
        verdict = "FACTORY_DRIVER_CAUSALITY_UNDETERMINED"
    return dict(code=case["code"],status=verdict,
                period_current=periods["current"],period_comparable=periods["prior_comparable"],
                gross_margin_delta_pp=round(100*delta_gm,4),
                fixed_cost_burden_change_pp=round(100*delta_fixed,4),
                variable_cost_burden_change_pp=round(100*delta_variable,4),
                utilization_change_pp=round(100*delta_util,4),
                fixed_absorption_offset_pp=round(-100*delta_fixed,4),
                variable_cost_and_mix_offset_pp=round(-100*delta_variable,4),
                current_utilization_pct=round(100*new["utilization"],4),
                current_yield_pct=round(100*new["yield_rate"],4),
                sources=verified, accounting_reconciliation_verified=True,
                quarterly_plant_learning_curve_causally_proven=False,
                structural_cost_pressure_causally_proven=False,
                price_mix_fx_wage_disaggregation_complete=False,
                forecast_bridge_formal_gate_pass=False,base_gm_override_allowed=False,
                model_eps_pe_target_changed=False,formal_a_plus_changed=False)


def accounting_only(code, prior, current, *, current_period, comparable_period, source):
    """Cheap universe-wide early flag; never a factory-attribution claim."""
    if not _CODE.fullmatch(str(code)):
        raise ValueError("FACTORY_ISSUER_INVALID")
    def compute(row):
        if not isinstance(row, dict):
            raise ValueError("FACTORY_ACCOUNTING_MISSING")
        r = _num(row.get("revenue_twd"), strictly_positive=True)
        g = _num(row.get("gross_profit_twd"))
        op = _num(row.get("operating_profit_twd"))
        if not -r <= g <= r or not -r <= op <= r:
            raise ValueError("FACTORY_ACCOUNTING_IMPLAUSIBLE")
        return r, g, op
    pr, pg, po = compute(prior)
    cr, cg, co = compute(current)
    gm_delta = 100*(cg/cr-pg/pr)
    op_delta = 100*(co/cr-po/pr)
    if gm_delta <= -1:
        state = "OBSERVED_MARGIN_DECLINE_CAUSE_UNVERIFIED"
    elif gm_delta >= 1:
        state = "OBSERVED_MARGIN_IMPROVEMENT_CAUSE_UNVERIFIED"
    else:
        state = "OBSERVED_MARGIN_STABLE_CAUSE_UNVERIFIED"
    return dict(code=str(code),status=state,source=source,financial_period=current_period,
                comparable_period=comparable_period,
                prior_gm_pct=round(100*pg/pr,3),current_gm_pct=round(100*cg/cr,3),
                gm_yoy_change_pp=round(gm_delta,3),
                operating_margin_yoy_change_pp=round(op_delta,3),
                current_revenue_yoy_pct=round(100*(cr/pr-1),3),
                factory_new_capacity_verified=False, utilization_verified=False,
                price_and_product_mix_verified=False,unit_cost_verified=False,
                fixed_cost_allocation_verified=False,inventory_recognition_verified=False,
                classification_plant_ramp_vs_structural="INSUFFICIENT_ORIGINAL_CAUSAL_EVIDENCE",
                forecast_bridge_formal_gate_pass=False,base_gm_override_allowed=False,
                model_eps_pe_target_changed=False,formal_a_plus_changed=False)
