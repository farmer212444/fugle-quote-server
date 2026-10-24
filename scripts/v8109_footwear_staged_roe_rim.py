#!/usr/bin/env python3
"""V8.10.9: footwear 2027-2031 gradual ROE fade and residual-income value.

Replaces the false assumption "2027 EPS/BVPS = perpetual franchise ROE".
Base/Bull/Bear are ONLY hypotheses, never empirically calibrated return
probabilities, actual long-run ROE guidance, firm NAV appraisal or a buy order.

RIM: V/B0 = 1 + Σ[(ROE_t-Ke)*B_(t-1)/(1+Ke)^t]/B0 +
 ((ROE_terminal-Ke)*B_T/(Ke-g))/(1+Ke)^T/B0.
ROE from 2027 -> 2031 linearly; B_t follows clean surplus with stated
hypothetical cash-payout ratio; 2032+ terminal ROE at g=2% book growth.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT=Path("tw-market-data/research/footwear_pb_2016_2026")
INPUT=ROOT/"2027_2031_staged_roe_rim_inputs.json"
HISTORY=ROOT/"full_pb_summary.json"
OUTPUT=ROOT/"2027_2031_staged_roe_rim_shadow.json"
EXPECTED_CASES=("Bear","Base","Bull")


def numeric(v,label):
    if type(v) not in (int,float) or not math.isfinite(v):
        raise ValueError("NOT_FINITE_"+label)
    return float(v)


def value_path(B0, first_eps, terminal_roe, ke, g, payout, years=5):
    B=numeric(B0,"book")
    E=numeric(first_eps,"eps")
    terminal=numeric(terminal_roe,"terminal_roe")
    k=numeric(ke,"discount")
    growth=numeric(g,"terminal_growth")
    dividend=numeric(payout,"payout")
    if (B<=0 or E<0 or not 0<=dividend<=1 or
        not 0<=terminal<=.30 or not .065<=k<=.25 or k<=growth+.025
        or years!=5 or growth<0 or growth>.04):
        raise ValueError("INVALID_RIM_FINANCIAL_ASSUMPTIONS")
    first_roe=E/B
    pv_ri=0.
    years_out=[]
    for year in range(1,years+1):
        normalized_roe=first_roe+(terminal-first_roe)*(year-1)/(years-1)
        eps=B*normalized_roe
        ri=(normalized_roe-k)*B
        discounted=ri/(1+k)**year
        payout_amount=eps*dividend
        years_out.append({
            "fiscal_year":2026+year,
            "starting_book_per_share":round(B,4),
            "roe_pct":round(normalized_roe*100,4),
            "eps_hypothesis":round(eps,4),
            "earnings_paid_cash_dividends_per_share":round(payout_amount,4),
            "ending_book_per_share":round(B+eps-payout_amount,4),
            "residual_income_per_share":round(ri,4),
            "present_value_of_residual_income":round(discounted,4)
        })
        pv_ri+=discounted
        B+=eps-payout_amount
    terminal_ri=(terminal-k)*B
    terminal_pv=(terminal_ri/(k-growth))/(1+k)**years
    value=B0+pv_ri+terminal_pv
    return {
       "value_per_share":value,
       "pv_explicit_RI":pv_ri,
       "pv_terminal_RI":terminal_pv,
       "end_year_2031_book_per_share":B,
       "terminal_2032_implied_ROE_pct":terminal*100,
       "yearly_staged_path":years_out
    }


def inverse_roe(stock,first_eps,price_goal,g,payout):
    bv=stock["parent_BVPS_2026q2"]
    cost=stock["longrun_cost_of_equity"]
    lo,hi=.0,.30
    if value_path(bv,first_eps,hi,cost,g,payout)["value_per_share"]<price_goal:
        return None
    for i in range(72):
        mid=(lo+hi)/2
        calc=value_path(bv,first_eps,mid,cost,g,payout)["value_per_share"]
        if calc<price_goal:lo=mid
        else:hi=mid
    return 100*(hi+lo)/2


def validate_filing(code,s,dates):
    h=s["h1_2026_reported"]
    bv=numeric(s["parent_BVPS_2026q2"],"bvps")
    price=numeric(s["price_2026_10_22"],"price")
    pb=numeric(s["twse_PB_2026_10_22"],"pb")
    if price<=0 or bv<=0 or abs(price/bv-pb)>.02:
        raise ValueError("OFFICIAL_TWSE_REFERENCE_PB_NOT_MATCH_PRICE_BOOK")
    if (h["parent_equity_k"]<=0 or h["total_assets_k"]<=0
        or h["total_liabilities_k"]<0 or
        h["total_assets_k"]-h["total_liabilities_k"]<h["parent_equity_k"]):
        raise ValueError("PARENT_BOOK_NOT_RECONCILED_WITH_CONSOLIDATED_EQUITY")
    shares_from_eps=h["parent_profit_k"]/h["reported_parent_eps"] # thousands of shares
    shares_from_equity=h["parent_equity_k"]/bv
    if abs(shares_from_equity/shares_from_eps-1)>.01:
        raise ValueError("SHARE_UNITS_PARENT_EPS_VS_EQUITY_MISMATCH")
    if h["pretax_profit_k"]<0 or h["revenue_k"]<=0 or h["gross_profit_k"]<=0:
        raise ValueError("UNEXPECTED_FINANCIAL_SIGN")
    nonop=h["pretax_profit_k"]-h["operating_profit_k"]
    nonop_share=nonop/h["pretax_profit_k"]
    out={
      "first_source_h1_asof":"2026-06-30",
      "reported_h1_revenue_billion_TWD":round(h["revenue_k"]/1e6,3),
      "reported_h1_gross_margin_pct":round(100*h["gross_profit_k"]/h["revenue_k"],3),
      "reported_h1_operating_profit_billion_TWD":round(h["operating_profit_k"]/1e6,3),
      "reported_h1_parent_profit_billion_TWD":round(h["parent_profit_k"]/1e6,3),
      "reported_h1_EPS":h["reported_parent_eps"],
      "reported_parent_equity_billion_TWD":round(h["parent_equity_k"]/1e6,3),
      "reported_h1_nonoperating_net_billion_TWD":round(nonop/1e6,3),
      "fraction_of_h1_pretax_profit_from_nonoperating_net_pct":round(100*nonop_share,3),
      "parent_BVPS_2026q2":bv,
      "implied_shares_from_equity_million":round(shares_from_equity/1000,3),
      "group_noncontrolling_equity_k":
          h["total_assets_k"]-h["total_liabilities_k"]-h["parent_equity_k"],
      "parent_book_2027_future_verified":False,
      "operating_nonoperating_disaggregated_original_notes_verified":False
    }
    if code=="9802":
        q=s.get("q3_2026_preliminary")
        if q is None or q.get("preliminary_not_full_audited_report") is not True:
            raise ValueError("FALSE_Q3_AUDIT_STATUS")
        if "9802_q3_selfearnings_reprint" not in dates:
            raise ValueError("Q3_SOURCE_MISSING")
        gm=q["quarter_gross_profit_k"]/q["quarter_revenue_k"]
        op=q["quarter_operating_profit_k"]
        gross=q["quarter_gross_profit_k"]
        if not .12<=gm<=.14 or op>gross:
            raise ValueError("Q3_PUBLIC_GROSS_MARGIN_ARITHMETIC_MISMATCH")
        if abs(q["quarter_parent_profit_k"]/shares_from_equity*1 - q["quarter_eps"])>.03:
            raise ValueError("Q3_EPS_AND_PARENT_SHARE_COUNT_INCONSISTENT")
        out["q3_preliminary_not_full_statement"]={
          "gross_margin_pct":round(100*gm,3),
          "reported_q3_eps":q["quarter_eps"],
          "q3_reported_revenue_billion":round(q["quarter_revenue_k"]/1e6,3),
          "q3_nonoperating_net_million":round((q["quarter_pretax_profit_k"]-op)/1000,3),
          "source_audit":"DATED_COMPANY_MOPS_SELFRESULT_REPRINT_UNVERIFIED_COMPLETE_Q3_REPORT"}
    else:
        if nonop_share<.60 or nonop_share>.85:
            raise ValueError("BAOCHENG_H1_NONOPERATING_DEPENDENCE_NOT_EXPOSED")
        out["material_h1_nonoperating_quality_risk_flag"]=True
    return out


def compute(data,hist):
    if (data.get("schema")!="V8109_FOOTWEAR_STAGED_ROE_RESIDUAL_INCOME_ASSUMPTIONS_V1"
        or data.get("price_reference_date")!="2026-10-22"
        or data.get("compiled_at_local_date")!="2026-10-24"
        or data.get("last_certified_book_quarter")!="2026Q2"
        or hist.get("schema")!="V8107_TWSE_2016_2026_DAILY_PB_RESEARCH_V1"
        or hist.get("all_full_listing_histories_certified") is not True):
        raise ValueError("HISTORICAL_PB_OR_CURRENT_BOOK_VINTAGE_MISMATCH")
    policy=data["method"]
    if (policy["first_earnings_year"]!=2027 or policy["last_explicit_year"]!=2031
        or policy["formal_Aplus_added"]!=0 or policy["trade_orders_placed"]!=0
        or policy["fair_price_hypotheses_not_tradable"] is not True
        or policy["forecast_eps_and_roe_not_PIT_verified"] is not True
        or policy["finite_horizon_not_perpetual_2027_ROE"] is not True):
        raise ValueError("FAKE_PIT_OR_FORMAL_MODEL_PROMOTION")
    growth=numeric(policy["longterm_terminal_growth_rate"],"g")
    histmap={row["issuer"]:row for row in hist["companies"]}
    if set(data["stocks"])!={"9802","9904"}:raise ValueError("RESEARCH_UNIVERSE_MISMATCH")
    for row in data["sources"].values():
        if (row.get("original_MOPS_pdf_sha256") is not None
            or row["event_date"]>"2026-10-24" or not row["url"].startswith("https://")):
            raise ValueError("UNARCHIVED_SOURCE_MISLABELED_VERIFIED")
    output={}
    for code,stock in data["stocks"].items():
        if (histmap[code]["asof_2026_10_22_pb"]!=stock["twse_PB_2026_10_22"]):
            raise ValueError("OFFICIAL_PB_REFERENCE_CHANGED")
        r=validate_filing(code,stock,data["sources"])
        cases=stock["cases"]
        if [x["name"] for x in cases]!=["Bear","Base","Bull"]:
            raise ValueError("SCENARIOS_UNSORTED_MISSING")
        B=stock["parent_BVPS_2026q2"]
        price=stock["price_2026_10_22"]
        k=stock["longrun_cost_of_equity"]
        payout=stock["shareholder_payout_rate_2027_to_2031_hypothesis"]
        rows=[]
        for c in cases:
            eps=numeric(c["2027_EPS"],"eps")
            term=numeric(c["terminal_ROE_from_2031"],"terminalroe")
            result=value_path(B,eps,term,k,g,payout)
            val=result["value_per_share"]
            if val<=0:
                raise ValueError("NEGATIVE_RIM_EQUITY_VALUE_REQUIRES_ALTERNATE_FLOOR")
            rows.append({
              "case":c["name"],"2027_EPS_hypothesis":eps,
              "2027_ROE_from_prior_2026q2_book_pct":round(eps/B*100,3),
              "terminal_2032_sustainable_ROE_hypothesis_pct":round(term*100,3),
              "hypothetical_shareholder_payout_ratio_pct":round(payout*100,1),
              "RIM_price_if_assumptions_hold":round(val,2),
              "RIM_PB_on_2026Q2_book":round(val/B,3),
              "model_upside_vs_2026_10_22_close_pct":round(100*(val/price-1),2),
              "pv_negative_or_positive_future_residual_income":round(result["pv_explicit_RI"],2),
              "pv_terminal_residual_income":round(result["pv_terminal_RI"],2),
              "2027_to_2031_accounting_projection":result["yearly_staged_path"],
              "original_PIT_and_forward_ROE_verified":False,
              "formally_certified_Aplus":False,
            })
        base=cases[1]
        first_eps=base["2027_EPS"]
        current_requirement=inverse_roe(stock,first_eps,price,g,payout)
        hurdle30=inverse_roe(stock,first_eps,price*1.30,g,payout)
        if current_requirement is None or hurdle30 is None:
            raise ValueError("TERMINAL_ROE_PRICE_HURDLE_NOT_SOLVABLE")
        equity_cost_up= k+.02
        equity_cost_down=k-.02
        sensitivity={}
        for tag,discount in (("Ke_plus_2pp",equity_cost_up),("Ke_minus_2pp",equity_cost_down)):
            v=value_path(B,first_eps,base["terminal_ROE_from_2031"],discount,g,payout)["value_per_share"]
            sensitivity[tag]={"cost_of_equity_pct":round(discount*100,2),"RIM_price":round(v,2)}
        output[code]={
         "name":stock["name"],"price_2026_10_22":price,
         "source_reconciled_reported_financials":r,
         "previous_single_year_base_eps_not_permanent_roe":first_eps,
         "2027_single_year_ROE_pct":round(first_eps/B*100,3),
         "2027_2031_staged_scenarios":rows,
         "required_terminal_ROE_to_justify_current_price_pct":round(current_requirement,3),
         "required_terminal_ROE_for_30pct_hypothetical_upside_pct":round(hurdle30,3),
         "base_long_run_ROE_pct":round(base["terminal_ROE_from_2031"]*100,3),
         "base_cost_of_equity_sensitivity":sensitivity,
         "revenue_to_operating_cash_flow_profit_bridge_certified":False,
         "historical_0050_total_return_beat_probability_verified":False,
         "all_13_quality_gates_passed":False,
         "research_only_not_buy":True
        }
    return {
     "schema":"V8109_FOOTWEAR_5YEAR_FADE_RESIDUAL_INCOME_STRESS_V1",
     "compiled_date":"2026-10-24","prices_through":"2026-10-22",
     "price_and_BVPS_asof_not_latest_2027_book":True,
     "forward_terminal_ROE_subjective_unverified":True,
     "full_original_MOPS_files_and_first_tradable_timestamp_verified":False,
     "ROE_discount_rates_are_internal_assumptions":True,
     "realized_one_year_stock_total_return_vs_0050":None,
     "probability_of_2027_excess_return_backtested":None,
     "formal_Aplus_added":0,"orders_placed":0,
     "five_issuers_historical_TWSE_PB_unchanged":True,
     "companies":output
    }


def main():
    data=json.loads(INPUT.read_bytes())
    hist=json.loads(HISTORY.read_bytes())
    result=compute(data,hist)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({code:{
      "price":row["price_2026_10_22"],
      "nonop_H1_share_pretax_pct":row["source_reconciled_reported_financials"]["fraction_of_h1_pretax_profit_from_nonoperating_net_pct"],
      "base_RIM_fair":row["2027_2031_staged_scenarios"][1]["RIM_price_if_assumptions_hold"],
      "base_upside_pct":row["2027_2031_staged_scenarios"][1]["model_upside_vs_2026_10_22_close_pct"],
      "longrun_roe_required_price":row["required_terminal_ROE_to_justify_current_price_pct"],
      "longrun_roe_required_plus30":row["required_terminal_ROE_for_30pct_hypothetical_upside_pct"],
    } for code,row in result["companies"].items()},ensure_ascii=False))


if __name__=="__main__":
    main()
