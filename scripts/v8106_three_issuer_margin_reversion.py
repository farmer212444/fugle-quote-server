#!/usr/bin/env python3
"""Source-dated comparative quarterly margin stress, 2027/4771/6206.

Explicitly a shadow sensitivity built on still-uncertified 2027 normalized
forecasts: it does not assert annual 2027 GM will match an individual Q2.
Does not silently change EPS, official 13 gates, PE, or trading controls.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT=Path("tw-market-data")
PRIORITY=ROOT/"rankings/latest_evidence_priority.json"
GATE=ROOT/"rankings/v891_gate_progress.json"
EVIDENCE=ROOT/"evidence/v8106_cross_sector_gm_source_observations_20261024.json"
OUTPUT=ROOT/"rankings/v8106_three_issuer_margin_reversion_shadow.json"
CODES=("2027","4771","6206")
DATE="2026-10-22"


def real(value, label):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError("INVALID_NUMERIC_"+label)
    return float(value)


def risk_balance(code, e):
    rows=e.get("balance_sheet_2026q2_m_ntd",{})
    if not rows:
        return None
    out={}
    for key, prev in (("inventory","inventory_2025q2"),("accounts_receivable","accounts_receivable_2025q2")):
        a,b=real(rows[key],key),real(rows[prev],prev)
        if a<=0 or b<=0:
            raise ValueError("NONPOSITIVE_BALANCE_SHEET_COMPONENT")
        out[key+"_yoy_pct"]=round(100*(a/b-1),2)
    if "noncurrent_pp_e" in rows:
        a,b=real(rows["noncurrent_pp_e"],"pp_e"),real(rows["noncurrent_pp_e_2025q2"],"pp_e_prev")
        out["noncurrent_ppe_yoy_pct"]=round(100*(a/b-1),2)
    if code=="2027":
        inv_q1=real(rows["inventory_2026q1"],"inventory_q1")
        out["inventory_qoq_pct"]=round(100*(rows["inventory"]/inv_q1-1),2)
    if "reported_Q2_revenue_yoy_pct" in rows:
        growth=real(rows["reported_Q2_revenue_yoy_pct"],"Q2_revenue_growth")
        out["reported_current_Q2_revenue_yoy_pct"]=growth
        out["receivable_growth_exceeds_Q2_revenue_growth"]=out["accounts_receivable_yoy_pct"]>growth
        out["PPE_yearly_growth_exceeds_40_pct"]=out.get("noncurrent_ppe_yoy_pct",0)>40
    out["accounting_original_filing_notes_verified"]=False
    return out


def prepare(evidence, rank, gate):
    if (evidence.get("schema")!="V8106_THREE_ISSUER_GM_REVERSION_INPUTS_V1"
         or evidence.get("research_asof")!="2026-10-24"
         or evidence.get("last_price_reference_date")!=DATE
         or set(evidence.get("cases",{}))!=set(CODES)):
        raise ValueError("UNTRUSTED_COMPARATIVE_MARGIN_OBSERVATIONS")
    if (gate.get("asof_price_date")!=DATE or gate.get("model")!="V8.10.5"
        or gate.get("formally_certified_Aplus_in_report")!=0
        or rank.get("formal_Aplus_added")!=0):
        raise ValueError("MODEL_PRICE_OR_A_PLUS_VINTAGE_MISMATCH")
    by={x["code"]:x for x in rank["top10_evidence_first"]}
    formal={x["code"]:x for x in gate["issuer_diagnostics"]}
    out={}
    for code in CODES:
        if code not in by or code not in formal:
            raise ValueError("TARGET_ISSUER_NOT_IN_RECONCILED_SOURCE_POOL")
        model=by[code]
        original=evidence["cases"][code]
        if original.get("issuer")!=model.get("name"):
            raise ValueError("ISSUER_MISMATCH")
        if (model.get("original_current_numeric_reconciled") is not True
             or model.get("all_eight_quarters_and_notes_verified") is not False
             or model.get("formal_Aplus") is not False
             or len(formal[code].get("still_pending_gates",[]))!=13):
            raise ValueError("UNCERTIFIED_FINANCIAL_OR_13_GATES_PROMOTED")
        gm2025=real(original["observation_2025q2"]["gm_pct"],"gm2025")
        gm2026=real(original["observation_2026q2"]["gm_pct"],"gm2026")
        recent=real(model["latest_standalone_quarter_gm_pct"],"current_company_gm")
        if abs(gm2026-recent)>.10:
            raise ValueError("MOST_RECENT_ORIGINAL_GM_DIFFERS_FROM_MODELED_QUARTER")
        for y in ("observation_2025q2","observation_2026q2"):
            d=original[y]
            if d.get("source_original_pdf_verified") is not False or not str(d.get("release_url","")).startswith("https://"):
                raise ValueError("ORIGINAL_REPORT_CERTIFICATION_MISSTATED")
        release=original["observation_2026q2"]
        reported=100*real(release["gross_profit_k"],"current_gp")/real(release["revenue_k"],"current_sales")
        if abs(reported-gm2026)>.10:
            raise ValueError("PUBLIC_QUARTER_INCOME_STATEMENT_ARITHMETIC_MISMATCH")
        sens=model["recent_quarter_gm_flat_2027_sensitivity"]
        if sens.get("status")!="MECHANICAL_2027_LAST_STANDALONE_GM_FLAT_ONLY" or sens.get("no_issuer_original_notes_signoff") is not True:
            raise ValueError("EPS_GM_SENSITIVITY_NOT_SOURCE_ISOLATED")
        base_eps=real(model["base_eps"],"baseeps")
        base_gm=real(sens["base_gross_margin_pct"],"basegm")
        pe=real(model["base_target_price"],"target")/base_eps
        price=real(model["reference_close"],"price")
        slope=(real(sens["eps_change_from_base"],"eps_change")/
               real(sens["difference_from_base_gm_pp"],"margin_diff"))
        if not .02<slope<5:
            raise ValueError("UNSUPPORTED_GM_EPS_STEP")
        if abs(sens["latest_standalone_gross_margin_pct"]-recent)>.05:
            raise ValueError("GROSS_MARGIN_SENSITIVITY_REFERENCES_DIFFERENT_QUARTER")
        verify_eps=base_eps+(recent-base_gm)*slope
        if abs(verify_eps-sens["scenario_eps"])>.001:
            raise ValueError("MARGINAL_GM_EPS_INTERNAL_CROSSCHECK_FAILED")

        gms=[
          ("MODELED_2027_BASE_MARGIN",base_gm),
          ("HISTORIC_2025_Q2_MARGIN_NOT_2027_FORECAST",gm2025),
          ("ACTUAL_2026_Q2_MARGIN_NOT_2027_FORECAST",gm2026),
          ("MODELED_BASE_LESS_3_PERCENTAGE_POINTS",base_gm-3),
          ("MODELED_BASE_LESS_5_PERCENTAGE_POINTS",base_gm-5),
        ]
        if "observation_2025h1" in original:
            gms.append(("HISTORIC_2025_H1_MARGIN_NOT_2027_FORECAST",
                        real(original["observation_2025h1"]["gm_pct"],"2025h1_gm")))
        scenarios=[]
        for label,gm in gms:
            eps=base_eps+(gm-base_gm)*slope
            if eps<=0:
                price_value=None
                upside=None
            else:
                price_value=eps*pe
                upside=100*(price_value/price-1)
            scenarios.append({
               "scenario":label,
               "substituted_full_2027_GM_pct_not_forecast":round(gm,4),
               "hypothetical_2027_eps":round(eps,4),
               "hypothetical_fair_price_at_original_PE":round(price_value,2) if price_value is not None else None,
               "hypothetical_upside_at_original_PE_pct":round(upside,2) if upside is not None else None,
               "hypothetical_fair_price_at_PE_20pct_discount":round(price_value*.8,2) if price_value is not None else None,
               "hypothetical_upside_at_PE_20pct_discount_pct":round(100*(price_value*.8/price-1),2) if price_value is not None else None,
               "issuer_2027_margin_forecast_certified":False
            })
        threshold=price*1.30/pe
        margin_needed=base_gm+(threshold-base_eps)/slope
        cash=original.get("cashflow_residual_review",{})
        normalized_ytd_ocf=real(cash.get("normalized_2026h1_ocf_k"),"ytd_ocf")
        official_obs=model["operating_cashflow_quarter_bridge"]
        if abs(normalized_ytd_ocf-real(official_obs.get("latest_ytd_ocf_k"),"source_ocf"))>1:
            raise ValueError("QUARTER_YTD_OCF_NOT_RECONCILED_WITH_SOURCE")
        out[code]={
         "company":original["issuer"],"sector":original["group"],
         "price_reference_date":DATE,"reference_close":price,
         "2027_base_eps_unverified":round(base_eps,4),
         "2027_base_pe_unverified":round(pe,4),
         "2027_base_gross_margin_pct_unverified":round(base_gm,4),
         "actual_2025q2_margin_pct_from_dated_public_reprint":gm2025,
         "actual_2026q2_margin_pct_from_dated_public_release":gm2026,
         "margin_change_q2_yoy_pp":round(gm2026-gm2025,2),
         "sensitivity_2027_EPS_per_1pp_gm_fixed_other_inputs":round(slope,4),
         "gm_2027_required_for_30pct_upside_with_existing_PE_pct":round(margin_needed,4),
         "tested_margin_scenarios":scenarios,
         "latest_halfyear_ocf_k_normalized_not_filing_original":normalized_ytd_ocf,
         "working_capital_component_original_notes_certified":False,
         "ocf_sustainability_verified":False,
         "balance_sheet_risk_metrics":risk_balance(code,original),
         "missing_original_issuer_quarter_filing_source_sha":True,
         "negative_operating_cashflow_is_not_automatic_Aplus_failure":True,
         "formal_Aplus_or_buy_signal":False,
         "actual_2027_outcome_vs_0050":None,
        }
    return {
      "schema":"V8106_THREE_ISSUER_2027_GM_REVERSION_STRESS_SHADOW_V1",
      "reference_price_date":DATE,
      "evaluated_issuers":list(CODES),
      "company_data_sources_include_secondhand_reprints":True,
      "official_original_filing_bytes_fully_audited":False,
      "historical_PIT_2026Q2_receipts_fully_audited":False,
      "all_13_formal_quality_gates_completed":False,
      "model_2027_base_eps_or_PE_overwritten":False,
      "full_independent_reestimation_of_operating_bridge":False,
      "return_probabilities_calibrated":False,
      "realized_2027_return_vs_0050":None,
      "formal_Aplus_additions":0,"orders_placed":0,
      "source_references":{
         code:{"2025q2_dated_release":original["observation_2025q2"]["release_url"],
               "2026q2_dated_release":original["observation_2026q2"]["release_url"],
               "original_full_issuer_filings_and_PIT_attested":False}
         for code,original in evidence["cases"].items()
      },
      "issuers":out,
    }


def main():
    rank=json.loads(PRIORITY.read_bytes())
    gates=json.loads(GATE.read_bytes())
    evidence=json.loads(EVIDENCE.read_bytes())
    result=prepare(evidence,rank,gates)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({code:{
        "2027_Base_GM":r["2027_base_gross_margin_pct_unverified"],
        "2025_Q2_GM":r["actual_2025q2_margin_pct_from_dated_public_reprint"],
        "2025_Q2_GM_as_2027_upside":next(z["hypothetical_upside_at_original_PE_pct"] for z in r["tested_margin_scenarios"] if z["scenario"]=="HISTORIC_2025_Q2_MARGIN_NOT_2027_FORECAST"),
        "2025_Q2_GM_and_PE_minus20_upside":next(z["hypothetical_upside_at_PE_20pct_discount_pct"] for z in r["tested_margin_scenarios"] if z["scenario"]=="HISTORIC_2025_Q2_MARGIN_NOT_2027_FORECAST"),
        "OCF_h1_k":r["latest_halfyear_ocf_k_normalized_not_filing_original"],
     } for code,r in result["issuers"].items()},ensure_ascii=False))


if __name__=="__main__":
    main()
