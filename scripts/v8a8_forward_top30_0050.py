#!/usr/bin/env python3
"""Predeclared forward-only TOP30/0050 shadow competition, NOT a return backtest.

This stage locks a monthly research selection only after the immutable archive
was actually created. It deliberately does not compute returns from unverified
closes, ETF prices, corporate actions, or non-executable paper fills.
No actual trades or secondary schedule are created here.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path

from scripts.v897_freeze_model_vintage import aware, verify_frozen_receipt

TAIPEI = dt.timezone(dt.timedelta(hours=8))
SCHEMA = "V8A8_FORWARD_TOP30_V1_NOT_YET_RETURN_VALIDATED"
CONFIG = "config/forward_top30_0050_v1.json"
OUT = "experiments/forward_top30_0050_v1"


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def validate_policy(policy):
    if policy.get("schema") != "V8A8_PREDECLARED_RESEARCH_SHADOW_COMPETITION_V1":
        raise ValueError("UNKNOWN_PREDECLARED_POLICY")
    if policy.get("selected_count") != 30 or policy.get("weighting") != "equal_weight":
        raise ValueError("SELECTION_POLICY_CHANGED")
    if policy.get("selection_source") != "top30_quality_priority":
        raise ValueError("SELECTION_POLICY_CHANGED")
    if policy.get("formation") != "first_verified_archive_per_local_calendar_month":
        raise ValueError("SELECTION_POLICY_CHANGED")
    if policy.get("benchmark") != ["0050_total_return", "TAIEX_total_return"]:
        raise ValueError("BENCHMARK_POLICY_CHANGED")
    if policy.get("monthly_rebalance_only") is not True:
        raise ValueError("REBALANCE_POLICY_CHANGED")
    activate = aware(policy["activation_at"]).astimezone(dt.timezone.utc)
    if activate.date() < dt.date(2026, 10, 22):
        raise ValueError("RETROSPECTIVE_POLICY_ACTIVATION")
    return activate


def earliest_eligible_receipt(root, policy, now):
    """Choose first archive actually captured in the *current* Taipei month.

    Earlier months cannot be retroactively filled by this function.
    """
    activate = validate_policy(policy)
    month = now.astimezone(TAIPEI).strftime("%Y-%m")
    if now < activate:
        return None
    matches = []
    for path in sorted((root / "pit_vintages").glob("20??-??-??/*/receipt.json")):
        receipt = verify_frozen_receipt(path)
        if receipt.get("strategy_variant", "current-information") != "current-information":
            continue
        vintage = aware(receipt["estimate_vintage"]).astimezone(dt.timezone.utc)
        archived = aware(receipt["archived_at_utc"]).astimezone(dt.timezone.utc)
        observed = max(vintage, archived)
        if observed < activate or observed > now:
            continue
        if observed.astimezone(TAIPEI).strftime("%Y-%m") != month:
            continue
        matches.append((observed, path, receipt))
    if not matches:
        return None
    matches.sort(key=lambda p: (p[0], str(p[1])))
    return matches[0]


def lock_selection(root, policy, eligible, now):
    signal_time, receipt_path, receipt = eligible
    research = read(receipt_path.parent / "latest_research.json")
    if research["estimate_vintage"] != receipt["estimate_vintage"]:
        raise ValueError("RESEARCH_VINTAGE_DIFFERENT_FROM_RECEIPT")
    rows = research.get("top30_quality_priority")
    if not isinstance(rows, list) or len(rows) != 30:
        raise ValueError("TOP30_PRIMARY_LIST_NOT_COMPLETE")
    picks = []
    seen = set()
    for order, row in enumerate(rows, 1):
        code, market = row.get("code"), row.get("market")
        if not code or market not in ("TWSE", "TPEX"):
            raise ValueError("UNIDENTIFIABLE_TOP30_SECURITY")
        if (market, code) in seen:
            raise ValueError("DUPLICATE_TOP30_SECURITY")
        seen.add((market, code))
        if row.get("source_tier") != "ORIGINAL_CURRENT_ISSUER_NUMERICS":
            raise ValueError("TOP30_NOT_PRIMARY_ORIGINAL_NUMERIC_COHORT")
        picks.append({
            "rank": order, "market": market, "code": code, "name": row.get("name"),
            "frozen_reference_price_date": research["asof_price_date"],
            "frozen_reference_close": row.get("reference_close"),
            "frozen_2027_base_eps": (row.get("base") or {}).get("eps"),
            "frozen_2027_base_target": (row.get("base") or {}).get("target_price"),
            "frozen_2027_base_upside_pct": (row.get("base") or {}).get("price_upside_pct"),
            "weight": 1 / 30,
            "research_only_not_formal_Aplus": True,
        })
    if research.get("asof_price_date") > now.astimezone(TAIPEI).date().isoformat():
        raise ValueError("FUTURE_REFERENCE_PRICE")
    core = {
        "schema": SCHEMA,
        "month": now.astimezone(TAIPEI).strftime("%Y-%m"),
        "policy_sha256": digest(policy),
        "model": research["model"],
        "model_code_sha256": receipt["model_code_sha256"],
        "strategy_variant_sha256": receipt.get("strategy_variant_sha256"),
        "frozen_source_receipt": receipt_path.relative_to(root).as_posix(),
        "frozen_source_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "archive_eligible_signal_at": signal_time.isoformat(),
        "selection_committed_at_utc": now.isoformat(),
        "next_eligible_open_only_after": now.isoformat(),
        "portfolio_reference_capital_ntd": policy["capital_ntd"],
        "entry_fills_verified": False,
        "research_top30": picks,
        "formal_Aplus_count_at_selection": research.get("formal_Aplus_count"),
        "formal_Aplus_shadow": "CASH_UNTIL_ALL_GATES_PASS",
        "performance_is_not_yet_verified": True,
    }
    return {**core, "selection_sha256": digest(core)}


def verify_locked(existing, policy):
    selected = {k: v for k, v in existing.items() if k != "selection_sha256"}
    if digest(selected) != existing.get("selection_sha256"):
        raise ValueError("LOCKED_MONTHLY_SELECTION_TAMPERED")
    if existing.get("policy_sha256") != digest(policy):
        raise ValueError("EXPERIMENT_POLICY_MUTATED_AFTER_LOCK")
    if len(existing.get("research_top30", [])) != 30:
        raise ValueError("LOCKED_TOP30_CORRUPT")
    return existing


def run(root, now=None):
    root = Path(root).resolve()
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("NOW_MUST_INCLUDE_TIMEZONE")
    now = now.astimezone(dt.timezone.utc)
    policy = read(root / CONFIG)
    activation = validate_policy(policy)
    month = now.astimezone(TAIPEI).strftime("%Y-%m")
    out = root / OUT
    frozen_path = out / "monthly" / (month + ".json")
    selection = None
    status = "WAITING_FOR_POLICY_ACTIVATION" if now < activation else "WAITING_FOR_FIRST_NEW_VERIFIED_ARCHIVE"
    if frozen_path.exists():
        selection = verify_locked(read(frozen_path), policy)
        status = "MONTHLY_TOP30_FROZEN_AWAITING_VERIFIED_FILLS_AND_BENCHMARK"
    elif now >= activation:
        eligible = earliest_eligible_receipt(root, policy, now)
        if eligible:
            selection = lock_selection(root, policy, eligible, now)
            if frozen_path.exists():
                verify_locked(read(frozen_path), policy)
                raise ValueError("CONCURRENT_MONTHLY_SELECTION_WRITE")
            write_atomic(frozen_path, selection)
            status = "MONTHLY_TOP30_FROZEN_AWAITING_VERIFIED_FILLS_AND_BENCHMARK"
    report = {
        "schema": SCHEMA, "status": status, "policy_sha256": digest(policy),
        "activation_at": policy["activation_at"], "local_month": month,
        "reference_capital_ntd": policy["capital_ntd"],
        "selection_path": frozen_path.relative_to(root).as_posix() if selection else None,
        "selection_sha256": selection["selection_sha256"] if selection else None,
        "research_top30_count": len(selection["research_top30"]) if selection else 0,
        "formal_Aplus_strategy_currently_in_cash": selection is None or selection["formal_Aplus_count_at_selection"] == 0,
        "verified_trading_results": 0,
        "model_net_total_return_pct": None,
        "benchmark_0050_net_total_return_pct": None,
        "benchmark_TAIEX_total_return_pct": None,
        "model_alpha_vs_0050_pct_points": None,
        "hit_rate": None, "maximum_drawdown_pct": None,
        "is_winner_vs_0050": None,
        "missing": [
            "Independent next-eligible-session open/fillability for each issuer and 0050",
            "Verifiable corporate-action/dividend/split/delisting coverage",
            "Verified ETF 0050 and matched TAIEX total-return historical prices",
            "Matched execution-cost, slippage, spread and liquidity evidence",
            "Matured independent outcomes and out-of-sample significance",
        ],
        "interpretation": "PRECOMMITTED_RESEARCH_EXPERIMENT_NOT_CERTIFIED_PERFORMANCE; NO_BROKER_ORDERS",
    }
    write_atomic(out / "latest_status.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="tw-market-data")
    args = parser.parse_args()
    print(json.dumps(run(args.data_root), ensure_ascii=False))


if __name__ == "__main__":
    main()
