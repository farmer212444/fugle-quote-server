#!/usr/bin/env python3
"""Independent 2027 footwear earnings bridge and upside, research-only V8.10.5.

No analyst consensus, price targets from third parties, retroactive PIT
validation, orders, formal A+ upgrades, or invented matured outperformance.
Historical original MOPS/official TWSE price precheck is an input, not a
complete audited corporate-action or ownership certificate.

Unit contract: revenue / profits in MILLION TWD, shares in MILLION shares.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ASSUMPTIONS = Path("tw-market-data/evidence/v880/insider_reviews/20261023_footwear_2027_independent_assumptions.json")
JOINED = Path("tw-market-data/evidence/v880/insider_reviews/20261023_joint_footwear_two_path_readiness.json")
OUTPUT = Path("tw-market-data/evidence/v880/insider_reviews/20261023_footwear_2027_independent_shadow.json")
SCHEMA = "V8105_2027_FOOTWEAR_INDEPENDENT_SCENARIO_ASSUMPTIONS_V1"
EPS_SHARES_EPSILON = .002
EPS_CASE_ORDER = ("Bear","Base","Bull")


def numeric(x, key):
    if type(x) not in (int, float) or not math.isfinite(x):
        raise ValueError("INVALID_FINANCIAL_INPUT_"+key)
    return float(x)


def assert_case(case, type_name):
    r=numeric(case.get("revenue_m"),"revenue_m")
    g=numeric(case.get("gross_margin_pct"),"gross_margin_pct")
    e=numeric(case.get("opex_rate_pct"),"opex_rate_pct")
    if r<=0 or not (0 <= e < 50 and 0 < g < 70):
        raise ValueError("INVALID_REVENUE_OR_MARGIN_BRIDGE")
    weight=numeric(case.get("weight"),"weight")
    if not 0<=weight<=1:
        raise ValueError("INVALID_SUBJECTIVE_WEIGHT")
    pe=case.get("reasonable_pe")
    if pe is not None and not 1<=numeric(pe,"reasonable_pe")<=30:
        raise ValueError("INVALID_PE_RANGE")
    if type_name=="PRETAX_NONOP_THEN_AFTERTAX_PARENT":
        nonop=numeric(case.get("pre_tax_nonop_m"),"pre_tax_nonop_m")
        retention=numeric(case.get("posttax_parent_ratio"),"posttax_parent_ratio")
        parent=(r*(g-e)/100+nonop)*retention
        if not .5<=retention<=.9:
            raise ValueError("INCONSISTENT_TAX_AND_MINORITY_RETENTION")
        payload={"pre_tax_nonop_m":nonop,"tax_and_attribution_retention":retention}
    elif type_name=="TAXED_OPERATING_PLUS_AFTERTAX_BELOW_OPERATION":
        rest=numeric(case.get("below_op_aftertax_and_minority_m"),"below_op_aftertax_and_minority_m")
        retention=numeric(case.get("op_tax_retention"),"op_tax_retention")
        if not .5<=retention<=.9:
            raise ValueError("INCONSISTENT_OPERATING_TAX_RETENTION")
        parent=r*(g-e)/100*retention+rest
        payload={"post_tax_nonop_and_minority_m":rest,"op_tax_retention":retention}
    else:
        raise ValueError("UNAPPROVED_EARNINGS_BRIDGE_TYPE")
    op=r*(g-e)/100
    return dict(payload,case=case["case"],weight=weight,revenue_m=r,
                gross_margin_pct=g,opex_rate_pct=e,
                operating_profit_m=op,attributable_parent_profit_m=parent,
                attributable_eps_undiluted_millions=None,
                reasonable_pe=pe)


def gm_for_current_price(case, bridge_type, current_price, shares):
    """Invert the exact stated earnings and P/E, not a fitted regression."""
    multiple=numeric(case.get("reasonable_pe"),"reasonable_pe")
    target_net=current_price/multiple*shares
    r=numeric(case["revenue_m"],"revenue_m")
    exp=numeric(case["opex_rate_pct"],"opex_rate_pct")
    if bridge_type=="PRETAX_NONOP_THEN_AFTERTAX_PARENT":
        nonop=numeric(case["pre_tax_nonop_m"],"pre_tax_nonop_m")
        keep=numeric(case["posttax_parent_ratio"],"posttax_parent_ratio")
        needed_op=target_net/keep-nonop
    elif bridge_type=="TAXED_OPERATING_PLUS_AFTERTAX_BELOW_OPERATION":
        rest=numeric(case["below_op_aftertax_and_minority_m"],"below_op_aftertax_and_minority_m")
        keep=numeric(case["op_tax_retention"],"op_tax_retention")
        needed_op=(target_net-rest)/keep
    else:
        raise ValueError("UNAPPROVED_EARNINGS_BRIDGE_TYPE")
    return exp+100*needed_op/r


def evaluate(data, joined):
    if data.get("schema")!=SCHEMA or data.get("compiled_asof")!="2026-10-23":
        raise ValueError("WRONG_ASSUMPTION_SCHEMA_OR_DATE")
    p=data.get("policy") or {}
    if p.get("year")!=2027 or p.get("reference_price_date")!="2026-10-22":
        raise ValueError("BAD_REFERENCE_DATE_OR_FORECAST_YEAR")
    if p.get("pe_independence")!="MULTIPLES_ARE_INTERNAL_HYPOTHESES_NOT_SELL_SIDE_CONSENSUS":
        raise ValueError("ESTIMATE_NOT_INDEPENDENT")
    if p.get("weights_type")!="SUBJECTIVE_SCENARIOS_NOT_BACKTESTED_PROBABILITIES":
        raise ValueError("WEIGHTS_MISLABELED_EMPIRICAL_PROBABILITIES")
    if data.get("quality_state",{}).get("formal_13_gates_all_passed") is not False:
        raise ValueError("INVALID_FORMAL_GATE_PROMOTION")
    if (joined.get("schema")!="V8105_FOOTWEAR_2_OFFICIAL_COMPONENTS_RESEARCH_PRECHECK"
            or joined.get("asof_market_session")!="2026-10-22"
            or joined.get("formal_Aplus_added")!=0):
        raise ValueError("MISSING_OR_PROMOTED_252_INSIDER_RESEARCH_PRECHECK")
    public=dict((r["code"],r) for r in joined.get("company_rows",[]))
    if set(public)!=set(data.get("companies",{})) or set(public)!={"9802","6965"}:
        raise ValueError("MISMATCHED_UNIVERSE")
    dilution=numeric(p.get("share_dilution_stress_pct"),"share_dilution_stress_pct")
    if not 0<=dilution<=25:
        raise ValueError("UNSUPPORTED_DILUTION_STRESS")
    if any(source.get("raw_original_sha256") is not None or
           source.get("historical_first_available_timestamp") is not None
           for source in data["sources"].values()):
        raise ValueError("MISREPRESENTED_DOCUMENT_ARCHIVE_OR_PIT")
    table={}
    for code in ("9802","6965"):
        stock=data["companies"][code]
        trusted=public[code]
        price=numeric(stock.get("current_price"),"current_price")
        shares=numeric(stock.get("shares_asof_current"),"shares_asof_current")
        if price<=0 or shares<=0:
            raise ValueError("INVALID_PRICE_OR_SHARES")
        if abs(trusted["2026_10_22_close"]-price)>EPS_SHARES_EPSILON:
            raise ValueError("PRICE_NOT_SAME_AS_OFFICIAL_ARCHIVE")
        # TWSE snapshot is in shares; model is in million shares.
        capital_m=trusted["jul_aug_sep_market_net_lots_provisional"]*1000/(trusted["three_month_current_capital_percent"]/100)/1e6
        if abs(capital_m-shares)>max(.05, .005*shares):
            raise ValueError("SHARE_COUNT_NOT_CROSSCHECKED_WITH_TWSE")
        if (trusted.get("insider_market_and_low_price_two_factor_precheck") is not True
                or trusted.get("strategy_A_publicly_executable_signal") is not False
                or trusted.get("strategy_B_GM_confirmed_publicly_executable_signal") is not False):
            raise ValueError("PRECHECK_NOT_ELIGIBLE_OR_ALREADY_PROMOTED")
        observed=stock["observed_2026"]
        year=stock["FY2025"]
        for k in ("annual_revenue_m","annual_operating_profit_m","annual_parent_net_m","reported_eps","reported_gm_pct"):
            numeric(year[k],"FY2025_"+k)
        if abs(year["annual_parent_net_m"]/shares-year["reported_eps"])> .18:
            # 2025 and 2026 share weights can differ; tolerance permits modest
            # issuer capital change but rejects unit failures.
            raise ValueError("ANNUAL_EPS_SHARE_UNIT_MISMATCH")
        refcase=stock["cases"]
        if [x.get("case") for x in refcase] != list(EPS_CASE_ORDER):
            raise ValueError("SCENARIO_ORDER_OR_COMPLETENESS_MISMATCH")
        if abs(sum(numeric(x.get("weight"),"weight") for x in refcase)-1)>1e-9:
            raise ValueError("SCENARIO_PROBABILITIES_DONT_SUM_TO_ONE")
        rows=[]
        for spec in refcase:
            bridge=assert_case(spec,stock["earnings_bridge_type"])
            eps=bridge["attributable_parent_profit_m"]/shares
            b_eps=eps/(1+dilution/100)
            pe=bridge["reasonable_pe"]
            if eps<=0 and pe is not None:
                raise ValueError("LOSS_MAKING_PE_MUST_BE_NULL")
            if eps>0 and pe is None:
                raise ValueError("POSITIVE_EPS_REQUIRES_PE_OR_EXPLICIT_VALUATION")
            fair=eps*pe if eps>0 else None
            diluted_fair=b_eps*pe if b_eps>0 else None
            # True nominal gross-margin revenue multiplier per 1.00pp;
            # other costs/tax and capital kept unchanged (not a forecast).
            keep=spec.get("posttax_parent_ratio",spec.get("op_tax_retention"))
            extra_eps=spec["revenue_m"]*.01*keep/shares
            rows.append(dict(bridge,
                attributable_eps=round(eps,4),
                hypothetical_10pct_diluted_eps=round(b_eps,4),
                scenario_fair_price=round(fair,2) if fair is not None else None,
                scenario_upside_pct=round(100*(fair/price-1),2) if fair is not None else None,
                hypothetical_diluted_fair_price=round(diluted_fair,2) if diluted_fair is not None else None,
                earnings_sensitivity_eps_per_1_gm_pp=round(extra_eps,4),
                no_pe_valuation_when_loss=eps<=0))
        base=refcase[1]
        breakeven_eps=price/base["reasonable_pe"]
        required_gm=gm_for_current_price(base,stock["earnings_bridge_type"],price,shares)
        if not (4<=required_gm<=35):
            raise ValueError("UNREASONABLE_BASE_CASE_REVERSE_GM_REQUIRED")
        weighted=sum(r["weight"]*r["attributable_eps"] for r in rows)
        base_fair=rows[1]["scenario_fair_price"]
        entry_cap_for_30pct=base_fair/1.30 if base_fair is not None else None
        table[code]={
            "issuer":stock["name"],
            "reference_date":"2026-10-22",
            "reference_close_twd":price,"current_shares_millions_not_2027_diluted":shares,
            "FY2025_reported_eps":year["reported_eps"],
            "FY2025_reported_GM_pct":year["reported_gm_pct"],
            "2026_latest_public_quarter":observed["latest_quarter"],
            "2026_latest_quarter_GM_pct":observed["latest_q_gm_pct"],
            "2027_cases":rows,
            "weighted_2027_eps_subjective_non_empirical":round(weighted,4),
            "subjective_base_is_at_least_30pct_upside":rows[1]["scenario_upside_pct"] >= 30.0,
            "maximum_theoretical_entry_for_30pct_base_upside_excluding_costs_and_all_gates":round(entry_cap_for_30pct,2) if entry_cap_for_30pct is not None else None,
            "base_breakeven_eps_at_current_price_and_base_PE":round(breakeven_eps,4),
            "base_gm_required_to_justify_current_price_pct":round(required_gm,4),
            "base_gm_margin_recovery_from_latest_q_pp":round(required_gm-observed["latest_q_gm_pct"],4),
            "hypothetical_share_dilution_stress_pct":dilution,
            "price_to_book_bear_valuation_not_computed":True,
            "no_probability_weighted_fair_value_for_negative_eps_bear":any(r["scenario_fair_price"] is None for r in rows),
            "formal_Aplus_or_exit_changed":False,
            "realized_2027_return_vs_0050":None,
            "official_eps_projection_verified":False}
    return {"schema":"V8105_2027_FOOTWEAR_BBB_INDEPENDENT_RESEARCH_SHADOW_V1",
            "valuation_asof":"2026-10-23",
            "reference_price_date":"2026-10-22",
            "assumptions_are_subjective_not_production_forecasts":True,
            "probabilities_not_backtest_calibrated":True,
            "true_issuer_beneficial_holder_PIT_unverified":True,
            "cashflow_CBs_disclosure_dilution_independent_quality_gates_pending":True,
            "actual_2027_0050_excess_returns":None,
            "formal_Aplus_new_issuers":0,"formal_Exit_changed":False,
            "models":table}


def main():
    specs=json.loads(ASSUMPTIONS.read_bytes())
    joined=json.loads(JOINED.read_bytes())
    result=evaluate(specs,joined)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({code:{
        "scenarios":[{"name":z["case"],"eps":z["attributable_eps"],"pe":z["reasonable_pe"],
                      "fair_price":z["scenario_fair_price"],"upside":z["scenario_upside_pct"]} for z in x["2027_cases"]],
        "breakeven_gm":x["base_gm_required_to_justify_current_price_pct"],
        "base_eps_needed":x["base_breakeven_eps_at_current_price_and_base_PE"]}
        for code,x in result["models"].items()},ensure_ascii=False))


if __name__=="__main__":
    main()
