"""Independent PIT-aware 12-month total-return research baseline.

This is a small, auditable baseline, NOT a certified alpha model or live signal.
No old V8 factors, gates, weights or ranking outputs are imported.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from math import isfinite, sqrt
from pathlib import Path

FEATURES = (
    "momentum_6m", "revenue_acceleration", "earnings_revision_3m",
    "operating_margin_change", "free_cashflow_yield", "volatility_60d",
)
REQUIRED_GATES = (
    "point_in_time_universe", "delisted_coverage", "corporate_actions",
    "verified_total_returns", "publication_timestamps", "execution_quotes",
    "source_hashes",
)


class ContractError(ValueError):
    """Fail closed when a training or evaluation input is not evidenced."""


def parse_date(value):
    if not isinstance(value, str):
        raise ContractError("DATE_MUST_BE_ISO_STRING")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError("INVALID_DATE") from exc
    if result.isoformat() != value:
        raise ContractError("DATE_MUST_BE_YYYY_MM_DD")
    return result


@dataclass(frozen=True)
class TradingCosts:
    """Example gross stock-return to net investor-return conversion.

    Parameters are configurable; not a claim about an actual broker tariff.
    """
    buy_fee: float = 0.001425
    sell_fee: float = 0.001425
    sell_tax: float = 0.003
    slippage_each_side: float = 0.001

    def __post_init__(self):
        vals = (self.buy_fee, self.sell_fee, self.sell_tax, self.slippage_each_side)
        if any(not isfinite(x) or x < 0 or x >= 0.5 for x in vals):
            raise ContractError("INVALID_TRADING_COST")
        if self.sell_fee + self.sell_tax + self.slippage_each_side >= 1:
            raise ContractError("INVALID_SELL_PROCEEDS")

    def net(self, total_return):
        if not isfinite(total_return) or total_return < -1:
            raise ContractError("INVALID_TOTAL_RETURN")
        buy = 1 + self.buy_fee + self.slippage_each_side
        sale = 1 - self.sell_fee - self.sell_tax - self.slippage_each_side
        return (1 + total_return) * sale / buy - 1


def _finite_number(x):
    return type(x) in (int, float) and isfinite(x)


def _valid_12m_label_maturity(signal_date, label_available_at):
    """A 12-month outcome cannot become known before its calendar anniversary.

    Feb 29 rolls to Feb 28 in a non-leap year. The separate PIT gate still
    requires the complete outcome and its publication time to be evidenced.
    """
    signal = parse_date(signal_date)
    available = parse_date(label_available_at)
    if signal.year == 9999:
        return False
    try:
        anniversary = signal.replace(year=signal.year + 1)
    except ValueError:
        anniversary = signal.replace(year=signal.year + 1, day=28)
    return available >= anniversary


def _assert_12m_label_maturities(rows):
    """Protect direct fit/walk-forward callers, not just manifest ingestion."""
    for row in rows:
        if row.get("total_return_12m") is not None and (
            row.get("label_available_at") is None
            or not _valid_12m_label_maturity(
                row["signal_date"], row["label_available_at"]
            )
        ):
            raise ContractError("INVALID_OR_LEAKING_RETURN_LABEL")


def load_bundle(folder):
    """Require cryptographic integrity plus explicit source audit evidence.

    Declarations are input checks only; they do not replace human/source audit.
    """
    folder = Path(folder)
    manifest_file = folder / "manifest.json"
    records_file = folder / "observations.jsonl"
    if not manifest_file.is_file() or not records_file.is_file():
        raise ContractError("DATASET_MANIFEST_OR_OBSERVATIONS_MISSING")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("schema") != "alphamax-research-v1":
        raise ContractError("UNSUPPORTED_DATASET_SCHEMA")
    missing = [key for key in REQUIRED_GATES if manifest.get("gates", {}).get(key) is not True]
    if missing:
        raise ContractError("UNCERTIFIED_DATA_GATES:" + ",".join(missing))
    raw = records_file.read_bytes()
    if sha256(raw).hexdigest() != manifest.get("observations_sha256"):
        raise ContractError("OBSERVATIONS_SHA256_MISMATCH")
    sources = manifest.get("source_receipts")
    if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or not s.strip() for s in sources):
        raise ContractError("SOURCE_RECEIPTS_REQUIRED")
    rows = []
    seen = set()
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"BAD_JSON_LINE:{line_number}") from exc
        if not isinstance(row, dict) or not isinstance(row.get("code"), str) or not row["code"]:
            raise ContractError(f"INVALID_SECURITY:{line_number}")
        signal_date = parse_date(row.get("signal_date"))
        key = (row["code"], signal_date)
        if key in seen:
            raise ContractError("DUPLICATE_SECURITY_SIGNAL_DATE")
        seen.add(key)
        feats = row.get("features")
        stamps = row.get("feature_available_at")
        if not isinstance(feats, dict) or not isinstance(stamps, dict):
            raise ContractError("FEATURES_AND_TIMESTAMPS_REQUIRED")
        if set(feats) != set(FEATURES) or set(stamps) != set(FEATURES):
            raise ContractError("FEATURE_SCHEMA_MISMATCH")
        if any(not _finite_number(feats[f]) or parse_date(stamps[f]) > signal_date for f in FEATURES):
            raise ContractError("FUTURE_OR_INVALID_FEATURE")
        if row.get("execution_possible") is not True:
            # Don't silently drop hard-to-trade stocks from the validation universe.
            # Preserve rows, but flag them as infeasible for a real transaction.
            if row.get("execution_possible") is not False:
                raise ContractError("EXECUTION_POSSIBLE_MUST_BE_BOOL")
        y = row.get("total_return_12m")
        maturity = row.get("label_available_at")
        if y is None:
            if maturity is not None:
                raise ContractError("UNMATCHED_LABEL_MATURITY")
        elif not _finite_number(y) or y < -1 or maturity is None or not _valid_12m_label_maturity(row["signal_date"], maturity):
            raise ContractError("INVALID_OR_LEAKING_RETURN_LABEL")
        rows.append(row)
    if not rows:
        raise ContractError("EMPTY_OBSERVATIONS")
    return manifest, rows


def _solve(matrix, vector):
    """Small ridge-regularized linear system; partial-pivot Gaussian elimination."""
    n = len(vector)
    a = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for j in range(n):
        pivot = max(range(j, n), key=lambda k: abs(a[k][j]))
        if abs(a[pivot][j]) < 1e-12:
            raise ContractError("SINGULAR_RIDGE_SYSTEM")
        a[j], a[pivot] = a[pivot], a[j]
        scale = a[j][j]
        for k in range(j, n + 1):
            a[j][k] /= scale
        for i in range(n):
            if i == j:
                continue
            factor = a[i][j]
            for k in range(j, n + 1):
                a[i][k] -= factor * a[j][k]
    return [a[i][-1] for i in range(n)]


def fit_asof(rows, signal_date, costs=None, min_history=80, ridge=1.0):
    """Train ONLY on labels observable before a historical prediction date."""
    asof = parse_date(signal_date)
    _assert_12m_label_maturities(rows)
    costs = costs or TradingCosts()
    if ridge <= 0 or not isfinite(ridge):
        raise ContractError("INVALID_RIDGE")
    historical = [
        r for r in rows
        if parse_date(r["signal_date"]) < asof
        and r.get("total_return_12m") is not None
        and parse_date(r["label_available_at"]) < asof
        and r["execution_possible"] is True
    ]
    if (len(historical) < min_history
        or len({r["signal_date"] for r in historical}) < 8
        or len({r["code"] for r in historical}) < 8):
        raise ContractError("INSUFFICIENT_MATURED_PIT_TRAINING_HISTORY")
    x = [[float(r["features"][f]) for f in FEATURES] for r in historical]
    y = [costs.net(r["total_return_12m"]) for r in historical]
    n, k = len(x), len(FEATURES)
    means = [sum(row[j] for row in x) / n for j in range(k)]
    stds = [max(sqrt(sum((row[j]-means[j])**2 for row in x) / n), 1e-8) for j in range(k)]
    standardized = [[(row[j]-means[j])/stds[j] for j in range(k)] for row in x]
    avg_y = sum(y)/n
    target = [sum(row[j]*(t-avg_y) for row,t in zip(standardized,y))/n for j in range(k)]
    gram = [[sum(row[j]*row[l] for row in standardized)/n + (ridge if j == l else 0)
             for l in range(k)] for j in range(k)]
    coefficients = _solve(gram, target)
    return {"means": means, "stds": stds, "coefficients": coefficients,
            "intercept": avg_y, "training_rows": n, "asof": signal_date,
            "model": "standardized-ridge-research-baseline", "ridge": ridge}


def _predict(model, row):
    return model["intercept"] + sum(
        model["coefficients"][j] * (row["features"][name]-model["means"][j])/model["stds"][j]
        for j, name in enumerate(FEATURES)
    )


def rank_asof(rows, signal_date, costs=None, min_history=80):
    model = fit_asof(rows, signal_date, costs, min_history)
    eligible = [r for r in rows if r["signal_date"] == signal_date and r["execution_possible"] is True]
    ranked = [{"code": r["code"], "signal_date": signal_date,
               "predicted_net_return_12m": round(_predict(model, r), 6)}
              for r in eligible]
    ranked.sort(key=lambda r: (-r["predicted_net_return_12m"], r["code"]))
    return {"status": "UNCALIBRATED_RESEARCH_ONLY", "model": model,
            "candidates": ranked, "not_available": [
                "double_probability", "tail_risk", "certified_expected_return",
                "live_buy_signal", "validated_portfolio_weights"
            ]}


def walk_forward(rows, evaluation_asof, costs=None, top_n=10, min_history=80):
    """Evaluate only *matured full cohorts* with models fit from past labels.

    No annualized Sharpe/CAGR claimed: overlapping 12-month cohorts aren't
    independent. For production, implement a costed holdings/equity simulator.
    """
    cutoff = parse_date(evaluation_asof)
    _assert_12m_label_maturities(rows)
    if top_n < 1:
        raise ContractError("TOP_N_MUST_BE_POSITIVE")
    costs = costs or TradingCosts()
    cohorts = []
    for signal in sorted({r["signal_date"] for r in rows}):
        day = parse_date(signal)
        if day >= cutoff:
            continue
        all_candidates = [r for r in rows if r["signal_date"] == signal]
        if not all_candidates or any(
            r.get("total_return_12m") is None or parse_date(r["label_available_at"]) > cutoff
            for r in all_candidates
        ):
            continue
        feasible = [r for r in all_candidates if r["execution_possible"] is True]
        if len(feasible) < top_n:
            continue
        try:
            model = fit_asof(rows, signal, costs, min_history)
        except ContractError as exc:
            if str(exc) == "INSUFFICIENT_MATURED_PIT_TRAINING_HISTORY":
                continue
            raise
        selected = sorted(feasible, key=lambda r: (-_predict(model, r), r["code"]))[:top_n]
        mean = lambda xs: sum(costs.net(r["total_return_12m"]) for r in xs) / len(xs)
        cohorts.append({
            "signal_date": signal,
            "selected_codes": [r["code"] for r in selected],
            "selected_mean_net_return": round(mean(selected), 6),
            "eligible_universe_mean_net_return": round(mean(feasible), 6),
            "training_rows": model["training_rows"],
            "infeasible_count": len(all_candidates)-len(feasible),
        })
    if not cohorts:
        return {"status": "BLOCKED_NO_MATURED_OOS_COHORTS", "cohorts": []}
    return {
        "status": "RESEARCH_BASELINE_NOT_CERTIFIED",
        "cohort_count": len(cohorts),
        "selected_mean_of_cohort_means": round(sum(c["selected_mean_net_return"] for c in cohorts)/len(cohorts), 6),
        "universe_mean_of_cohort_means": round(sum(c["eligible_universe_mean_net_return"] for c in cohorts)/len(cohorts), 6),
        "cohorts": cohorts,
        "warning": "Overlapping cohorts; no portfolio equity curve, CAGR, Sharpe or statistical significance computed.",
    }
