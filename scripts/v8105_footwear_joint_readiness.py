#!/usr/bin/env python3
"""Evidence-only combined footwear insider/price readiness as of 2026-10-23.

This module independently recomputes the join from two current, frozen,
original-source verified research reports. It never certifies identities,
historical filing publication, corporate actions, GM or 365-day returns.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


REPORTS = {
    "insider": Path("tw-market-data/evidence/v880/insider_reviews/20261023_two_official_sources_reconciliation.json"),
    "price": Path("tw-market-data/evidence/v880/insider_reviews/footwear_252_official_price_readiness.json"),
}
OUTPUT = Path("tw-market-data/evidence/v880/insider_reviews/20261023_joint_footwear_two_path_readiness.json")
CODES = ("9802", "6965")


def combine(insiders, prices):
    if insiders.get("schema") != "V8105_TWO_OFFICIAL_SOURCE_CROSSCHECK_RESEARCH_ONLY":
        raise ValueError("INSIDER_OFFICIAL_SOURCE_CROSSCHECK_NOT_AVAILABLE")
    if prices.get("status") != "RESEARCH_UNADJUSTED_PRICE_WINDOW_ONLY":
        raise ValueError("OFFICIAL_COMPLETE_252_WINDOW_UNAVAILABLE")
    if prices.get("ref_date") != "2026-10-22" or prices.get("calendar_sessions") != 252:
        raise ValueError("INCORRECT_252_WINDOW_DATE_OR_COUNT")
    if (insiders.get("claims", {}).get("raw_original_bytes_sha_verified") is not True
            or insiders["claims"].get("mops_every_row_rollforward_checked") is not True
            or insiders["claims"].get("september_name_and_close_share_balances_crosschecked") is not True):
        raise ValueError("OFFICIAL_ORIGINALS_AND_BALANCES_NOT_VERIFIED")
    if (insiders.get("formal_Aplus_or_Exit_changed") is not False
            or prices.get("signal_created") is not False
            or prices.get("formal_Aplus_changed") is not False):
        raise ValueError("UNAUTHORIZED_FORMAL_SIGNAL_OR_GRADE")
    if set(insiders["crosschecks"])!=set(CODES) or set(prices["research_price_candidates"])!=set(CODES):
        raise ValueError("MISMATCHED_TWO_SOURCE_ISSUER_UNIVERSE")
    rows=[]
    for code in CODES:
        holder=insiders["crosschecks"][code]
        price=prices["research_price_candidates"][code]
        if (holder.get("all_cross_source_share_balances_match") is not True
                or holder.get("pass_formal_insider_quality_gate") is not False
                or price.get("source_backed_unadjusted_prices") is not True
                or price.get("price_low_window_certified") is not False):
            raise ValueError("UNVERIFIED_SOURCE_OR_IMPROPER_FORMAL_PROMOTION")
        preliminary_buy=holder.get("research_materiality_0_05pct_current_denominator_observed") is True
        preliminary_low=price.get("provisional_bottom_20pct") is True
        months=holder.get("month_rollforwards") or {}
        if set(months)!={"2026-07","2026-08","2026-09"}:
            raise ValueError("INCOMPLETE_JUL_SEP_MARKET_TRADES")
        consecutive=all(months[m]["market_net_lots_provisional"]>0 for m in sorted(months))
        # Gross margin data remain in a separate UNCERTIFIED research lane.
        # Never manufacture an original published financial report from
        # a third-party quarterly margin table or live self-report.
        rows.append({
            "code":code,"name":holder["name"],
            "jul_aug_sep_market_net_lots_provisional":holder["jul_sep_market_net_lots_provisional"],
            "three_month_current_capital_percent":holder["three_month_net_pct_of_oct22_issued_shares"],
            "three_consecutive_positive_original_market_rows_provisionally":consecutive,
            "three_month_size_0_05pct_precheck":preliminary_buy,
            "252_close_low":price["range_min_close"],
            "252_close_high":price["range_max_close"],
            "2026_10_22_close":price["reference_close"],
            "252_close_position_pct":round(100*price["range_position"],2),
            "low_20pct_unadjusted_precheck":preliminary_low,
            "insider_market_and_low_price_two_factor_precheck":consecutive and preliminary_buy and preliminary_low,
            "strategy_A_publicly_executable_signal":False,
            "strategy_B_GM_confirmed_publicly_executable_signal":False,
            "insider_unique_accounts_certified":False,
            "official_first_publication_and_revision_times_certified":False,
            "dated_historical_issued_share_denominator_certified":False,
            "raw_price_corporate_actions_coverage_certified":False,
            "next_open_fillability_certified":False,
            "latest_two_published_quarter_GM_PIT_certified":False,
            "formal_Aplus_changed":False,
            "automatic_exit":False,
            "unresolved":["UNIQUE_BENEFICIAL_ACCOUNTS",
                          "INSIDER_HISTORICAL_PUBLICATION_REVISION",
                          "HISTORICAL_ISSUED_CAPITAL",
                          "PRICE_ACTION_ADJUSTMENT_AND_FILLABILITY",
                          "STANDALONE_QUARTER_GM_PIT_ORIGINAL",
                          "0050_COMPLETE_DIVIDEND_ADJUSTED_365D_EXECUTION_RETURNS"]
        })
    return {
      "schema":"V8105_FOOTWEAR_2_OFFICIAL_COMPONENTS_RESEARCH_PRECHECK",
      "asof_market_session":"2026-10-22",
      "universe":"TWO_ISSUERS_ONLY_NOT_ALL_FOOTWEAR_STOCKS",
      "original_source_scope":"SIX_MONTHLY_MOPS_POST_TRADE_AND_TWSE_CURRENT_BALANCES_PLUS_45_OFFICIAL_TWSE_STOCK_DAY_MONTHS",
      "minimum_historical_lookback_session_count":252,
      "all_prechecks_are_research_only":True,
      "historical_PIT_backtest_started_or_completed":False,
      "real_one_year_win_rate_vs_0050":None,
      "formal_Aplus_added":0,
      "company_rows":rows,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=OUTPUT)
    args=parser.parse_args()
    ins=json.loads(REPORTS["insider"].read_bytes())
    price=json.loads(REPORTS["price"].read_bytes())
    result=combine(ins,price)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":result["schema"],
                      "two_factor_research_candidates":[r["code"] for r in result["company_rows"] if r["insider_market_and_low_price_two_factor_precheck"]],
                      "validated_A_B_signals":0,
                      "one_year_win_rate":None},
                     ensure_ascii=False))


if __name__=="__main__":
    main()
