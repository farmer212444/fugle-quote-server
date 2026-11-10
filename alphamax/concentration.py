"""AlphaMax Concentration V1: auditable, fail-closed paper allocation.

This module is independent of legacy V8 gates. It consumes externally
calibrated forecasts; it does not manufacture forecasts, confidence, or alpha.
All outputs are research-only, never broker orders or certified buy signals.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite

from alphamax.core import ContractError, parse_date


EVIDENCE_GATES = (
    "point_in_time_audited",
    "historical_universe_and_delistings_audited",
    "corporate_actions_and_total_returns_audited",
    "out_of_sample_validated",
    "probabilities_calibrated",
    "execution_costs_and_fillability_audited",
    "independent_review_documented",
)
REQUIRED_CANDIDATE_FIELDS = (
    "code", "sector", "asof", "horizon_months",
    "expected_net_return_12m", "lower_bound_net_return_12m",
    "probability_loss_30pct", "confidence", "daily_turnover_ntd",
    "executable",
)


def _number(v):
    return type(v) in (int, float) and isfinite(v)


def forecast_digest(candidates, scenarios):
    """SHA-256 of a canonical UTF-8 snapshot, including all joint scenarios."""
    raw = json.dumps(
        {"candidates": candidates, "scenarios": scenarios},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class ConcentrationPolicy:
    """Illustrative safety limits, not optimized or investment-advised values."""

    max_single_weight: float = 0.20
    max_sector_weight: float = 0.30
    max_joint_stress_loss: float = 0.12
    min_excess_lower_return: float = 0.05
    min_confidence: float = 0.80
    max_probability_loss_30pct: float = 0.35
    min_daily_turnover_ntd: float = 20_000_000.0
    downside_probability_penalty: float = 0.15
    weight_step: float = 0.01

    def __post_init__(self):
        bounded = (
            self.max_single_weight, self.max_sector_weight,
            self.max_joint_stress_loss, self.min_confidence,
            self.max_probability_loss_30pct, self.weight_step,
        )
        if any(not _number(x) or x <= 0 or x > 1 for x in bounded):
            raise ContractError("INVALID_CONCENTRATION_POLICY_BOUNDS")
        if self.max_single_weight > self.max_sector_weight:
            raise ContractError("SINGLE_WEIGHT_EXCEEDS_SECTOR_WEIGHT")
        if any(not _number(x) or x < 0 for x in (
            self.min_excess_lower_return, self.min_daily_turnover_ntd,
            self.downside_probability_penalty,
        )):
            raise ContractError("INVALID_CONCENTRATION_POLICY_VALUE")
        if round(1 / self.weight_step) * self.weight_step != 1:
            # One-percent default does not have a binary-exact representation.
            if abs(round(1 / self.weight_step) * self.weight_step - 1) > 1e-9:
                raise ContractError("WEIGHT_STEP_MUST_DIVIDE_ONE")


def _validate_inputs(candidates, scenarios, evidence, cash_return, policy):
    if not isinstance(candidates, list) or not candidates:
        raise ContractError("EMPTY_CONCENTRATION_CANDIDATES")
    if not _number(cash_return) or cash_return < -1 or cash_return > 1:
        raise ContractError("INVALID_CASH_RETURN")
    if len(candidates) > 3000:
        raise ContractError("TOO_MANY_CONCENTRATION_CANDIDATES")
    if not isinstance(evidence, dict):
        raise ContractError("CONCENTRATION_EVIDENCE_MISSING")
    absent = [key for key in EVIDENCE_GATES if evidence.get(key) is not True]
    if absent:
        raise ContractError("CONCENTRATION_EVIDENCE_GATES_MISSING:" + ",".join(absent))
    receipts = evidence.get("receipt_ids")
    if (not isinstance(receipts, list) or not receipts
        or any(not isinstance(x, str) or not x.strip() for x in receipts)):
        raise ContractError("CONCENTRATION_RECEIPTS_MISSING")
    if not isinstance(scenarios, dict) or len(scenarios) < 2:
        raise ContractError("AT_LEAST_TWO_JOINT_STRESS_SCENARIOS_REQUIRED")

    seen = set()
    asofs = set()
    for row in candidates:
        if not isinstance(row, dict) or any(k not in row for k in REQUIRED_CANDIDATE_FIELDS):
            raise ContractError("CONCENTRATION_CANDIDATE_SCHEMA_MISSING")
        code, sector = row["code"], row["sector"]
        if (not isinstance(code, str) or not code.strip()
            or not isinstance(sector, str) or not sector.strip()):
            raise ContractError("INVALID_CODE_OR_SECTOR")
        if code in seen:
            raise ContractError("DUPLICATE_CONCENTRATION_CODE")
        seen.add(code)
        asofs.add(parse_date(row["asof"]).isoformat())
        if type(row["horizon_months"]) is not int or row["horizon_months"] != 12:
            raise ContractError("CONCENTRATION_HORIZON_NOT_12M")
        if type(row["executable"]) is not bool:
            raise ContractError("EXECUTABLE_MUST_BE_BOOLEAN")
        for key in ("expected_net_return_12m", "lower_bound_net_return_12m",
                    "probability_loss_30pct", "confidence", "daily_turnover_ntd"):
            if not _number(row[key]):
                raise ContractError("NONFINITE_CONCENTRATION_FORECAST:" + key)
        if (row["expected_net_return_12m"] < -1
            or row["lower_bound_net_return_12m"] < -1
            or row["lower_bound_net_return_12m"] > row["expected_net_return_12m"]
            or not 0 <= row["probability_loss_30pct"] <= 1
            or not 0 <= row["confidence"] <= 1
            or row["daily_turnover_ntd"] < 0):
            raise ContractError("INVALID_CONCENTRATION_DISTRIBUTION")
    if len(asofs) != 1 or evidence.get("asof") not in asofs:
        raise ContractError("CONCENTRATION_ASOF_MISMATCH")
    codes = set(seen)
    for scenario, losses in scenarios.items():
        if (not isinstance(scenario, str) or not scenario.strip()
            or not isinstance(losses, dict) or set(losses) != codes):
            raise ContractError("JOINT_SCENARIO_MISSING_SECURITIES")
        if any(not _number(x) or x < 0 or x > 1 for x in losses.values()):
            raise ContractError("INVALID_JOINT_SCENARIO_LOSS")
    if evidence.get("forecast_sha256") != forecast_digest(candidates, scenarios):
        raise ContractError("CONCENTRATION_FORECAST_HASH_MISMATCH")
    return sorted(candidates, key=lambda x: x["code"])


def allocate_concentration(candidates, scenarios, evidence, *,
                           cash_net_return_12m=0.0, policy=None):
    """Compute *paper-only* risk-budgeted weights from a pre-audited forecast.

    Inputs:
      candidates: 12m forecasts from an external, calibrated model. All returns
        must already include fees/taxes/slippage.
      scenarios: two or more *joint* name->loss-fraction shock scenarios.
      evidence: timestamp, source receipts, snapshot SHA and seven review gates.
    The Boolean gates are contract assertions, NOT independent authentication.

    Objective is a transparent greedy robust-return heuristic subject to
    per-name, per-sector and simultaneous-shock budgets. It is NOT a proven
    globally optimal portfolio, and CASH may be 100%.
    """
    policy = policy or ConcentrationPolicy()
    if not isinstance(policy, ConcentrationPolicy):
        raise ContractError("INVALID_POLICY_TYPE")
    try:
        rows = _validate_inputs(candidates, scenarios, evidence, cash_net_return_12m, policy)
    except (ContractError, ValueError, TypeError, OverflowError) as exc:
        return {"status": "BLOCKED", "reason": str(exc), "weights": [],
                "cash_weight": 1.0, "buy_signal": False}

    eligible, rejected = [], []
    for row in rows:
        errors = []
        if row["executable"] is False:
            errors.append("NOT_EXECUTABLE")
        if row["daily_turnover_ntd"] < policy.min_daily_turnover_ntd:
            errors.append("LOW_LIQUIDITY")
        if row["confidence"] < policy.min_confidence:
            errors.append("INSUFFICIENT_CONFIDENCE")
        if row["probability_loss_30pct"] > policy.max_probability_loss_30pct:
            errors.append("EXCESS_TAIL_PROBABILITY")
        if row["lower_bound_net_return_12m"] - cash_net_return_12m < policy.min_excess_lower_return:
            errors.append("INSUFFICIENT_ROBUST_EXPECTED_EXCESS_RETURN")
        if max(s[row["code"]] for s in scenarios.values()) <= 0:
            errors.append("NO_EVIDENCED_JOINT_STRESS_LOSS")
        margin = (row["lower_bound_net_return_12m"] - cash_net_return_12m
                  - policy.downside_probability_penalty * row["probability_loss_30pct"])
        if margin <= 0:
            errors.append("NEGATIVE_CONSERVATIVE_UTILITY")
        if errors:
            rejected.append({"code": row["code"], "reasons": errors})
        else:
            eligible.append((row, margin))

    # Greedy maximization of robust marginal gain; all risk budgets are explicit.
    weights = {row["code"]: 0.0 for row, _ in eligible}
    sectors = {row["sector"]: 0.0 for row, _ in eligible}
    stress_used = {name: 0.0 for name in scenarios}
    total = 0.0
    steps = round(1.0 / policy.weight_step)
    eps = 1e-10
    for _ in range(steps):
        feasible = []
        for row, margin in eligible:
            code, sector = row["code"], row["sector"]
            if weights[code] + policy.weight_step > policy.max_single_weight + eps:
                continue
            if sectors[sector] + policy.weight_step > policy.max_sector_weight + eps:
                continue
            if any(
                stress_used[name] + policy.weight_step * losses[code]
                > policy.max_joint_stress_loss + eps
                for name, losses in scenarios.items()
            ):
                continue
            feasible.append((margin, code, sector))
        if not feasible:
            break
        # Deterministic tie-break; no forced allocation to negative-return names.
        _, chosen, sector = max(feasible, key=lambda v: (v[0], -ord(v[1][0]) if v[1] else 0, v[1]))
        weights[chosen] += policy.weight_step
        sectors[sector] += policy.weight_step
        total += policy.weight_step
        for name, losses in scenarios.items():
            stress_used[name] += policy.weight_step * losses[chosen]

    output = []
    for row, margin in eligible:
        w = weights[row["code"]]
        if w > eps:
            output.append({
                "code": row["code"], "sector": row["sector"],
                "weight": round(w, 8),
                "expected_net_return_12m": row["expected_net_return_12m"],
                "conservative_marginal_utility": round(margin, 8),
            })
    output.sort(key=lambda r: (-r["weight"], r["code"]))
    cash = max(0.0, 1 - sum(x["weight"] for x in output))
    scenario_loss = {
        name: round(sum(x["weight"] * losses[x["code"]] for x in output), 8)
        for name, losses in scenarios.items()
    }
    expected = cash * cash_net_return_12m + sum(
        w * row["expected_net_return_12m"] for row, _ in eligible
        for w in [weights[row["code"]]]
    )
    return {
        "status": "RESEARCH_ALLOCATION_ONLY_NOT_LIVE",
        "asof": evidence["asof"],
        "buy_signal": False,
        "method": "deterministic_greedy_conservative_expected_return_with_joint_stress_budgets",
        "weights": output,
        "cash_weight": round(cash, 8),
        "scenario_portfolio_loss": scenario_loss,
        "scenario_worst_loss": max(scenario_loss.values()),
        "illustrative_expected_net_return_12m": round(expected, 8),
        "rejected": rejected,
        "eligible_count": len(eligible),
        "caveat": "Contract booleans and hash are not external proof; allocations require independent audit and cannot generate orders.",
    }
