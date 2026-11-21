"""Explicit fiscal-year horizon for AlphaHunter's independent 2027 EPS scenarios.

No analyst estimates, no adjustment to V8 or AlphaMax. All values are
assumptions; validation cannot prove that a source existed on the cited date.
"""
from __future__ import annotations
from datetime import date
import math

from .core import EvidenceError, SCENARIOS, _day, _num
from .earnings_bridge import build_eps_scenarios

MAX_FISCAL_HORIZON_YEARS = 3


def build_fiscal_year_scenarios(financials, scenarios, asof, target_fiscal_year):
    """Compound explicit yearly sales growth before projecting target-year EPS.

    Financial baseline MUST be a full calendar fiscal year ending Dec 31;
    revenue amounts must be raw TWD and diluted shares raw units.
    Sales growth for each interim year is explicit rather than multiplying
    the 2025 baseline by a single '2027 growth' assumption.
    """
    asof_date = _day(asof, "asof")
    if asof_date > date.today():
        raise EvidenceError("ASOF_IN_FUTURE")
    if not isinstance(financials, dict) or not isinstance(scenarios, dict):
        raise EvidenceError("FISCAL_BRIDGE_INPUT_REQUIRED")
    baseline = _day(financials.get("trailing_period_end"), "trailing_period_end")
    if (baseline.month, baseline.day) != (12, 31):
        raise EvidenceError("FULL_YEAR_DEC31_BASELINE_REQUIRED")
    if (isinstance(target_fiscal_year, bool)
            or not isinstance(target_fiscal_year, int)):
        raise EvidenceError("INVALID_TARGET_FISCAL_YEAR")
    years = list(range(baseline.year + 1, target_fiscal_year + 1))
    if not 1 <= len(years) <= MAX_FISCAL_HORIZON_YEARS:
        raise EvidenceError("UNSUPPORTED_FORECAST_HORIZON")
    if set(scenarios) != set(SCENARIOS):
        raise EvidenceError("FISCAL_SCENARIOS_REQUIRED")
    baseline_sales = _num(financials.get("trailing_revenue_twd"), "trailing_revenue_twd")
    if baseline_sales <= 0:
        raise EvidenceError("INVALID_BASELINE_REVENUE")
    compact = {}
    revenue_paths = {}
    for name in SCENARIOS:
        spec = scenarios[name]
        if not isinstance(spec, dict):
            raise EvidenceError("FISCAL_SCENARIO_INVALID")
        required = {
            "assumption_available_at", "annual_revenue_growth", "gross_margin",
            "opex_ratio", "net_nonoperating_twd", "tax_rate", "pe", "dividend",
        }
        if set(spec) != required:
            raise EvidenceError("FISCAL_ASSUMPTIONS_INCOMPLETE")
        if _day(spec["assumption_available_at"], "assumption_available_at") > asof_date:
            raise EvidenceError("FUTURE_FISCAL_ASSUMPTION")
        growth = spec["annual_revenue_growth"]
        if not isinstance(growth, dict) or set(growth) != {str(y) for y in years}:
            raise EvidenceError("INTERMEDIATE_REVENUE_GROWTH_MISSING")
        sales = baseline_sales
        each_year_sales = {}
        for year in years:
            change = _num(growth[str(year)], "revenue_growth_" + str(year))
            if change < -1:
                raise EvidenceError("IMPOSSIBLE_ANNUAL_REVENUE_GROWTH")
            sales *= 1 + change
            if not math.isfinite(sales):
                raise EvidenceError("NONFINITE_PROJECTED_REVENUE")
            each_year_sales[str(year)] = sales
        revenue_paths[name] = each_year_sales
        compact[name] = {
            k: spec[k] for k in (
                "assumption_available_at", "gross_margin", "opex_ratio",
                "net_nonoperating_twd", "tax_rate", "pe", "dividend",
            )
        }
        compact[name]["revenue_growth"] = (sales / baseline_sales) - 1
    result = build_eps_scenarios(financials, compact, asof)
    result["target_fiscal_year"] = target_fiscal_year
    result["baseline_fiscal_year"] = baseline.year
    result["annual_revenue_path_twd"] = revenue_paths
    result["annual_path_method"] = "COMPOUNDED_DISCLOSED_ASSUMPTIONS_NOT_VERIFIED"
    result["forecast_horizon_years"] = len(years)
    return result
