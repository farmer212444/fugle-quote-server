"""AlphaHunter V1: independent, research-only, explainable opportunity ranking.

The scores are uncalibrated hypotheses, NOT expected investable returns or A+.
No historical V8/AlphaMax score or thresholds are imported.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
import json
import math

SCHEMA = "alphahunter-research-v1"
GATES = (
    "pit_security_master", "pit_financial_vintages", "corporate_actions",
    "historical_delistings", "execution_prices", "original_source_receipts",
)
FEATURES = (
    "revenue_yoy", "gross_margin_change_pp", "cash_conversion",
    "net_debt_to_ebitda",
)
SCENARIOS = ("bear", "base", "bull")
PROBABILITIES = {"bear": 0.25, "base": 0.50, "bull": 0.25}
ROUND_TRIP_COST = 0.006  # Illustrative Taiwan stock transaction-cost budget.
STATUS = "UNCALIBRATED_RESEARCH_ONLY"


class EvidenceError(ValueError):
    """Reject an unsupported, stale or future-contaminated dataset."""


def _day(value, field):
    if not isinstance(value, str):
        raise EvidenceError("INVALID_DATE:" + field)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceError("INVALID_DATE:" + field) from exc
    if parsed.isoformat() != value:
        raise EvidenceError("NON_CANONICAL_DATE:" + field)
    return parsed


def _num(value, field):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise EvidenceError("INVALID_NUMBER:" + field)
    if not math.isfinite(float(value)):
        raise EvidenceError("NONFINITE_NUMBER:" + field)
    return float(value)


def _matures(signal):
    """Twelve calendar months, with Feb 29 -> Feb 28."""
    try:
        return signal.replace(year=signal.year + 1)
    except ValueError:
        return signal.replace(year=signal.year + 1, day=28)


def validate_rows(rows):
    """Check recorded availability; checks do not independently audit sources."""
    if not isinstance(rows, list) or not rows:
        raise EvidenceError("EMPTY_OBSERVATIONS")
    seen = set()
    validated = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise EvidenceError("INVALID_ROW")
        code = row.get("code")
        if not isinstance(code, str) or not code or len(code) > 12:
            raise EvidenceError("INVALID_SECURITY_ID")
        signal = _day(row.get("signal_date"), "signal_date")
        if signal > date.today():
            raise EvidenceError("FUTURE_SIGNAL")
        key = (code, signal)
        if key in seen:
            raise EvidenceError("DUPLICATE_SECURITY_DATE")
        seen.add(key)

        if _day(row.get("reference_price_available_at"), "reference_price_available_at") > signal:
            raise EvidenceError("FUTURE_REFERENCE_PRICE")
        if _day(row.get("forecast_available_at"), "forecast_available_at") > signal:
            raise EvidenceError("FUTURE_FORECAST")
        price = _num(row.get("reference_price"), "reference_price")
        if price <= 0:
            raise EvidenceError("INVALID_REFERENCE_PRICE")
        if not isinstance(row.get("execution_possible"), bool):
            raise EvidenceError("EXECUTION_FLAG_REQUIRED")

        features = row.get("features")
        available = row.get("feature_available_at")
        if not isinstance(features, dict) or not isinstance(available, dict):
            raise EvidenceError("FEATURE_RECEIPTS_MISSING")
        if set(features) != set(FEATURES) or set(available) != set(FEATURES):
            raise EvidenceError("FEATURE_SCHEMA_MISMATCH")
        for feature in FEATURES:
            _num(features[feature], feature)
            if _day(available[feature], feature) > signal:
                raise EvidenceError("FUTURE_FEATURE:" + feature)

        scenarios = row.get("scenarios")
        if not isinstance(scenarios, dict) or set(scenarios) != set(SCENARIOS):
            raise EvidenceError("SCENARIO_SCHEMA_MISMATCH")
        targets = []
        for name in SCENARIOS:
            v = scenarios[name]
            if not isinstance(v, dict) or set(v) != {"eps", "pe", "dividend"}:
                raise EvidenceError("SCENARIO_ASSUMPTIONS_MISSING")
            eps = _num(v["eps"], name + ".eps")
            pe = _num(v["pe"], name + ".pe")
            div = _num(v["dividend"], name + ".dividend")
            if eps < 0 or pe <= 0 or div < 0:
                raise EvidenceError("SCENARIO_OUT_OF_DOMAIN")
            targets.append(eps * pe + div)
        if targets != sorted(targets):
            raise EvidenceError("SCENARIOS_NOT_ORDERED")

        realized = row.get("realized_total_return_12m")
        label_date = row.get("label_available_at")
        if (realized is None) != (label_date is None):
            raise EvidenceError("LABEL_DATE_PAIR_REQUIRED")
        if realized is not None:
            _num(realized, "realized_total_return_12m")
            if _day(label_date, "label_available_at") < _matures(signal):
                raise EvidenceError("PREMATURE_12M_RETURN")
        validated.append(row)
    return validated


def load_bundle(folder):
    """SHA and provenance gates are necessary, but do not certify real PIT truth."""
    folder = Path(folder)
    manifest_file = folder / "manifest.json"
    records_file = folder / "observations.jsonl"
    if not manifest_file.is_file() or not records_file.is_file():
        raise EvidenceError("INDEPENDENT_VERIFIED_BUNDLE_MISSING")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        raw = records_file.read_bytes()
    except (OSError, ValueError) as exc:
        raise EvidenceError("BUNDLE_UNREADABLE") from exc
    if manifest.get("schema") != SCHEMA:
        raise EvidenceError("WRONG_SCHEMA")
    if manifest.get("observations_sha256") != sha256(raw).hexdigest():
        raise EvidenceError("OBSERVATIONS_SHA256_MISMATCH")
    gates = manifest.get("gates")
    if not isinstance(gates, dict) or any(gates.get(k) is not True for k in GATES):
        raise EvidenceError("UNVERIFIED_EVIDENCE_GATES")
    receipts = manifest.get("source_receipts")
    if not isinstance(receipts, list) or not receipts or not all(isinstance(r, str) and r for r in receipts):
        raise EvidenceError("SOURCE_RECEIPTS_MISSING")
    try:
        records = [json.loads(x) for x in raw.splitlines() if x.strip()]
    except (ValueError, UnicodeDecodeError) as exc:
        raise EvidenceError("OBSERVATIONS_INVALID_JSONL") from exc
    return manifest, validate_rows(records)


def score(row):
    """Only as-of scenario assumptions and as-of operating features enter score."""
    price = float(row["reference_price"])
    returns = {
        s: (row["scenarios"][s]["eps"] * row["scenarios"][s]["pe"]
            + row["scenarios"][s]["dividend"]) / price - 1.0 - ROUND_TRIP_COST
        for s in SCENARIOS
    }
    expected = sum(PROBABILITIES[s] * returns[s] for s in SCENARIOS)
    downside = max(0.0, -returns["bear"])
    f = row["features"]
    cash_penalty = 0.08 * max(0.0, 0.75 - f["cash_conversion"])
    debt_penalty = 0.025 * max(0.0, f["net_debt_to_ebitda"] - 2.0)
    risk_score = expected - 0.35 * downside - cash_penalty - debt_penalty
    inflection = f["revenue_yoy"] >= 0.10 and f["gross_margin_change_pp"] >= 0.50
    return {
        "code": row["code"],
        "signal_date": row["signal_date"],
        "scenario_returns": {s: round(returns[s], 6) for s in SCENARIOS},
        "scenario_weighted_return_UNCALIBRATED": round(expected, 6),
        "risk_adjusted_research_score": round(risk_score, 6),
        "inflection_evidence": bool(inflection),
        "cash_conversion": f["cash_conversion"],
        "status": STATUS,
    }


def rank_asof(rows, asof, top_n=10):
    asof_date = _day(asof, "asof")
    if asof_date > date.today():
        raise EvidenceError("ASOF_IN_FUTURE")
    if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
        raise EvidenceError("INVALID_TOP_N")
    checked = validate_rows(list(rows))
    eligible = [row for row in checked
                if row["signal_date"] == asof and row["execution_possible"]]
    if not eligible:
        raise EvidenceError("NO_ELIGIBLE_SIGNAL_DATE")
    candidates = sorted((score(r) for r in eligible),
                        key=lambda x: (-x["risk_adjusted_research_score"], x["code"]))
    return {
        "status": STATUS, "signal_date": asof,
        "candidate_count": len(candidates), "candidates": candidates[:top_n],
        "not_a_buy_signal": True,
        "assumption_probability_calibrated": False,
        "external_source_audit_completed": False,
    }


def matured_cohort_diagnostics(rows, evaluation_date, top_n=10):
    """Non-investable, overlapping 12m cohort diagnostic; never portfolio CAGR."""
    end = _day(evaluation_date, "evaluation_date")
    if end > date.today():
        raise EvidenceError("EVALUATION_IN_FUTURE")
    checked = validate_rows(list(rows))
    cohorts = []
    for signal in sorted(set(r["signal_date"] for r in checked)):
        selected = [r for r in checked if r["signal_date"] == signal and r["execution_possible"]]
        if not selected:
            continue
        selected = sorted(selected, key=lambda r: (-score(r)["risk_adjusted_research_score"], r["code"]))[:top_n]
        if not all(r["realized_total_return_12m"] is not None
                   and _day(r["label_available_at"], "label_available_at") <= end
                   for r in selected):
            continue
        realized = sum(r["realized_total_return_12m"] for r in selected) / len(selected)
        cohorts.append({"signal_date": signal, "selected_count": len(selected),
                        "mean_realized_total_return_12m": round(realized, 6)})
    return {
        "status": "DIAGNOSTIC_ONLY_NOT_INVESTABLE" if cohorts else "BLOCKED_NO_MATURED_COHORTS",
        "cohort_count": len(cohorts), "cohorts": cohorts,
        "portfolio_cagr_certified": False, "independent_outperformance_certified": False,
    }
