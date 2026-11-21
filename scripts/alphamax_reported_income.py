#!/usr/bin/env python3
"""Reconcile factual general-industry YTD income; never annualize or rank."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphamax.core import ContractError
from alphamax.reported_income import reported_income_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-ref-file", type=Path, required=True)
    parser.add_argument("--money-unit", required=True, choices=["TWD_thousands"])
    parser.add_argument("--period-basis", required=True, choices=["year_to_date"])
    parser.add_argument("--codes", nargs="+", default=["2330", "2317", "6206", "9802"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = reported_income_snapshot(
            args.source_root, codes=args.codes,
            source_commit=args.source_ref_file.read_text(encoding="utf-8").strip(),
            units={"money": args.money_unit, "eps": "TWD_per_share", "period_basis": args.period_basis},
        )
    except (ContractError, ValueError, TypeError, KeyError, OSError) as exc:
        report = {"status": "BLOCKED_REPORTED_FACTS", "reason": str(exc), "buy_signal": False, "investment_certified": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("status", "reconciled_count", "requested_count", "reason")}, ensure_ascii=False))
    return 0  # A disclosed source gap does not turn code CI into trading approval.


if __name__ == "__main__":
    raise SystemExit(main())
