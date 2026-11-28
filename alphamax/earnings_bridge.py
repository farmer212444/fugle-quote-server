"""Independent operating-to-EPS scenarios; no calibrated forecasts or buy signal.

All money inputs are TWD and shares are actual shares, never thousands of
shares. Scenario assumptions and source declarations remain unverified inputs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import sys
from urllib.parse import urlparse

from alphamax.core import ContractError, parse_date


SCENARIOS = ("bear", "base", "bull")
OPERATING_FIELDS = (
    "revenue_twd", "gross_margin", "operating_expenses_twd", "other_operating_income_twd",
    "net_nonoperating_income_twd", "effective_tax_rate",
    "noncontrolling_profit_twd", "diluted_shares", "exit_pe",
    "net_dividends_per_share_twd",
)
COST_FIELDS = (
    "buy_fee_rate", "buy_slippage_rate", "sell_fee_rate",
    "sell_tax_rate", "sell_slippage_rate",
)


def _number(value, name, minimum=None, maximum=None):
    if type(value) not in (int, float) or not isfinite(value):
        raise ContractError("NONFINITE_OR_NONNUMERIC:" + name)
    if minimum is not None and value < minimum:
        raise ContractError("BELOW_MINIMUM:" + name)
    if maximum is not None and value > maximum:
        raise ContractError("ABOVE_MAXIMUM:" + name)
    return value


def _time(value):
    if not isinstance(value, str):
        raise ContractError("TIMESTAMP_MUST_BE_STRING")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("INVALID_TIMESTAMP") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ContractError("TIMESTAMP_REQUIRES_TIMEZONE")
    return stamp.astimezone(timezone.utc)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ContractError("NONEMPTY_TEXT_REQUIRED:" + name)
    return value


def earnings_bridge(spec, *, now=None):
    """Compute transparent annual EPS/valuation scenarios from explicit inputs.

    This does not estimate the scenario inputs, authenticate source bytes,
    assign probabilities, certify A+, or provide portfolio weights. Dividends
    are net cash per initial share received by valuation_date, without
    reinvestment. Ordinary positive-EPS P/E valuation only; no bank/insurance
    balance-sheet model, split/conversion simulation or loss-company pricing.
    """
    if not isinstance(spec, dict) or spec.get("schema") != "alphamax-earnings-bridge-v2":
        raise ContractError("INVALID_EARNINGS_BRIDGE_SCHEMA")
    if any(k in spec for k in ("probabilities", "expected_net_return_12m", "weights")):
        raise ContractError("CALIBRATED_PREDICTIONS_OR_WEIGHTS_NOT_SUPPORTED")
    code = _text(spec.get("code"), "code")
    if spec.get("currency") != "TWD" or spec.get("shares_unit") != "shares":
        raise ContractError("EXPLICIT_TWD_AND_ACTUAL_SHARES_REQUIRED")
    asof = _time(spec.get("asof"))
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ContractError("CURRENT_TIME_REQUIRES_TIMEZONE")
    if asof > now:
        raise ContractError("ASOF_IN_FUTURE")
    valuation_date = parse_date(spec.get("valuation_date"))
    if valuation_date <= asof.date():
        raise ContractError("VALUATION_DATE_MUST_FOLLOW_ASOF")
    required_return = _number(spec.get("required_net_return"), "required_net_return", 0)

    receipts = spec.get("source_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise ContractError("SOURCE_DECLARATIONS_REQUIRED")
    source_times = {}
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise ContractError("INVALID_SOURCE_DECLARATION")
        identity = _text(receipt.get("id"), "source_id")
        if identity in source_times:
            raise ContractError("DUPLICATE_SOURCE_ID")
        uri = urlparse(_text(receipt.get("source_url"), "source_url"))
        if uri.scheme != "https" or not uri.netloc:
            raise ContractError("HTTPS_SOURCE_URL_REQUIRED")
        digest = receipt.get("sha256")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise ContractError("INVALID_DECLARED_SOURCE_SHA256")
        published, observed = _time(receipt.get("published_at")), _time(receipt.get("observed_at"))
        if published > observed or observed > asof:
            raise ContractError("SOURCE_NOT_OBSERVED_AT_ASOF")
        source_times[identity] = (published, observed)

    quote = spec.get("quote")
    if not isinstance(quote, dict):
        raise ContractError("QUOTE_REQUIRED")
    close = _number(quote.get("close_twd"), "close_twd", 0)
    if close == 0:
        raise ContractError("POSITIVE_QUOTE_REQUIRED")
    quote_time = _time(quote.get("available_at"))
    quote_source = quote.get("source_receipt_id")
    if not isinstance(quote_source, str) or quote_source not in source_times:
        raise ContractError("UNKNOWN_QUOTE_SOURCE")
    if not source_times[quote_source][0] <= quote_time <= asof:
        raise ContractError("QUOTE_NOT_AVAILABLE_AT_ASOF")

    costs = spec.get("costs")
    if not isinstance(costs, dict) or set(costs) != set(COST_FIELDS):
        raise ContractError("EXPLICIT_COST_RATES_REQUIRED")
    for name in COST_FIELDS:
        _number(costs[name], name, 0, 1)
    buy_factor = 1 + costs["buy_fee_rate"] + costs["buy_slippage_rate"]
    sell_factor = 1 - costs["sell_fee_rate"] - costs["sell_tax_rate"] - costs["sell_slippage_rate"]
    if sell_factor <= 0:
        raise ContractError("NONPOSITIVE_SALE_PROCEEDS")

    scenarios = spec.get("scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != set(SCENARIOS):
        raise ContractError("EXACTLY_BEAR_BASE_BULL_REQUIRED")
    rows = []
    for name in SCENARIOS:
        values = scenarios[name]
        if not isinstance(values, dict):
            raise ContractError("INVALID_SCENARIO")
        if any(k in values for k in ("probability", "weight", "confidence")):
            raise ContractError("SCENARIO_PROBABILITIES_NOT_SUPPORTED")
        for field in OPERATING_FIELDS:
            _number(values.get(field), field)
        for field in ("revenue_twd", "operating_expenses_twd", "net_dividends_per_share_twd"):
            _number(values[field], field, 0)
        _number(values["gross_margin"], "gross_margin", -1, 1)
        _number(values["effective_tax_rate"], "effective_tax_rate", 0, 1)
        if values["diluted_shares"] <= 0 or values["exit_pe"] <= 0:
            raise ContractError("POSITIVE_DILUTED_SHARES_AND_PE_REQUIRED")
        _text(values.get("assumption_note"), "assumption_note")
        references = values.get("source_receipt_ids")
        if (not isinstance(references, list) or not references
                or any(not isinstance(r, str) or r not in source_times for r in references)):
            raise ContractError("UNKNOWN_OR_MISSING_SCENARIO_SOURCE")

        gross_profit = values["revenue_twd"] * values["gross_margin"]
        operating_profit = (gross_profit - values["operating_expenses_twd"]
                            + values["other_operating_income_twd"])
        pretax = operating_profit + values["net_nonoperating_income_twd"]
        # Do not invent a realizable tax asset when operating assumptions lose money.
        tax = max(pretax, 0) * values["effective_tax_rate"]
        parent_profit = pretax - tax - values["noncontrolling_profit_twd"]
        eps = parent_profit / values["diluted_shares"]
        price = eps * values["exit_pe"] if eps > 0 else None
        dividends = values["net_dividends_per_share_twd"]
        proceeds = price * sell_factor + dividends if price is not None else None
        net_return = proceeds / (close * buy_factor) - 1 if proceeds is not None else None
        ceiling = proceeds / ((1 + required_return) * buy_factor) if proceeds is not None else None
        rows.append({
            "scenario": name, "assumptions": dict(values),
            "gross_profit_twd": gross_profit, "operating_profit_twd": operating_profit,
            "pretax_profit_twd": pretax, "tax_expense_twd": tax,
            "parent_profit_twd": parent_profit, "eps_twd": eps,
            "valuation_status": "POSITIVE_EPS_PE_SCENARIO" if price is not None else "LOSS_COMPANY_PE_NOT_APPLICABLE",
            "scenario_price_twd": price, "scenario_net_return_to_valuation_date": net_return,
            "max_entry_price_for_required_net_return_twd": ceiling,
        })

    try:
        raw = json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        # Extreme but finite inputs must not overflow into a published infinity.
        json.dumps(rows, allow_nan=False)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ContractError("NONFINITE_OR_UNSERIALIZABLE_BRIDGE") from exc
    prices = [r["scenario_price_twd"] for r in rows]
    labels_ordered = all(p is not None for p in prices) and prices == sorted(prices)
    return {
        "status": "SCENARIO_RESEARCH_ONLY_NOT_CALIBRATED",
        "code": code, "asof": asof.isoformat(), "valuation_date": valuation_date.isoformat(),
        "horizon_days": (valuation_date - asof.date()).days,
        "currency": "TWD", "shares_unit": "shares", "quote": dict(quote),
        "quote_age_days": (asof - quote_time).total_seconds() / 86400,
        "required_net_return": required_return, "costs": dict(costs),
        "input_sha256": sha256(raw).hexdigest(), "source_receipts": receipts,
        "source_authentication": "DECLARATIONS_ONLY_NOT_INDEPENDENTLY_VERIFIED",
        "scenarios": rows, "scenario_labels_price_ordered": labels_ordered,
        "warnings": [] if labels_ordered else ["SCENARIO_LABELS_DO_NOT_ESTABLISH_PRICE_ORDER_OR_LOSS_BOUND"],
        "calibrated_probabilities": None, "expected_net_return_12m": None,
        "portfolio_weights": None, "buy_signal": False, "investment_certified": False,
        "caveat": "Assumption arithmetic only; scenario prices are neither probabilities nor maximum-loss bounds. Source hashes are declarations, not authentication.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="Explicit assumption/source JSON; prints research output only")
    args = parser.parse_args()
    try:
        result = earnings_bridge(json.loads(args.spec.read_text(encoding="utf-8")))
    except (ContractError, ValueError, TypeError, OSError, OverflowError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "buy_signal": False}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
