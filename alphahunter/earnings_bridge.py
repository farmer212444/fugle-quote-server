"""As-of fundamental earnings bridge for AlphaHunter research.

Independently derives scenario EPS from recorded financial inputs, not analyst
consensus, target prices, V8 or AlphaMax scores. Declared timestamps and
references are NOT an independent source audit.
"""
from __future__ import annotations
from datetime import date
from .core import EvidenceError, SCENARIOS, _day, _num


def build_eps_scenarios(financials, assumptions, signal_date):
    """Return input-compatible bear/base/bull research scenarios.

    Monetary units: raw TWD for sales, non-operating profit and net profit;
    diluted shares: number of ordinary shares, not lots or shares in millions.
    Assumptions: decimal fractions except multiple and per-share dividends.
    Includes no financing share-issuance changes after the as-of timestamp.
    """
    asof = _day(signal_date, "signal_date")
    if asof > date.today():
        raise EvidenceError("ASOF_IN_FUTURE")
    if not isinstance(financials, dict) or not isinstance(assumptions, dict):
        raise EvidenceError("BRIDGE_INPUT_REQUIRED")
    period = _day(financials.get("trailing_period_end"), "trailing_period_end")
    reported = _day(financials.get("financials_available_at"), "financials_available_at")
    shares_at = _day(financials.get("share_count_available_at"), "share_count_available_at")
    if not (period <= reported <= asof) or shares_at > asof:
        raise EvidenceError("UNAVAILABLE_ASOF_FINANCIALS")
    receipts = financials.get("source_receipts")
    if (not isinstance(receipts, list) or not receipts
        or any(not isinstance(x, str) or not x.strip() for x in receipts)):
        raise EvidenceError("FINANCIAL_SOURCE_REFERENCES_REQUIRED")
    revenue = _num(financials.get("trailing_revenue_twd"), "trailing_revenue_twd")
    shares = _num(financials.get("diluted_shares"), "diluted_shares")
    if revenue <= 0 or shares <= 0:
        raise EvidenceError("INVALID_BRIDGE_UNITS")
    if set(assumptions) != set(SCENARIOS):
        raise EvidenceError("BRIDGE_SCENARIOS_REQUIRED")

    output = {}
    projections = {}
    for name in SCENARIOS:
        spec = assumptions[name]
        if not isinstance(spec, dict):
            raise EvidenceError("BRIDGE_SCENARIO_INVALID")
        required = {
            "assumption_available_at", "revenue_growth", "gross_margin",
            "opex_ratio", "net_nonoperating_twd", "tax_rate", "pe", "dividend",
        }
        if set(spec) != required:
            raise EvidenceError("BRIDGE_ASSUMPTIONS_INCOMPLETE")
        if _day(spec["assumption_available_at"], "assumption_available_at") > asof:
            raise EvidenceError("FUTURE_BRIDGE_ASSUMPTIONS")
        growth = _num(spec["revenue_growth"], "revenue_growth")
        margin = _num(spec["gross_margin"], "gross_margin")
        expenses = _num(spec["opex_ratio"], "opex_ratio")
        other = _num(spec["net_nonoperating_twd"], "net_nonoperating_twd")
        tax = _num(spec["tax_rate"], "tax_rate")
        pe = _num(spec["pe"], "pe")
        dividend = _num(spec["dividend"], "dividend")
        if (growth < -1.0 or not 0 <= margin <= 1 or not 0 <= expenses <= 1
            or not 0 <= tax <= 1 or pe <= 0 or dividend < 0):
            raise EvidenceError("BRIDGE_ASSUMPTION_OUT_OF_DOMAIN")
        sales = revenue * (1 + growth)
        gross_profit = sales * margin
        operating_profit = gross_profit - sales * expenses
        pretax = operating_profit + other
        net_profit = pretax * (1-tax) if pretax > 0 else pretax
        raw_eps = net_profit / shares
        # A P/E multiple is undefined on losses. Proxy floor of zero here is
        # pessimistic book-asset value exclusion, NOT a certified fair value.
        eps = max(raw_eps, 0.0)
        output[name] = {"eps": eps, "pe": pe, "dividend": dividend}
        projections[name] = {
            "revenue_twd": sales,
            "gross_profit_twd": gross_profit,
            "operating_profit_twd": operating_profit,
            "net_profit_twd": net_profit,
            "raw_eps": raw_eps,
            "eps_clipped_at_zero_due_to_loss": raw_eps < 0,
        }
    values = [output[x]["eps"] * output[x]["pe"] + output[x]["dividend"] for x in SCENARIOS]
    if values != sorted(values):
        raise EvidenceError("BRIDGE_SCENARIO_VALUES_NOT_ORDERED")
    return {
        "status": "UNCALIBRATED_RESEARCH_ONLY",
        "scenarios": output,
        "income_bridge": projections,
        "source_references_proven": False,
        "probabilities_calibrated": False,
        "loss_making_scenario_not_pe_valued": any(
            projections[x]["eps_clipped_at_zero_due_to_loss"] for x in SCENARIOS
        ),
    }
