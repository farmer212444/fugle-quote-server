#!/usr/bin/env python3
"""Fail-closed AlphaMax baseline readiness and research runner.

No return ranking is issued without an independently verified 12-month
total-return bundle with PIT proof and historical delisting coverage.
"""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphamax import ContractError, load_bundle, rank_asof, walk_forward


def readiness(root, bundle):
    blockers = []
    warnings = []
    info = {}
    manifest = Path(root) / "tw-market-data/prices/latest_manifest.json"
    if not manifest.exists():
        blockers.append("OFFICIAL_PRICE_MANIFEST_MISSING")
    else:
        try:
            current = json.loads(manifest.read_text(encoding="utf-8"))
            info["latest_official_price_date"] = current.get("date")
            if current.get("unadjusted_quotes") is not False:
                warnings.append("LEGACY_PRICES_NOT_TOTAL_RETURN_ADJUSTED")
            if current.get("security_master_verified") is not True:
                warnings.append("LEGACY_PIT_SECURITY_MASTER_NOT_VERIFIED")
        except (ValueError, OSError):
            blockers.append("PRICE_MANIFEST_UNREADABLE")
    if not (Path(bundle) / "manifest.json").is_file():
        blockers.append("INDEPENDENT_VERIFIED_BUNDLE_MISSING")
    else:
        try:
            _, rows = load_bundle(bundle)
            info["contract_checked_rows"] = len(rows)
        except (ContractError, ValueError, OSError) as exc:
            blockers.append("BUNDLE_CONTRACT_FAILED:" + str(exc))
    return {"status": "BLOCKED" if blockers else "INPUT_CONTRACT_PASSED_NOT_AUDITED",
            "blockers": blockers, "warnings": warnings, "info": info,
            "note": "A passing input contract does not certify sources, models or live trading."}


def research(bundle, asof=None, top_n=10, min_history=80):
    # Explicit future research dates must be rejected before reading any
    # potentially invalid or contaminated return-label bundle. The gate is
    # a request validation rule, not a side effect of dataset validity.
    if asof is not None:
        from alphamax.core import parse_date
        if parse_date(asof) > date.today():
            raise ContractError("ASOF_IN_FUTURE")
    _, rows = load_bundle(bundle)
    signals = sorted({r["signal_date"] for r in rows})
    asof = asof or signals[-1]
    if asof > date.today().isoformat():
        raise ContractError("ASOF_IN_FUTURE")
    if asof not in signals:
        raise ContractError("ASOF_HAS_NO_SIGNAL_DATE")
    rank = rank_asof(rows, asof, min_history=min_history)
    evaluation = walk_forward(rows, min(asof, date.today().isoformat()),
                              top_n=top_n, min_history=min_history)
    return {"status": "UNCALIBRATED_RESEARCH_ONLY", "asof": asof,
            "predictions": rank["candidates"],
            "trained_rows": rank["model"]["training_rows"],
            "backtest": evaluation,
            "not_available": rank["not_available"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["readiness", "research"])
    p.add_argument("--repo-root", type=Path, default=ROOT)
    p.add_argument("--bundle", type=Path, default=ROOT / "alphamax/datasets/production")
    p.add_argument("--asof")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if args.command == "readiness":
        report = readiness(args.repo_root, args.bundle)
    else:
        try:
            report = research(args.bundle, args.asof, args.top_n)
        except (ContractError, FileNotFoundError, ValueError, OSError) as exc:
            report = {"status": "BLOCKED", "reason": str(exc),
                      "predictions": [], "note": "Do not invent predictions or backtest metrics."}
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
