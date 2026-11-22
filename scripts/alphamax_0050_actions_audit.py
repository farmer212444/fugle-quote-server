#!/usr/bin/env python3
"""Report known 0050 split/dividend evidence gaps; never estimate returns."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from alphamax.benchmark_0050_action_audit import audit_0050_corporate_action_gaps


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--packet", type=Path, required=True)
    p.add_argument("--notice-root", type=Path, default=None)
    p.add_argument("--output", type=Path, default=Path("alphamax-0050-action-gap.json"))
    args = p.parse_args()
    report = audit_0050_corporate_action_gaps(
        json.loads(args.packet.read_text(encoding="utf-8")),
        notice_root=args.notice_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "raw_sessions": report["raw_price_session_count"],
        "notice_verification_status": report["retrospective_notice_reverification"]["status"],
        "notices_reverified": report["retrospective_notice_reverification"]["verified_count"],
        "reference_entitlements": len(report["continuous_holding_reference_cash_entitlements"]),
        "investor_total_return_verified": report["daily_adjusted_investor_total_returns_verified"],
        "raw_prices_span_split_date": report["raw_prices_span_split_date"],
        "split_boundary_quotes_present": (
            report["split_event"]["raw_quote_at_last_pre_split_session"] and
            report["split_event"]["raw_quote_at_first_post_split_session"]),
        "cash_distributions_still_unreconciled": len(report["cash_distribution_reference_candidates"]),
        "verified_after_cost_12m_cohorts": report["oos_12m_after_cost_cohorts_verified"],
        "formal_Aplus": report["formal_Aplus"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
