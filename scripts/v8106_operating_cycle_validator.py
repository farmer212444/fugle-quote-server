#!/usr/bin/env python3
"""Reconcile 4771/6206 Q2 turnover-day trends and source-normalized statements.

Do not infer deteriorating customer collection solely from rising A/R balances.
Published Q2 DSO/DIO/DPO may use *different methods* between a company's deck
and vendor-calculated ratios. Never pool the levels across methods.

These are research facts as observed on 2026-10-24, NOT first-seen original
filing PIT, trade/Exit flags, collateralization, bad debt, inventory write-offs.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT=Path("tw-market-data")
INPUT=ROOT/"evidence/v8106_4771_6206_operating_cycle_20261024.json"
MARGINS=ROOT/"evidence/v8106_cross_sector_gm_source_observations_20261024.json"
OUT=ROOT/"rankings/v8106_4771_6206_turnover_cycle_shadow.json"
CODES=("4771","6206")
QUARTERS=("2025q2","2026q1","2026q2")


def finite(value,name):
    if type(value) not in (float,int) or not math.isfinite(value):
        raise ValueError("INVALID_FINITE_"+name)
    return float(value)


def percent(now,old):
    return 100*(now/old-1)


def rounded_summaries(src):
    metrics={}
    for k in ("dso","dio","dpo","ccc"):
        vals={q:src.get(k+"_"+q) for q in QUARTERS}
        if any(v is None for v in vals.values()):
            if k=="dpo" and src.get("source_id")=="6206_company_deck_transcription":
                metrics[k]=None
                continue
            if k=="ccc":
                if all(v is None for v in vals.values()):
                    vals={q:src["dso_"+q]+src["dio_"+q]-src["dpo_"+q] for q in QUARTERS if src.get("dpo_"+q) is not None}
                    if len(vals)!=3:
                        metrics[k]=None
                        continue
                else:
                    raise ValueError("PARTIAL_PUBLISHED_CCC_INVALID")
            else:
                raise ValueError("MISSING_DAYS_METRIC_"+k)
        for quarter,value in vals.items():
            if not 0<finite(value,k+quarter)<500:
                raise ValueError("INVALID_DAYS_METRIC_"+k)
        if k=="ccc" and src.get("ccc_2025q2") is not None:
            for q in QUARTERS:
                if abs(vals[q]-(src["dso_"+q]+src["dio_"+q]-src["dpo_"+q]))>.02:
                    raise ValueError("REPORTED_CCC_ARITHMETIC_DISAGREES_WITH_COMPONENTS")
        metrics[k]={
            "days_2025q2":round(vals["2025q2"],2),
            "days_2026q1":round(vals["2026q1"],2),
            "days_2026q2":round(vals["2026q2"],2),
            "yoy_days":round(vals["2026q2"]-vals["2025q2"],2),
            "qoq_days":round(vals["2026q2"]-vals["2026q1"],2),
        }
    return metrics


def evaluate(data,margins):
    if (data.get("schema")!="V8106_4771_6206_Q2_OPERATING_CYCLE_RECONCILIATION_INPUT_V1"
            or data.get("research_asof")!="2026-10-24"
            or data.get("observation_end")!="2026-06-30"
            or set(data.get("issuers",{}))!=set(CODES)
            or margins.get("schema")!="V8106_THREE_ISSUER_GM_REVERSION_INPUTS_V1"):
        raise ValueError("WRONG_SOURCE_VINTAGE_OR_UNIVERSE")
    out={}
    for code in CODES:
        issuer=data["issuers"][code]
        name=issuer["name"]
        reference=margins["cases"][code]
        if name!=reference["issuer"]:
            raise ValueError("ISSUER_NAME_DIFFERENT_FROM_PREVIOUS_SOURCE")
        if (issuer.get("sales_source") is None or
             not issuer["sales_source"].startswith("https://") or
             issuer.get("sources") is None):
            raise ValueError("MISSING_DATED_PUBLIC_SOURCE_LINK")
        revenue_2025=finite(issuer["sales_2025q2_k"],"revenue25")
        revenue_2026=finite(issuer["sales_2026q2_k"],"revenue26")
        cogs_2025=finite(issuer["cogs_2025q2_k"],"cogs25")
        cogs_2026=finite(issuer["cogs_2026q2_k"],"cogs26")
        if not 0<cogs_2025<revenue_2025 or not 0<cogs_2026<revenue_2026:
            raise ValueError("INVALID_COGS_OR_REVENUE")
        if abs(revenue_2026-reference["observation_2026q2"]["revenue_k"]) > 600:
            raise ValueError("Q2_REVENUE_NOT_SAME_AS_PREVIOUS_MARGIN_SOURCE")
        if abs(100*(revenue_2026-cogs_2026)/revenue_2026-
               reference["observation_2026q2"]["gm_pct"])>.13:
            raise ValueError("GROSS_MARGIN_MISMATCH_WITH_ORIGINAL_FINANCIAL_SOURCE")
        ar25=finite(issuer["ar_2025q2_m"],"ar25")
        ar26=finite(issuer["ar_2026q2_m"],"ar26")
        inventory25=finite(issuer["inventory_2025q2_m"],"inventory25")
        inventory26=finite(issuer["inventory_2026q2_m"],"inventory26")
        if min(ar25,ar26,inventory25,inventory26)<=0:
            raise ValueError("NONPOSITIVE_RECEIVABLES_INVENTORY")
        revenue_growth=percent(revenue_2026,revenue_2025)
        cost_growth=percent(cogs_2026,cogs_2025)
        receivable_growth=percent(ar26,ar25)
        inventory_growth=percent(inventory26,inventory25)
        if abs(ar26-reference["balance_sheet_2026q2_m_ntd"]["accounts_receivable"])>.01:
            raise ValueError("A_R_IS_NOT_PRIOR_ARCHIVED_DATA")
        if abs(inventory26-reference["balance_sheet_2026q2_m_ntd"]["inventory"])>.01:
            raise ValueError("INVENTORY_NOT_PRIOR_ARCHIVED_DATA")
        if abs(issuer["normalized_2026h1_ocf_k"]-
               reference["cashflow_residual_review"]["normalized_2026h1_ocf_k"])>1:
            raise ValueError("OCF_NOT_MATCHING_PRIOR_NORMALIZED_SOURCE")
        sources={}
        for s in issuer["sources"]:
            sid=s["source_id"]
            if sid in sources:
                raise ValueError("DUPLICATE_RATIO_SOURCE_ID")
            if (not s["url"].startswith("https://")
                    or s["kind"] not in ("SECONDARY_TRANSCRIPTION_OF_ISSUER_PRESENTATION",
                                        "SECONDARY_FINANCIAL_RATIO_CALCULATION")
                    or s["issuer_original_document_sha256"] is not None
                    or s["original_document_ever_archived"] is not False):
                raise ValueError("FALSE_ORIGINAL_PDF_ARCHIVE_OR_BAD_RATIO_SOURCE")
            sources[sid]={"source_url":s["url"],"source_kind":s["kind"],
                          "method":s["method"],"metrics":rounded_summaries(s),
                          "exact_days_comparable_across_sources":False}
        if len(sources)!=(2 if code=="4771" else 1):
            raise ValueError("INSUFFICIENT_PUBLISHED_TURNOVER_METHODOLOGIES")
        if code=="4771":
            method1=sources["4771_company_deck_transcription"]["metrics"]
            method2=sources["4771_financial_ratio_vendor"]["metrics"]
            # Never treat a vendor's 76.69 days as the slide's 80 days.
            if abs(method1["dso"]["days_2026q2"]-method2["dso"]["days_2026q2"])<2:
                raise ValueError("EXPECTED_DIFFERENT_METHODS_NOT_PRESERVED")
            for measure in ("dso","ccc"):
                if not all(method[measure]["yoy_days"]>0 and method[measure]["qoq_days"]<0
                           for method in (method1,method2)):
                    raise ValueError("CROSS_METHOD_COLLECTION_CYCLE_DIRECTION_INCONSISTENT")
            if abs(method2["dio"]["yoy_days"])>.5 or abs(method1["dio"]["yoy_days"])>1:
                raise ValueError("INVENTORY_DAYS_NOT_HISTORICALLY_FLAT")
            status="AR_COLLECTION_LONGER_YOY_BUT_IMPROVING_QOQ_TWO_METHODS"
            flags=["4771_DSO_LONGER_YOY_BUT_QOQ_BETTER",
                   "4771_RECEIVABLES_GROW_FASTER_THAN_QUARTERLY_SALES",
                   "4771_DIO_APPROX_FLAT_NOT_INVENTORY_TURNOVER_COLLAPSE"]
            if not (receivable_growth>revenue_growth+5):
                raise ValueError("MISREAD_4771_YOY_AR_VS_REVENUE")
        else:
            report=sources["6206_company_deck_transcription"]["metrics"]
            dso=report["dso"]
            dio=report["dio"]
            if (dso["yoy_days"]>=0 or dio["yoy_days"]<=20
                    or not -5<=dio["qoq_days"]<=0):
                raise ValueError("FLYTECH_COLLECTION_OR_INVENTORY_TREND_INCONSISTENT")
            if not receivable_growth<revenue_growth:
                raise ValueError("FLYTECH_AR_GROWTH_EXCEEDS_SALES_CONTRARY_TO_DATA")
            if not (inventory_growth>cost_growth+20):
                raise ValueError("FLYTECH_INVENTORY_GROWTH_NOT_EXPANDING_RELATIVE_TO_COGS")
            if (issuer["normalized_2026h1_ocf_k"]>=0
                or issuer["normalized_2026q2_standalone_ocf_k"]<=0):
                raise ValueError("FLYTECH_H1_NEGATIVE_Q2_POSITIVE_CASH_STATUS_CONFLICT")
            status="DSO_YOY_FASTER_COLLECTION_BUT_DIO_YOY_SHARPLY_LONGER"
            flags=["6206_AR_BALANCE_GROWTH_DOES_NOT_MEAN_SLOWER_DSO",
                   "6206_DIO_PLUS34_DAYS_YOY_INVENTORY_VALIDATION",
                   "6206_Q2_DIO_QOQ_PARTIAL_RECOVERY",
                   "6206_H1_OCF_STILL_NEGATIVE_WITH_Q2_POSITIVE"]
        out[code]={
            "issuer":name,"observation_cutoff":"2026-06-30",
            "sales_2026q2_revenue_yoy_pct":round(revenue_growth,2),
            "q2_cogs_yoy_pct":round(cost_growth,2),
            "end_q2_accounts_receivable_yoy_pct":round(receivable_growth,2),
            "end_q2_inventory_yoy_pct":round(inventory_growth,2),
            "yoy_AR_grows_faster_than_quarter_revenue":receivable_growth>revenue_growth,
            "yoy_inventory_grows_faster_than_quarter_COGS":inventory_growth>cost_growth,
            "published_turnover_sources":sources,
            "cross_source_day_levels_not_directly_equal":code=="4771",
            "risk_phase":status,"research_operational_flags":flags,
            "cashflow_h1_k_normalized_unverified_original":issuer["normalized_2026h1_ocf_k"],
            "original_accounts_aging_and_inventory_writeoff_notes_verified":False,
            "bad_debt_loss_or_inventory_impairment_concluded":False,
            "issuer_original_annual_report_PIT_verified":False,
            "no_formal_Aplus_or_exit":True
        }
    return {
      "schema":"V8106_OPERATING_CYCLE_TWO_ISSUER_SHADOW_V1",
      "vintage_date":"2026-10-24","price_reference_date":"2026-10-22",
      "issuers":out,
      "primary_official_reports_full_original_sha_archived":False,
      "no_definitive_impairment_or_misconduct_claim":True,
      "formal_Aplus_count_changed":0,"orders_placed":0,
      "actual_one_year_total_return_vs_0050":None,
    }


def main():
    data=json.loads(INPUT.read_bytes())
    margins=json.loads(MARGINS.read_bytes())
    result=evaluate(data,margins)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({
        code:{"operational_readout":o["risk_phase"],
              "sales_yoy":o["sales_2026q2_revenue_yoy_pct"],
              "ar_yoy":o["end_q2_accounts_receivable_yoy_pct"],
              "cogs_yoy":o["q2_cogs_yoy_pct"],
              "inventory_yoy":o["end_q2_inventory_yoy_pct"]}
        for code,o in result["issuers"].items()},ensure_ascii=False))


if __name__=="__main__":
    main()
