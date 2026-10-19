#!/usr/bin/env python3
"""Explain EXACTLY why normalized issuers never reach V8.8.1 model rows.

Uses the same MarketData instance as the real engine, but never changes estimates.
This is a diagnostic only; not a substitute for PIT or financial certification.
"""
import argparse
import collections
import json
from pathlib import Path

from tw_model_v880.data import MarketData
from tw_model_v880.math import number

def classify(data, report):
    expected = report["data_scope"]["normalized_issuers"]
    actual = len(data.history)
    if expected != actual:
        raise ValueError("NORMALIZED_SNAPSHOT_COUNT_MISMATCH: expected=%d current=%d" % (expected, actual))
    modeled = [str(x["code"]) for x in report["all_model_row_summary"]]
    if len(set(modeled)) != len(modeled):
        raise ValueError("AMBIGUOUS_MODELED_CODE_UNIVERSE")
    if len(modeled) != report["data_scope"]["model_rows"]:
        raise ValueError("MODELED_COUNT_MISMATCH")
    if any(code not in {key[1] for key in data.history} for code in modeled):
        raise ValueError("MODELED_CODE_NOT_IN_FINANCIAL_UNIVERSE")
    new = []
    master = data.evidence.get("master", {})
    for (market, code), historical in sorted(data.history.items()):
        if code in modeled:
            continue
        missing = []
        if data.period not in historical:
            missing.append("NO_CURRENT_ELIGIBLE_QUARTER_INCOME")
        else:
            absent_quarters = [q for q in data.required_periods if q not in historical]
            if absent_quarters:
                missing.append("INCOMPLETE_EIGHT_QUARTER_INCOME")
        price = data.prices.get((market, code))
        if not price:
            missing.append("NO_MATCHING_OFFICIAL_PRICED_ISSUER")
        else:
            close = number(price.get("close"))
            volume = number(price.get("volume_shares"))
            if close is None or volume is None:
                missing.append("NO_ELIGIBLE_CLOSE_OR_VOLUME")
            elif close < 8:
                missing.append("PRICE_BELOW_8_MODEL_RESEARCH_FLOOR")
            elif close * volume < 12000000:
                missing.append("LOW_SINGLE_DAY_TRADING_VALUE_BELOW_12M_NTD")
        if code not in data.revenue:
            missing.append("NO_CURRENT_MONTHLY_REVENUE")
        if code not in master:
            missing.append("NO_ELIGIBLE_SHARE_MASTER_INPUT")
        if not missing:
            missing.append("OTHER_ESTIMATE_PRECHECK_OR_IDENTITY_CONFLICT_REQUIRES_INVESTIGATION")
        latest = historical.get(data.period) or next(iter(historical.values()))
        new.append({
            "market": market, "code": code, "name": latest.get("name"),
            "primary_blocker": missing[0], "all_blockers": missing,
            "latest_quarter_present": data.period in historical,
            "quarters_present": len(historical),
            "PIT_issuer_master_verified": False,
            "formal_Aplus": False
        })
    if len(new) != expected - len(modeled):
        raise ValueError("UNMODELED_IDENTITY_RECONCILIATION_MISMATCH")
    counts = dict(sorted(collections.Counter(x["primary_blocker"] for x in new).items()))
    all_blockers = dict(sorted(collections.Counter(k for x in new for k in x["all_blockers"]).items()))
    return {
        "model": report["model"],
        "estimate_vintage": report["estimate_vintage"],
        "reference_price_date": report["asof_price_date"],
        "financial_last_quarter": data.period,
        "normalized_universe": expected, "modeled": len(modeled), "unmodeled": len(new),
        "primary_blocker_counts": counts,
        "all_blocker_counts": all_blockers,
        "source_errors": len(data.errors),
        "PIT_universe_verified": False, "certified_marketwide_ranking": False,
        "interpretation": (
            "Exact model entry exclusions as of estimate vintage. Multiple blockers preserved. "
            "Policy prices and one-day trading value are model research floors, not exchange delisting status. "
            "Missing share master cannot be filled with guessed shares."
        ),
        "unmodeled_issuers": new
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="tw-market-data")
    p.add_argument("--research", default="tw-market-data/rankings/latest_research.json")
    p.add_argument("--output", default="tw-market-data/rankings/unmodeled_blockers.json")
    a = p.parse_args()
    report = json.loads(Path(a.research).read_text(encoding="utf-8"))
    data = MarketData(a.data_dir, report["estimate_vintage"])
    result = classify(data, report)
    dest = Path(a.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("normalized_universe", "modeled", "unmodeled",
                                             "primary_blocker_counts", "PIT_universe_verified")},
                     ensure_ascii=False))

if __name__ == "__main__":
    main()
