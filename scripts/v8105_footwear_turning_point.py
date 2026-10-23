"""V8.10.5 footwear operating leverage / turning-point research shadow.

No formal A+/Exit modification. Corporate quarterly release date alone does
not certify a filing's exact first-observed timestamp or historical PIT.
No scenario sensitivity below is a forward EPS forecast.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

REPORT_DATE = dt.date(2026, 10, 23)
LEDGER = Path("tw-market-data/evidence/v880/insider_reviews/footwear_turning_point_corporate_20261023.json")
JOINT = Path("tw-market-data/evidence/v880/insider_reviews/20261023_joint_footwear_two_path_readiness.json")
OUTPUT = Path("tw-market-data/evidence/v880/insider_reviews/20261023_footwear_turning_point_shadow.json")
ALLOWED_SOURCE_DOMAINS = ("https://www.fulgentsun.com/", "https://www.chungjye.com.tw/")
RECOVERY_MARGIN_PP = 1.0
HYPOTHETICAL_AFTER_TAX_KEEP = .80


def _valid_q(date):
    if not isinstance(date, str) or len(date)!=6 or date[4]!="Q" or date[-1] not in "1234":
        raise ValueError("INVALID_QUARTER_ID")
    try:
        year=int(date[:4])
    except (ValueError, TypeError) as exc:
        raise ValueError("INVALID_QUARTER_ID") from exc
    if year<2000:
        raise ValueError("INVALID_QUARTER_YEAR")
    return 4*year+int(date[-1])


def _money(row, key):
    value=row.get(key)
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError("INVALID_QUARTER_FINANCIAL_"+key)
    return float(value)


def _financials(data, issuer, *, date=REPORT_DATE):
    company=data["companies"][issuer]
    rows=company["quarters"]
    releases=data["sources"]
    periods=set()
    available=[]
    for row in rows:
        period=_valid_q(row.get("period"))
        if period in periods:
            raise ValueError("DUPLICATE_QUARTER_RECORD")
        periods.add(period)
        for key in ("revenue","gross_profit","operating_profit","eps","gm_reported_pct"):
            _money(row,key)
        if row["revenue"]<=0 or row["gross_profit"]<0 or row["gross_profit"]>row["revenue"]:
            raise ValueError("INVALID_REVENUE_GROSS_PROFIT_RELATION")
        calculated=100*row["gross_profit"]/row["revenue"]
        if abs(calculated-row["gm_reported_pct"])>.2:
            raise ValueError("GROSS_MARGIN_SOURCE_ARITHMETIC_MISMATCH")
        if "operating_expense" in row:
            if abs(row["gross_profit"]-row["operating_expense"]-row["operating_profit"])>2:
                raise ValueError("OPERATING_PROFIT_BRIDGE_ARITHMETIC_MISMATCH")
        source=releases[row["source_key"]]
        url=source["url"]
        if not isinstance(url,str) or not url.startswith(ALLOWED_SOURCE_DOMAINS):
            raise ValueError("UNEXPECTED_NONISSUER_RESULTS_SOURCE")
        issued=dt.date.fromisoformat(source["stated_release_date"])
        if issued>date:
            continue
        available.append(dict(row,source_release_date=issued.isoformat(),
                              release_exact_first_seen_verified=source["first_public_at_verified"]))
    by_index={_valid_q(r["period"]):r for r in available}
    recent_year=max(r["period"][:4] for r in available)
    chronological=sorted((r for r in available if r["period"].startswith(recent_year) and
                         not r.get("historical_quarter_source_release_is_later_comparative")),
                         key=lambda r:_valid_q(r["period"]))
    if len(chronological)<2:
        return company, chronological, None
    before, after=chronological[-2:]
    if _valid_q(after["period"]) != _valid_q(before["period"])+1:
        raise ValueError("NONCONSECUTIVE_LATEST_QUARTERS")
    return company, chronological, (before, after)


def quarter_bridge(before, after):
    revenue_delta=_money(after,"revenue")-_money(before,"revenue")
    gp_delta=_money(after,"gross_profit")-_money(before,"gross_profit")
    op_delta=_money(after,"operating_profit")-_money(before,"operating_profit")
    ratio_before=100*before["gross_profit"]/before["revenue"]
    ratio_after=100*after["gross_profit"]/after["revenue"]
    return {
      "previous":before["period"],"latest":after["period"],
      "unit":"NTD_thousands",
      "revenue_growth_pct":round(100*revenue_delta/before["revenue"],4),
      "incremental_revenue_ntd_thousands":round(revenue_delta,2),
      "incremental_gross_profit_ntd_thousands":round(gp_delta,2),
      "incremental_operating_profit_ntd_thousands":round(op_delta,2),
      "implied_increase_in_operating_expense_ntd_thousands":round(gp_delta-op_delta,2),
      "incremental_gross_profit_per_extra_sales_pct":
          round(100*gp_delta/revenue_delta,4) if revenue_delta>0 else None,
      "gross_margin_before_pct":round(ratio_before,4),
      "gross_margin_latest_pct":round(ratio_after,4),
      "gross_margin_qoq_change_pp":round(ratio_after-ratio_before,4),
      "operating_margin_before_pct":round(100*before["operating_profit"]/before["revenue"],4),
      "operating_margin_latest_pct":round(100*after["operating_profit"]/after["revenue"],4),
      "operating_expense_rate_before_pct":round(100*(before["gross_profit"]-before["operating_profit"])/before["revenue"],4),
      "operating_expense_rate_latest_pct":round(100*(after["gross_profit"]-after["operating_profit"])/after["revenue"],4),
      "eps_previous":before["eps"],"eps_latest":after["eps"]
    }


def evaluate(data, joined, *, asof=REPORT_DATE):
    if data.get("schema")!="FOOTWEAR_CORPORATE_RESULTS_DATED_RESEARCH_V1" or joined.get("schema")!="V8105_FOOTWEAR_2_OFFICIAL_COMPONENTS_RESEARCH_PRECHECK":
        raise ValueError("UNEXPECTED_RESEARCH_LEDGER_SOURCE")
    if data.get("formal_Aplus_changed") is not False or joined.get("formal_Aplus_added")!=0:
        raise ValueError("UNAUTHORIZED_FORMAL_A_PLUS_PROMOTION")
    if asof>REPORT_DATE:
        raise ValueError("UNAUTHORIZED_FORWARD_DATED_SNAPSHOT")
    frozen={r["code"]:r for r in joined["company_rows"]}
    if set(frozen)!=set(data["companies"]):
        raise ValueError("SOURCE_UNIVERSE_MISMATCH")
    scores={}
    for code in sorted(frozen):
        candidate=frozen[code]
        company, quarters, pair=_financials(data,code,date=asof)
        if (candidate.get("insider_market_and_low_price_two_factor_precheck") is not True or
            candidate.get("strategy_A_publicly_executable_signal") is not False):
            raise ValueError("UNVERIFIED_ISSUER_PRECHECK_OR_PROMOTED_ENTRY")
        if pair is None:
            raise ValueError("MISSING_COMPARABLE_QUARTERS")
        before, after=pair
        bridge=quarter_bridge(before,after)
        gm=bridge["gross_margin_qoq_change_pp"]
        op=bridge["incremental_operating_profit_ntd_thousands"]
        confirmed=gm>=RECOVERY_MARGIN_PP and op>0 and after["operating_profit"]>0
        stage=("PROFIT_TURN_PRECHECK_PENDING_PIT" if confirmed
               else "REVENUE_WITH_NO_OPERATING_PROFIT_CONVERSION" if
               bridge["incremental_revenue_ntd_thousands"]>0 and op<=0
               else "UNCONFIRMED_OR_WEAK_OPERATING_CONVERSION")
        outstanding=company["issued_shares_current_snapshot"]
        if type(outstanding) is not int or outstanding<=0 or company["historical_issued_shares_PIT_certified"] is not False:
            raise ValueError("CAPITAL_SNAPSHOT_OR_HISTORICAL_CERTIFICATION_MISMATCH")
        one_pp=after["revenue"]*1000*.01*HYPOTHETICAL_AFTER_TAX_KEEP/outstanding
        scores[code]={
            "issuer":company["name"],"latest_release_date_stated":after["source_release_date"],
            "latest_financial_quarter":after["period"],
            "latest_release_original_exact_time_PIT_verified":after["release_exact_first_seen_verified"],
            "bridge":bridge,"turning_research_status":stage,
            "earnings_recovery_1pp_provisional":confirmed,
            "next_strong_confirmation_gm_min_pct":round(bridge["gross_margin_latest_pct"]+RECOVERY_MARGIN_PP,2),
            "next_strong_confirmation_operating_profit_min_ntd_thousands":after["operating_profit"],
            "no_auto_buy_or_recommendation":True,
            "hypothetical_plus_one_gm_pp_quarter_eps_effect_ntd":round(one_pp,4),
            "hypothetical_plus_one_gm_pp_annualized_eps_effect_ntd":round(one_pp*4,4),
            "sensitivity_assumption":"Same quarterly revenue x +1 gross-margin point, flat operating expenses, 20% hypothetical incremental tax and unchanged Oct-22 shares. Does NOT forecast 2027 EPS.",
            "source_data_PIT_fully_independently_verified":False,
            "formal_13_gates_modified":False,"2027_Base_price_revised":False,
            "risk":"Q1/Q2 vs Q3 seasonal mix, factory ramp, expenses, FX, orders and original first-public time can all alter apparent turn."
        }
    return {
        "schema":"V8105_FOOTWEAR_PROFIT_BRIDGE_ASOF_RESEARCH_SHADOW_V1",
        "asof":asof.isoformat(),"issuer_count":len(scores),
        "method":"SEPARATE_TWO_SOURCE_PRECHECK_FROM_ACTUAL_PUBLISHED_QUARTER_OPERATING_BRIDGE",
        "all_returns_unknown":True,
        "no_real_historical_12m_outperformance_results":True,
        "formal_Aplus_new_count":0,"formal_Exit_changed":False,
        "quarter_preliminary_issuer_press_releases_not_complete_first_seen_PIT":True,
        "companies":scores,
    }


def main():
    data=json.loads(LEDGER.read_bytes())
    joint=json.loads(JOINT.read_bytes())
    output=evaluate(data,joint)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({c:{"stage":x["turning_research_status"],
                          "GM_qoq_pp":x["bridge"]["gross_margin_qoq_change_pp"],
                          "operating_change_k":x["bridge"]["incremental_operating_profit_ntd_thousands"],
                          "eps_one_pp_annualized_hypothesis":x["hypothetical_plus_one_gm_pp_annualized_eps_effect_ntd"]}
                        for c,x in output["companies"].items()},ensure_ascii=False))


if __name__=="__main__":
    main()
