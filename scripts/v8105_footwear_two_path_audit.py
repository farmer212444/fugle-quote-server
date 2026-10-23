#!/usr/bin/env python3
"""Live repository readiness audit for footwear insider strategies A and B.

Uses *existing* secondary ToAlpha-derived issuer rows ONLY for descriptive
triage. Does NOT claim any trade, point-in-time original, or one-year return.
Each run recomputes from records already present in the repository.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

INPUT = Path("tw-market-data/evidence/v880/insider_reviews/shoe_makers_202609_secondary_shadow.json")
ETF = Path("tw-market-data/benchmarks/0050/latest_source_status.json")
EXPECTED_MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]


def build(shadow, etf):
    if (shadow.get("schema") != "V1_INSIDER_SECONDARY_SHADOW_NOT_OFFICIAL"
            or shadow.get("months") != EXPECTED_MONTHS
            or shadow.get("record_provenance") != "SECONDARY_MOPS_DERIVED_SUMMARY_ONLY"
            or shadow.get("official_mops_post_trade_originals_received") is not False
            or shadow.get("insider_claims_quality_gate") != "PENDING_ORIGINAL_MOPS_AND_IDENTITY_DEDUP"):
        raise ValueError("INSIDER_SECONDARY_SOURCE_MISCLASSIFIED")
    if etf.get("benchmark_id") != "0050":
        raise ValueError("WRONG_BENCHMARK_SOURCE")
    if not isinstance(shadow.get("records"), list) or not shadow["records"]:
        raise ValueError("MISSING_ISSUER_LIST")
    by_stock = []
    seen = set()
    for rec in shadow["records"]:
        code = str(rec["code"])
        if code in seen:
            raise ValueError("DUPLICATE_ISSUER")
        seen.add(code)
        buy, sell = rec["market_buys"], rec["market_sells"]
        if (not isinstance(buy, list) or not isinstance(sell, list)
                or len(buy) != 6 or len(sell) != 6
                or any(type(x) is not int or x < 0 for x in buy + sell)):
            raise ValueError("INVALID_MONTHLY_TRADE_LOTS")
        three = [b - s for b, s in zip(buy[-3:], sell[-3:])]
        persistence = all(x > 0 for x in three)
        by_stock.append({
            "code": code, "name": rec.get("name"),
            "jul_aug_sep_secondary_monthly_market_net_lots": three,
            "jul_sep_secondary_net_lots": sum(three),
            "three_month_positive_secondary_observed": persistence,
            "original_issuer_buying_certified": False,
            "strategy_a_admitted": False,
            "strategy_b_admitted": False,
            "low_price_252_verified": False,
            "quarterly_margin_PIT_verified": False,
            "risk_label": "SECONDARY_TRIAGE_ONLY_NO_ACTIONABLE_SIGNAL",
        })
    by_stock.sort(key=lambda r: (-r["jul_sep_secondary_net_lots"], r["code"]))
    return {
        "schema": "V8105_FOOTWEAR_TWO_PATH_SOURCE_READINESS_ONLY",
        "research_cutoff_reporting_month": "2026-09",
        "selection_universe": "SIX_SELECTED_FOOTWEAR_ISSUERS_NOT_COMPLETE_SECTOR",
        "not_a_backtest": True,
        "source_months": EXPECTED_MONTHS,
        "only_secondary_market_trade_summary": True,
        "no_official_trade_originals_captured": True,
        "a_early_condition": "3_positive_published_insider_months_AND_bottom20pct_252_closes",
        "b_confirmation_condition": "A_AND_latest_published_quarter_GM_up_at_least_1pp",
        "strategy_a_research_precheck_count": sum(r["three_month_positive_secondary_observed"] for r in by_stock),
        "strategy_a_certified_signal_count": 0,
        "strategy_b_certified_signal_count": 0,
        "strategy_a_independent_matured_return_count": 0,
        "strategy_b_independent_matured_return_count": 0,
        "strategy_a_12m_win_rate_vs_0050": None,
        "strategy_b_12m_win_rate_vs_0050": None,
        "strategy_a_12m_alpha_vs_0050": None,
        "strategy_b_12m_alpha_vs_0050": None,
        "benchmark": {
            "quote_source_status": etf.get("status"),
            "total_return_register_complete": False,
            "matched_full_12m_benchmark_ready": False,
        },
        "unresolved": [
            "MOPS_ORIGINAL_POST_TRADE_EVENTS_AND_PUBLICATION_RECEIPTS",
            "STABLE_HOLDER_IDENTITY_AND_ROLE_DEDUPLICATION",
            "HISTORICAL_SHARES_OUTSTANDING_ASOF_SIGNAL",
            "252_SESSION_SOURCE_BACKED_LOW_PRICE_PERCENTILE",
            "PUBLISHED_STANDALONE_GROSS_MARGIN_PIT_VINTAGES",
            "MATURED_365_DAY_VERIFIED_FILLS_BROKER_COSTS_CORPORATE_ACTIONS",
            "ETF_0050_MATCHED_NET_DIVIDEND_ADJUSTED_TOTAL_RETURN",
            "PRE_REGISTERED_INDEPENDENT_WALK_FORWARD_SIGNIFICANCE",
        ],
        "issuers": by_stock,
        "any_performance_claim_from_this_report": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--insiders", type=Path, default=INPUT)
    parser.add_argument("--benchmark", type=Path, default=ETF)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = build(json.loads(args.insiders.read_text(encoding="utf-8")),
                   json.loads(args.benchmark.read_text(encoding="utf-8")))
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
