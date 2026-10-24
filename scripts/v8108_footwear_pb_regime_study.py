"""V8.10.8 footwear: duration of undervaluation and PIT-safe P/B reversion study.

Uses five issuer TWSE daily P/B primary-response archives from V8.10.7.
Only today's BACKFILLED historical P/B observations, not contemporaneously
archived originals. Future P/B change IS NOT realized total stock return:
it has no dividend, splits, taxes, spread, fees, 0050 benchmark, or NAV
credit-risk certification. Descriptive statistics do not certify 2027 A+.
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
from pathlib import Path

from scripts.v8107_footwear_official_pb_history import ROOT, STOCKS, BEGIN, END, audit_one
from scripts.v8107_footwear_official_pb_archive_audit import validate

OUT=ROOT/"footwear_pb_regime_and_reversion_shadow.json"
YEAR_SESSIONS=252
THREE_YEAR_SESSIONS=756


def percentile(values, pct):
    values=sorted(values)
    if not values:
        raise ValueError("PERCENTILE_EMPTY")
    ix=(len(values)-1)*pct
    lo=int(ix)
    return values[lo]*(1-(ix-lo))+values[min(lo+1,len(values)-1)]*(ix-lo)


def group_spells(rows,predicate):
    start=None
    spells=[]
    for i,row in enumerate(rows):
        active=predicate(row)
        if active and start is None:
            start=i
        elif not active and start is not None:
            spells.append({"first":rows[start]["date"],"last":rows[i-1]["date"],
                           "trading_days":i-start,"left_censored":start==0})
            start=None
    if start is not None:
        spells.append({"first":rows[start]["date"],"last":rows[-1]["date"],
                       "trading_days":len(rows)-start,"left_censored":start==0})
    return spells


def fixed_crossing_reversions(rows,threshold,lag=YEAR_SESSIONS):
    if lag<1:
        raise ValueError("UNSAFE_HORIZON")
    matured=[]
    censored=[]
    prev_event=-lag
    # i=0 cannot be crossing because previous session outside the
    # requested historical observation window is not known.
    for i in range(1,len(rows)):
        if i-prev_event<lag:
            continue
        if rows[i]["pb"]>=threshold or rows[i-1]["pb"]<threshold:
            continue
        start=rows[i]
        event={"signal_date":start["date"],"PB_start":start["pb"],
               "trigger":f"FIRST_CROSS_UNDER_{threshold:g}_P_B",
               "horizon_sessions":lag}
        prev_event=i
        if i+lag>=len(rows):
            censored.append(event)
            continue
        finish=rows[i+lag]
        event["PB_end"]=finish["pb"]
        event["end_date"]=finish["date"]
        event["PB_multiple_change_pct"]=round(100*(finish["pb"]/start["pb"]-1),3)
        event["PB_above_entry_after_252trading_days"]=finish["pb"]>start["pb"]
        matured.append(event)
    return matured,censored


def rolling_low_10pct_events(rows,history=THREE_YEAR_SESSIONS,
                             lag=YEAR_SESSIONS):
    # P/B low threshold is computed exclusively from PRIOR observation days,
    # unlike a decade-full-sample P10 threshold (look-ahead biased).
    if history<lag or history<252:
        raise ValueError("HISTORY_WINDOW_TOO_SHORT")
    matured=[]
    censored=[]
    prior_signal=-lag
    for i in range(history,len(rows)):
        previous=[r["pb"] for r in rows[i-history:i]]
        limit=percentile(previous,.1)
        if i-prior_signal<lag or rows[i]["pb"]>limit:
            continue
        # Re-entry after flat-under-threshold can occur on cooldown expiry;
        # signal is "low PB" not necessarily a strict crossing.
        entry=rows[i]
        event={"signal_date":entry["date"],"PB_start":entry["pb"],
               "prior_756_session_P10":round(limit,4),
               "signal_window_excludes_current_and_future":True,
               "horizon_sessions":lag}
        prior_signal=i
        if i+lag>=len(rows):
            censored.append(event)
        else:
            future=rows[i+lag]
            event.update({"PB_end":future["pb"],"end_date":future["date"],
                "PB_multiple_change_pct":round(100*(future["pb"]/entry["pb"]-1),3),
                "PB_above_entry_after_252trading_days":future["pb"]>entry["pb"]})
            matured.append(event)
    return matured,censored


def summarize_events(matured,censored):
    changes=[x["PB_multiple_change_pct"] for x in matured]
    return {
        "matured_independent_events":len(changes),
        "unmatured_latest_events_not_counted":len(censored),
        "historical_PB_change_median_pct":round(statistics.median(changes),3) if changes else None,
        "PB_multiples_rise_frequency_not_stock_win_rate_pct":
            round(100*sum(x["PB_above_entry_after_252trading_days"] for x in matured)/len(changes),2) if changes else None,
        "records":matured,
        "pending":censored,
        "realized_total_stock_returns_including_dividends":None,
        "realized_excess_return_vs_0050":None,
        "transaction_fee_slippage_costs_included":False,
        "safe_to_infer_stock_win_rate_from_PB_only":False
    }


def issuer_regime(code,rows):
    if not rows or rows[-1]["date"]!=END.isoformat():
        raise ValueError("MISSING_TWSE_ANCHOR_DATE")
    if len({r["date"] for r in rows})!=len(rows):
        raise ValueError("DUPLICATE_DAYS")
    for r in rows:
        if not .01<=r["pb"]<=100 or not r["date"].startswith(("201","202")):
            raise ValueError("INVALID_ORIGINAL_RATIO_OR_DATE")
    ratios=[x["pb"] for x in rows]
    by_year={}
    for y in sorted({r["date"][:4] for r in rows}):
        yearly=[r["pb"] for r in rows if r["date"].startswith(y)]
        by_year[y]={"sessions":len(yearly),"PB_median":round(statistics.median(yearly),3),
                    "PB_below_one_pct":round(100*sum(p<1 for p in yearly)/len(yearly),2),
                    "PB_low":min(yearly),"PB_high":max(yearly)}
    thresholds={}
    for th in (1,.9,.75):
        spells=group_spells(rows,lambda x:x["pb"]<th)
        current=next((s for s in reversed(spells) if s["last"]==rows[-1]["date"]),None)
        lagged,pending=fixed_crossing_reversions(rows,th)
        thresholds[str(th)]={
            "time_below_threshold_sessions":sum(s["trading_days"] for s in spells),
            "share_of_observed_days_below_threshold_pct":
                round(100*sum(s["trading_days"] for s in spells)/len(rows),2),
            "spell_count":len(spells),
            "longest_consecutive_spell":max(spells,key=lambda s:s["trading_days"]) if spells else None,
            "ongoing_spell":current,
            "first_5_spells":spells[:5],
            "horizon_252_session_PB_reversion_only":summarize_events(lagged,pending)
        }
    rolling,roll_pending=rolling_low_10pct_events(rows)
    trailing={}
    for window in (252,756):
        if len(ratios)>=window:
            segment=ratios[-window:]
            trailing[str(window)]={
                "sessions":window,"median_PB":round(statistics.median(segment),4),
                "P10_PB":round(percentile(segment,.1),4),
                "P25_PB":round(percentile(segment,.25),4),
                "minimum_PB":min(segment),"maximum_PB":max(segment)}
        else:
            trailing[str(window)]=None
    summary=audit_one(code,[{"month":x["date"][:7],"stat":"OK"}
         for x in rows],"probe")
    # audit_one creates a missing-month list because the synthetic
    # per-trading-day list isn't a monthly source inventory. Only reuse
    # stock identification fields, never source-certification flags.
    return {
        "issuer":code,"name":STOCKS[code][0],
        "observations":len(rows),
        "first_date":rows[0]["date"],"last_date":rows[-1]["date"],
        "current_PB":ratios[-1],
        "full_period_median_PB":round(statistics.median(ratios),4),
        "rolling_PB_stats":trailing,
        "calendar_year_risk_regimes":by_year,
        "absolute_PB_thresholds_and_historic_spells":thresholds,
        "rolling_P10_of_PB_using_only_prior_756_sessions":
          summarize_events(rolling,roll_pending),
        "recent_ROE_book_value_risk_from_issuer_reports_independently_checked":False,
        "historical_PB_to_stock_total_return_conversion_done":False,
        "formal_Aplus":False,
        "expected_2027_total_stock_return_pct":None
    }


def build(root=ROOT):
    validation=validate(root)
    if (validation.get("source_body_sha256_verified_count")!=450
       or validation.get("unique_official_daily_pb_points_recomputed")!=9050):
        raise ValueError("INCOMPLETE_OFFICIAL_ORIGINALS_NOT_BACKTEST_SAFE")
    reports={}
    for code in STOCKS:
        with gzip.open(root/f"{code}_full_originals.json.gz","rb") as f:
            source=json.load(f)
        first=max(BEGIN, __import__("datetime").date.fromisoformat(STOCKS[code][1]))
        observations=sorted([
            dict(r,issuer=code)
            for month in source["months"]
            for r in month.get("rows",[])
            if first<=__import__("datetime").date.fromisoformat(r["date"])<=END
        ],key=lambda o:o["date"])
        reports[code]=issuer_regime(code,observations)
    return {
      "schema":"V8108_FOOTWEAR_PB_REGIME_DURATION_FORWARD_PB_MULTIPLE_ONLY_V1",
      "asof_official_trading_date":"2026-10-22",
      "lookback_start":"2016-10-24",
      "official_primary_source_http_sha_verified":True,
      "total_official_daily_observations":sum(r["observations"] for r in reports.values()),
      "never_claim_PB_rise_as_stock_total_return":True,
      "historical_source_fetch_after_the_fact_not_original_PIT_archive":True,
      "six_month_and_year_ROE_fundamentals_still_not_verified_for_all":True,
      "formal_Aplus_2027":0,
      "2027_performance_vs_0050_known":False,
      "no_stock_trades":True,
      "issuers":reports,
    }


def main():
    out=build()
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    brief={}
    for k,v in out["issuers"].items():
        one=v["absolute_PB_thresholds_and_historic_spells"]["1"]
        rel=v["rolling_P10_of_PB_using_only_prior_756_sessions"]
        brief[k]={
            "PB":v["current_PB"],
            "last252_median":v["rolling_PB_stats"]["252"]["median_PB"],
            "last756_median":v["rolling_PB_stats"]["756"]["median_PB"] if v["rolling_PB_stats"]["756"] else None,
            "under1_days":one["time_below_threshold_sessions"],
            "longest_under1_days":one["longest_consecutive_spell"]["trading_days"] if one["longest_consecutive_spell"] else 0,
            "ongoing_under1_days":one["ongoing_spell"]["trading_days"] if one["ongoing_spell"] else 0,
            "under1_matured_events":one["horizon_252_session_PB_reversion_only"]["matured_independent_events"],
            "rolling_P10_matured":rel["matured_independent_events"],
            "rolling_P10_PB_rise_freq_not_total_return":rel["PB_multiples_rise_frequency_not_stock_win_rate_pct"]
        }
    print(json.dumps(brief,ensure_ascii=False))


if __name__=="__main__":
    main()
