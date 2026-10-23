#!/usr/bin/env python3
"""V8.10.6: evidence-first 2027 cross-sector valuation prechecks.

This intentionally does not treat an independent model's provisional Base
upside as a measured expected return. Stage-2 is *review priority only*.
Does not run orders, promote A+, change main valuation or assume all Taiwan
issuers have full 13-gate certification. Required vintage and prices must match.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path("tw-market-data")
PRIORITY = ROOT / "rankings/latest_evidence_priority.json"
GATE = ROOT / "rankings/v891_gate_progress.json"
TOP20 = ROOT / "rankings/v892_top20_quality_audit.json"
REPORT = ROOT / "rankings/v8106_cross_sector_evidence_first_shadow.json"
EVENTS = ROOT / "evidence/v8106_cross_sector_public_events_20261024.json"
MARGIN_STRESS = ROOT / "rankings/v8106_three_issuer_margin_reversion_shadow.json"
REQUIRED_DATE = "2026-10-22"

WARNING_RULES = (
    ("LATEST_MONTH_REVENUE_FELL_AT_LEAST_10PCT_YOY_WHILE_YTD_POSITIVE","LATEST_MONTH_SALES_REVERSAL"),
    ("NEGATIVE_OCF_REQUIRES_WORKING_CAPITAL_BRIDGE_NOT_AUTOMATIC_FAIL","UNRESOLVED_NEGATIVE_OPERATING_CASHFLOW"),
    ("LATEST_STANDALONE_QUARTER_GM_FELL_GE3PP_QOQ","SHARP_RECENT_GM_DECLINE"),
    ("2027_BASE_GM_GE3PP_ABOVE_LATEST_STANDALONE_QUARTER","2027_GM_ASSUMPTION_GE3PP_HIGHER_THAN_LATEST"),
    ("ISSUER_ORIGINAL_QUALIFIED_AUDITOR_CONCLUSION_SUBSIDIARIES_UNREVIEWED","AUDITOR_SUBSIDIARY_SCOPE_REVIEW"),
    ("REPORTED_YTD_NONOPERATING_GAP_GE20PCT_PRETAX_COMPONENTS_UNCERTIFIED","MATERIAL_UNRESOLVED_NONOPERATING"),
    ("2027_EPS_GE30PCT_ABOVE_UNSEASONALIZED_CURRENT_YTD_RUN_RATE","2027_EPS_STEPUP_NEEDS_BRIDGE"),
    ("EPS_YTD_RUN_RATE_BELOW_0_5_RATIO_DENOMINATOR_FRAGILE","LOW_EPS_DENOMINATOR_UNSTABLE"),
)
EXTRA_SEVERE = set(x for x,_ in WARNING_RULES)
CAUTION_LANE = "CHECK_FINANCIAL_AND_REVENUE_ORIGINALS_BEFORE_ANY_RISK_DECISION"
SOURCE_FIRST_LANE = "SOURCE_RECONCILED_NEXT_EARNINGS_QUALITY_REVIEW"
UNVERIFIED_LANE = "HIGH_UPSIDE_BULK_SOURCE_UNVERIFIED_NOT_BUY"


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("INVALID_FINITE_"+label)
    return float(value)


def build(primary, official_gate, broad, material_events=None, industry_stress=None):
    if industry_stress is None:
        industry_stress=json.loads(MARGIN_STRESS.read_bytes())
    if (industry_stress.get("schema")!="V8106_THREE_ISSUER_2027_GM_REVERSION_STRESS_SHADOW_V1"
            or industry_stress.get("reference_price_date")!=REQUIRED_DATE
            or industry_stress.get("formal_Aplus_additions")!=0
            or industry_stress.get("official_original_filing_bytes_fully_audited") is not False
            or set(industry_stress.get("issuers",{}))!={"2027","4771","6206"}):
        raise ValueError("MISSING_UNCERTIFIED_THREE_ISSUER_CYCLICAL_MARGIN_SOURCE")
    stress_by_code=industry_stress["issuers"]
    if material_events is None:
        material_events=json.loads(EVENTS.read_bytes())
    if (material_events.get("schema")!="V8106_PUBLIC_COMPANY_MATERIAL_EVENT_RESEARCH_LEDGER_V1"
            or material_events.get("research_cutoff")!="2026-10-24"):
        raise ValueError("MISSING_DATED_PUBLIC_MATERIAL_EVENT_REGISTRY")
    ev_by_code={}
    for event in material_events.get("events",[]):
        key=event.get("code")
        if key in ev_by_code or key is None:
            raise ValueError("DUPLICATE_OR_UNIDENTIFIED_MATERIAL_EVENT")
        date=event.get("event_date")
        if not isinstance(date,str) or date>REQUIRED_DATE:
            raise ValueError("FUTURE_OR_UNDEFINED_PUBLIC_EVENT")
        if (not str(event.get("source_url","")).startswith("https://news.cnyes.com/news/")
                or event.get("source_type")!="DATED_REPUBLICATION_OF_COMPANY_MATERIAL_DISCLOSURE"
                or event.get("official_company_original_bytes_sha256") is not None
                or event.get("original_company_first_available_timestamp_verified") is not False
                or event.get("legal_liability_or_official_penalty_determined") is not False):
            raise ValueError("MATERIAL_EVENT_SOURCE_OR_LEGAL_STATUS_MISREPRESENTED")
        if event.get("remove_from_clean_risk_lane") is not True:
            raise ValueError("MATERIAL_EVENT_MUST_BLOCK_CLEAN_LANE")
        ev_by_code[key]=event
    # This frozen 2026-10-24 research snapshot may not silently drop a
    # known 2026-10-06 material disclosure just because numerics look healthy.
    if ev_by_code.get("3130",{}).get("event_id")!="3130_CYBER_RESUME_DISCLOSURE_20261006":
        raise ValueError("MISSING_KNOWN_3130_CYBER_RISK_EVENT")
    if (primary.get("schema") != "EVIDENCE_FIRST_RESEARCH_QUEUE_V1"
            or primary.get("min_base_upside_pct") != 25
            or primary.get("realized_return_accuracy_calibrated") is not False
            or primary.get("formal_Aplus_added") != 0):
        raise ValueError("INVALID_EVIDENCE_FIRST_SOURCE_POLICY")
    if (official_gate.get("model") != "V8.10.5"
            or official_gate.get("asof_price_date") != REQUIRED_DATE
            or official_gate.get("formally_certified_Aplus_in_report") != 0):
        raise ValueError("GATE_VINTAGE_OR_FORMAL_GRADE_MISMATCH")
    if (broad.get("model") != official_gate.get("model")
            or broad.get("asof_price_date") != REQUIRED_DATE
            or broad.get("formal_Aplus_from_source") != 0):
        raise ValueError("BROAD_UNIVERSE_PRICE_DATE_MISMATCH")
    if official_gate.get("model_evaluated_issuer_count",0) < 1 or official_gate.get("not_evaluated_issuer_count",0)<0:
        raise ValueError("MODEL_COVERAGE_INVALID")
    priority_rows=primary.get("top10_evidence_first")
    if not isinstance(priority_rows,list) or len(priority_rows)!=10:
        raise ValueError("MISSING_EVIDENCE_FIRST_TOP10")
    gate_rows={r["code"]:r for r in official_gate["issuer_diagnostics"]}
    picked=set()
    rows=[]
    for i,item in enumerate(priority_rows):
        code=item.get("code")
        if not isinstance(code,str) or not(code.isdigit() and len(code)==4) or code in picked:
            raise ValueError("DUPLICATE_OR_INVALID_PRIORITY_ISSUER")
        picked.add(code)
        if item.get("original_current_numeric_reconciled") is not True:
            raise ValueError("CURRENT_ISSUER_SOURCE_UNVERIFIED")
        if item.get("all_eight_quarters_and_notes_verified") is not False:
            raise ValueError("MISLABELED_FULL_EIGHT_QUARTER_CERTIFICATION")
        if item.get("formal_Aplus") is not False or item.get("recommendation_blocked") is not False:
            raise ValueError("FORMAL_GRADE_OR_GOVERNANCE_CONFLICT")
        if item.get("pending_offering") is not False or item.get("cb_terms_or_shares_unresolved") is not False:
            raise ValueError("EQUITY_OFFERING_OR_CB_UNRESOLVED")
        if item.get("review_rank")!=i+1:
            raise ValueError("UNEXPECTED_SOURCE_RANK")
        price=_number(item.get("reference_close"),"reference_close")
        upside=_number(item.get("base_upside_pct"),"base_upside_pct")
        target=_number(item.get("base_target_price"),"base_target_price")
        eps=_number(item.get("base_eps"),"base_eps")
        stress=_number(item.get("eps_pe_each_minus20_upside_pct"),"stress20_upside")
        if price<=0 or eps<=0 or target<=0 or abs(100*(target/price-1)-upside)>0.25:
            raise ValueError("UPSIDE_EPS_PRICE_BRIDGE_NOT_RECONCILED")
        if code in gate_rows:
            gate=gate_rows[code]
            if gate.get("formal_Aplus") is not False or gate.get("formally_passed_gates")!=[]:
                raise ValueError("FORMAL_13_GATE_MISREPRESENTED")
            pending=gate.get("still_pending_gates",[])
            if len(pending)!=13:
                raise ValueError("NOT_ALL_13_GATE_SOURCE_ROWS_ACCOUNTED_FOR")
        else:
            # The formal top128 near-upside queue is a limited sample; lack of
            # a per-issuer row cannot be silently converted to a PASS.
            pending=item.get("pending_gates")
            if not isinstance(pending,list) or len(pending)!=13:
                raise ValueError("MISSING_ALTERNATE_FORMAL_GATE_STATUS")
        flags=item.get("warning_flags")
        if not isinstance(flags,list):
            raise ValueError("MISSING_DIAGNOSTIC_FLAGS")
        severe=[label for source,label in WARNING_RULES if source in flags]
        negative_ytd = item.get("operating_cashflow_quarter_bridge",{}).get("h1_or_current_ytd_ocf_still_negative")
        if negative_ytd is not False and negative_ytd is not True:
            raise ValueError("OPERATING_CASH_FLOW_FLAG_MISSING")
        if negative_ytd and "UNRESOLVED_NEGATIVE_OPERATING_CASHFLOW" not in severe:
            severe.append("NEGATIVE_YTD_OCF_UNRESOLVED")
        material_event=ev_by_code.get(code)
        if material_event is not None:
            severe.append(material_event["research_risk_flag"])
        issuer_stress=stress_by_code.get(code)
        stress_observations=[]
        if issuer_stress is not None:
            if (issuer_stress.get("company")!=item["name"]
                or abs(issuer_stress["reference_close"]-price)>.01
                or abs(issuer_stress["2027_base_eps_unverified"]-eps)>.01
                or issuer_stress.get("formal_Aplus_or_buy_signal") is not False):
                raise ValueError("CYCLICAL_STRESS_ISSUER_DATE_OR_EPS_INCONSISTENT")
            older=next((z for z in issuer_stress["tested_margin_scenarios"]
                        if z["scenario"]=="HISTORIC_2025_Q2_MARGIN_NOT_2027_FORECAST"),None)
            if older is None or older["hypothetical_upside_at_original_PE_pct"] is None:
                raise ValueError("MISSING_PRIOR_Q2_CYCLICAL_MARGIN_STRESS")
            old_upside=older["hypothetical_upside_at_original_PE_pct"]
            if (code=="2027" and upside-old_upside>=25):
                severe.append("STEEL_PRICE_CYCLE_GM_REVERSION_REMOVES_MOST_BASE_UPSIDE")
            balance=issuer_stress.get("balance_sheet_risk_metrics") or {}
            if balance.get("receivable_growth_exceeds_Q2_revenue_growth") is True:
                severe.append("RECEIVABLES_GROW_FASTER_THAN_SALES_REVIEW_COLLECTIONS")
            if balance.get("inventory_yoy_pct",0)>=80:
                severe.append("INVENTORY_YEARLY_GROWTH_GE80PCT_REVIEW_WORKING_CAPITAL")
            if balance.get("noncurrent_ppe_yoy_pct",0)>=40:
                severe.append("CAPEX_FIXED_ASSETS_YEARLY_GROWTH_GE40PCT_REVIEW")
            stress_observations=[
                "historical_2025Q2_margin_substitution_upside_pct="+str(old_upside),
                "all_historical_margin_stresses_are_not_2027_forecasts"
            ]
        phase= SOURCE_FIRST_LANE if not severe else CAUTION_LANE
        # Verified current quarter summaries are NOT full historical PIT, and
        # a vendor or source-calculated PE does not qualify as certified.
        risk20_pct=round(100*((target/price)*.8*.8-1),2)
        if abs(risk20_pct-stress)>1.0:
            raise ValueError("EPS_AND_PE_DOUBLE20_STRESS_MISMATCH")
        rows.append({
            "research_code":code,"company":item["name"],"market":item["market"],
            "source_rank":i+1,"reference_close":price,
            "model_2027_base_eps_unverified":round(eps,4),
            "model_2027_base_pe_unverified":round(target/eps,2),
            "model_2027_base_fair_value_unverified":round(target,2),
            "model_base_upside_pct_unverified":round(upside,2),
            "model_eps_and_pe_both_minus20_upside_pct":round(stress,2),
            "bear_case_upside_pct_unverified":item.get("bear_upside_pct"),
            "margin_of_safety_30pct_mathematical_entry_ceiling":round(target/1.30,2),
            "passes_base_at_least_30pct_mathematical_hurdle":upside>=30,
            "passes_downside_stress_30pct_hurdle":stress>=30,
            "source_original_current_numeric_reconciled":True,
            "all_13_formal_quality_gates_PASSED":False,
            "formal_pending_gates":len(pending),
            "formal_Aplus":False,"research_quality_lane":phase,
            "high_risk_review_flags":severe,
            "additional_cyclical_margin_lookback_review":stress_observations,
            "dated_public_material_event_id":material_event["event_id"] if material_event else None,
            "dated_public_material_event_date":material_event["event_date"] if material_event else None,
            "material_event_original_company_mops_attested":False,
            "current_cashflow_ytd_negative":negative_ytd,
            "latest_month_revenue_yoy_pct":round(_number(item["latest_month_revenue_yoy_pct"],"monthly_revenue_yoy"),2),
            "gross_margin_flat_sensitivity_upside_pct":item.get("recent_quarter_gm_flat_2027_sensitivity",{}).get("scenario_price_upside_pct"),
            "eligible_for_one_stock_10m_concentration":False,
            "trade_action":"NO_BUY_SOURCE_QUALITY_AND_OOS_PENDING",
        })
    # A stress pass on a bulk source is NOT equal to being source certified.
    broad_rows=[]
    for b in broad["issuer_ranked"]:
        if b.get("code") in picked:
            continue
        if len(broad_rows)>=10:
            break
        base=_number(b.get("base_2027_upside_pct"),"bulk_base_upside")
        if base<30:
            continue
        raw=b.get("analysis",{})
        broad_rows.append({
            "code":b["code"],"name":b["name"],
            "price":b["reference_close"],
            "model_base_upside_pct":base,
            "double20_eps_and_pe_upside_pct":b["stress_double20_upside_pct"],
            "cash_conversion_percent_of_net_income":raw.get("operating_cashflow_to_total_net_income_pct"),
            "unverified_flags":raw.get("flags",[])[:5],
            "source_lane":UNVERIFIED_LANE,
            "formal_Aplus":False,
        })
    base_ge30=sum(row["passes_base_at_least_30pct_mathematical_hurdle"] for row in rows)
    stress_ge30=sum(row["passes_downside_stress_30pct_hurdle"] for row in rows)
    watch=sorted(rows,key=lambda row:(
        row["research_quality_lane"]!=SOURCE_FIRST_LANE,
        -row["model_base_upside_pct_unverified"]))
    return {
      "schema":"V8106_CROSS_SECTOR_SOURCE_FIRST_RISK_FILTER_V1",
      "reference_date":REQUIRED_DATE,
      "model_version":official_gate["model"],
      "frozen_model_vintage":official_gate["estimate_vintage"],
      "tracked_issuers":official_gate["tracked_issuer_count"],
      "evaluated_issuers":official_gate["model_evaluated_issuer_count"],
      "unverified_remaining_issuers":official_gate["not_evaluated_issuer_count"],
      "provisional_2027_upside_ge30_count_in_evaluated_pool":official_gate["high_upside_research_candidates"],
      "formally_certified_Aplus_count":0,
      "observed_real_out_of_sample_win_rate_vs_0050":None,
      "stress_rule":"BOTH_FORWARD_EPS_AND_PE_MINUS20_PERCENT_ONE_AT_A_TIME_ADJUSTED_MULTIPLICATIVELY",
      "stress_upside_ge30_in_original_current_reconciled_top10_count":stress_ge30,
      "base_upside_ge30_in_original_current_reconciled_top10_count":base_ge30,
      "source_reconciled_top10_without_identified_earnings_cycle_cashflow_or_governance_flags_count":sum(not row["high_risk_review_flags"] for row in rows),
      "all_top10_formal_13_gates_still_pending":all(row["formal_pending_gates"]==13 for row in rows),
      "research_candidates_source_order":rows,
      "known_public_material_events_included":len(ev_by_code),
      "newly_joined_margin_cashflow_issuer_count":len(stress_by_code),
      "new_historical_margin_stress_requires_manual_review":True,
      "known_3130_cyber_event_research_risk_review":True,
      "safer_evidence_review_order_NOT_A_BUY_RANKING":watch,
      "high_upside_but_originals_unverified_examples":broad_rows,
      "limitations":[
        "Source-normalized current quarterly numerics do not certify all 8 original statements or footnotes.",
        "Cash-flow quality/receivables/inventory/capex bridges, dilution, management and issuer PIT remain incomplete.",
        "Downside PE and EPS stress is not a scenario probability, confidence interval, or realized drawdown.",
        "No stock here is a formal A+ or authorized for 10m NT$ single-stock concentration.",
        "Some top broad-universe names are absent from source-reconciled subset; do not call ranking comprehensive.",
        "Dividends, splits, next open fills, fees and matched 0050 total returns have not been validated."
      ],
      "orders_placed":0,"model_changed":False,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--out",type=Path,default=REPORT)
    a=parser.parse_args()
    j=build(json.loads((a.root/"rankings/latest_evidence_priority.json").read_bytes()),
            json.loads((a.root/"rankings/v891_gate_progress.json").read_bytes()),
            json.loads((a.root/"rankings/v892_top20_quality_audit.json").read_bytes()),
            json.loads((a.root/"evidence/v8106_cross_sector_public_events_20261024.json").read_bytes()),
            json.loads((a.root/"rankings/v8106_three_issuer_margin_reversion_shadow.json").read_bytes()))
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(j,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({
        "date":j["reference_date"],
        "evaluated":j["evaluated_issuers"],
        "plus30":j["provisional_2027_upside_ge30_count_in_evaluated_pool"],
        "Aplus":j["formally_certified_Aplus_count"],
        "double_stress_30pct_count":j["stress_upside_ge30_in_original_current_reconciled_top10_count"],
        "risk_screen_watch":[x["research_code"] for x in j["safer_evidence_review_order_NOT_A_BUY_RANKING"][:5]]},ensure_ascii=False))


if __name__=="__main__":
    main()
