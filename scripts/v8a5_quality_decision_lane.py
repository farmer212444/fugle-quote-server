#!/usr/bin/env python3
"""Separate Top20 mathematical 2027 upside from evidence-based decision readiness.

This is a conservative RESEARCH REVIEW QUEUE, not stock recommendations or
statistically calibrated probabilities. No modification to frozen Base EPS/PE,
existing ranks, 13 formal A+ gates, or automated trade decisions.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/"tw-market-data"
SHOCK_FLAGS=(
    "Q3_REVENUE_GROWTH_DECELERATED_AT_LEAST_20PP",
    "Q3_REVENUE_YOY_GROWTH_DECELERATED_OVER_20PP",
    "OPERATING_MARGIN_DECLINED_AT_LEAST_2PP",
    "NEGATIVE_OR_ZERO_H1_OCF_REQUIRES_WORKING_CAPITAL_BRIDGE",
    "NEGATIVE_YTD_OPERATING_CASHFLOW_CHECK_WORKING_CAPITAL",
    "LOW_OCF_RELATIVE_TO_TOTAL_NET_INCOME",
    "AUDITOR_QUALIFIED_SCOPE_MATERIALITY_PENDING",
    "AUDITOR_SCOPE_MATERIALITY_OPEN",
    "EQUITY_ISSUANCE_NOT_CONFIRMED",
)
SHARE_FLAGS=("CB_LEGAL_TERMS_UNVERIFIED","LISTED_CB_TERMS_UNVERIFIED","CASH_EQUITY_RAISE_STATUS_UNVERIFIED")
PE_FLAGS=("HIGH_FORWARD_PE_UNVERIFIED_PEERS","FORWARD_PE_AT_LEAST_20_REQUIRES_MATCHED_PEERS")
ORIGINAL_FLAG="ISSUER_ORIGINAL_NUMERICS_NOT_CROSSCHECKED"

def require(test,error):
    if not test:raise ValueError(error)

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def prepare(top,gate,price_manifest,focus=None,etf_overlay=None,*,main_update=None):
    """Check input vintages before sorting; never splice a stale snapshot."""
    asof=top.get("asof_price_date")
    require(asof and asof==gate.get("asof_price_date")==price_manifest.get("date"),
            "DECISION_LANE_VINTAGE_MISMATCH")
    require(isinstance(top.get("issuer_ranked"),list) and len(top["issuer_ranked"])>=10,
            "DECISION_LANE_TOP20_MISSING")
    require(top.get("automatically_certified_Aplus")==0,"DECISION_LANE_UNEXPECTED_NEW_CERTIFICATION_REVIEW")
    gate_index={x["code"]:x for x in gate.get("issuer_diagnostics",[])}
    require(len(gate_index)==len(gate.get("issuer_diagnostics",[])),
            "DECISION_LANE_DUPLICATE_GATE_ISSUER")
    etf_index={}
    if etf_overlay is not None:
        require(etf_overlay.get("schema")=="V8A6_ETF_INDEX_ROTATION_RESEARCH_WATCH"
                and etf_overlay.get("asof_price_date")==asof
                and etf_overlay.get("estimate_vintage")==top.get("estimate_vintage")
                and etf_overlay.get("formal_Aplus_created")==0
                and etf_overlay.get("base_ranking_and_2027_model_unchanged") is True,
                "ETF_OVERLAY_VINTAGE_OR_FORMAL_CERTIFICATE_INCONSISTENT")
        etf_index=etf_overlay.get("stocks",{})
        require(isinstance(etf_index,dict),"ETF_OVERLAY_STOCKS_INVALID")
    result=[]
    for r in top["issuer_ranked"]:
        code=r["code"]
        require(code in gate_index,"DECISION_LANE_ISSUER_GATE_MISSING_"+code)
        evidence=gate_index[code]
        require(not r.get("formal_Aplus") and not evidence.get("formal_Aplus"),
                "DECISION_LANE_FORMAL_A_PLUS_REQUIRES_SEPARATE_CERTIFICATE")
        critical=list(r.get("critical_evidence_gaps",[]))
        governance=r.get('governance_review') or {}
        governance_blocked=r.get('recommendation_blocked') is True or governance.get('blocks_recommendation') is True
        warnings=list(r.get("analysis",{}).get("flags",[]))
        bag=set(critical+warnings)
        operating=sorted(x for x in bag if x in SHOCK_FLAGS)
        dilution=sorted(x for x in bag if x in SHARE_FLAGS)
        valuation=sorted(x for x in bag if x in PE_FLAGS)
        original_verified=(r.get("source_tier")=="ORIGINAL_CURRENT_ISSUER_NUMERICS"
                           and ORIGINAL_FLAG not in bag)
        if operating or dilution or valuation:
            status="OPERATING_PE_OR_DILUTION_RED_FLAGS_REVIEW"
        elif not original_verified:
            status="BATCH_ONLY_ORIGINAL_FILING_REVIEW"
        else:
            status="CURRENT_NUMERICS_VERIFIED_OTHER_GATES_PENDING"
        constituent=etf_index.get(code,{})
        etf_convergent=constituent.get("three_way_convergence_observed") is True
        if etf_convergent:
            status="ETF_CHIP_EARNINGS_CONVERGENT_RISK_REVIEW"
        if governance_blocked:
            status='MAJOR_GOVERNANCE_REVIEW_BLOCK'
        stress=r.get("stress_double20_upside_pct")
        stress_survives=isinstance(stress,(int,float)) and not isinstance(stress,bool) and stress>=30
        formal_passed=evidence.get("formally_passed_gates",[])
        pending=evidence.get("still_pending_gates",[])
        require(len(formal_passed)+len(pending)+len(evidence.get("formally_failed_gates",[]))==13,
                "DECISION_LANE_INCOMPLETE_THIRTEEN_GATE_RECORD_"+code)
        result.append(dict(
            prior_base_rank=r["rank"],code=code,name=r.get("name"),price_date=asof,
            source_tier=r.get("source_tier"),original_current_numerics_checked=original_verified,
            base_2027_eps_scenario=r.get("base_2027_eps"),
            base_2027_pe_assumption=r.get("base_2027_pe"),
            base_target_price_scenario=r.get("base_2027_target"),
            base_upside_pct=r.get("base_2027_upside_pct"),
            q3_revenue_yoy_pct=r.get("q3_revenue_yoy_pct"),
            sensitivity_eps20_pe20_upside_pct=stress,
            sensitivity_survives_30pct_threshold=stress_survives,
            operating_evidence_gaps=operating,pe_evidence_gaps=valuation,
            capital_evidence_gaps=dilution,
            official_original_financial_review_needed=not original_verified,
            other_critical_gaps=sorted(bag-set(operating)-set(valuation)-set(dilution)),
            model_13_gate_passed_count=len(formal_passed),
            model_13_gate_pending_count=len(pending),
            model_13_gate_failed_count=len(evidence.get("formally_failed_gates",[])),
            quality_review_status=status,
            governance_review=governance,recommendation_blocked=governance_blocked,
            etf_constituent_research_context=(
                {k:constituent.get(k) for k in
                 ("research_review_status","event_history_count",
                  "live_archived_deletions_120d","three_way_convergence_observed")}
                if constituent else None),
            etf_warning_active=etf_convergent,
            ETF_history_is_not_evidence_of_manager_forecast_accuracy=True,
            high_confidence_buy_or_Aplus_certified=False))
    # Review order is an explicit heuristic, NOT an objective return ranking.
    priority={"MAJOR_GOVERNANCE_REVIEW_BLOCK":4,
              "ETF_CHIP_EARNINGS_CONVERGENT_RISK_REVIEW":3,
              "CURRENT_NUMERICS_VERIFIED_OTHER_GATES_PENDING":0,
              "BATCH_ONLY_ORIGINAL_FILING_REVIEW":1,
              "OPERATING_PE_OR_DILUTION_RED_FLAGS_REVIEW":2}
    for_review=sorted(result,key=lambda r:(
        priority[r["quality_review_status"]],
        -int(r["sensitivity_survives_30pct_threshold"]),
        -(r["sensitivity_eps20_pe20_upside_pct"] if isinstance(r["sensitivity_eps20_pe20_upside_pct"],(int,float)) else -1000),
        r["prior_base_rank"]))
    for i,x in enumerate(for_review,1):x["verification_priority_rank"]=i
    report=dict(schema="V8A5_QUALITY_DECISION_RESEARCH_SHADOW",
        asof_price_date=asof,estimate_vintage=top.get("estimate_vintage"),
        current_financial_period=top.get("financial_last_quarter"),
        top20_base_ranking_untouched=True,
        has_statistical_outperformance_calibration=False,
        uncertainty_from_not_yet_disclosed_Q3_profit_retained=True,
        full_market_certified_rank=False,
        formal_Aplus_added=0,
        etf_index_event_overlay_present=etf_overlay is not None,
        etf_overlay_is_not_a_fourteenth_gate=True,
        etf_origin_publication_PIT_and_backtest_not_certified=True,
        etf_focus_9802=(
            {k:etf_index["9802"].get(k) for k in
              ("deletes","adds","last_event","live_archived_deletions_120d",
               "research_review_status")}
            if "9802" in etf_index else None),
        issuer_count=len(result),
        verification_order=for_review,
        base_upside_order=result,
        governance_watch=top.get('governance_watch',[]),
        limits=[
            "Top20 research queue only; NOT 791-issuer formal quality rankings.",
            "Official current value mirroring does not mean original detailed notes or published PIT verified.",
            "Double20 stress assumes EPS and PE each minus20%; not a tail-loss probability or adjusted Base.",
            "Revenue deceleration is not proven earnings deceleration, and negative OCF can arise during expansion.",
            "CB terms and industry peer PE require dated original evidence; ranking never grants A+.",
            "ETF constituent index changes are not actual ETF fund orders, never automatically promote A+ or Exit; incomplete coverage is not zero ETF exposure.",
        ])
    if focus:
        report["9802_Q3_self_report"]=dict(period=focus.get("period"),
           status=focus.get("status"),disclosed_at=focus.get("disclosed_at"),
           eps=focus.get("q3_2026",{}).get("eps"),
           gross_margin_pct=round(100*focus["q3_2026"]["gross_profit"]/
                              focus["q3_2026"]["revenue"],2),
           official_full_quarter_notes_verified=False,
           impact_on_2027_base="UPDATED_FROM_RECONCILED_ORIGINAL_SELF_REPORT" if (main_update or {}).get('applied') else "NOT_AUTOMATICALLY_RESTATED",
           needs="Reconcile Q3 source and forward factory cost/GM bridge before relying on 2027 PE/EPS")
    return report

def markdown(report):
    fmt=lambda x:"待驗" if x is None else f"{x:+.1f}%"
    lines=["# V8.A5 2027報酬率與品質可信度分流（研究版）","",
        f"股票收盤基準：{report['asof_price_date']}；財報：{report['current_financial_period']}；正式新增A+：**0檔**。",
        "**第一軌是既有Base潛在漲幅；第二軌僅作證據查核優先序，不是買進信心或實證勝率排名。**",
        "","|查核順位|股票|原Base序|Base漲幅|EPS與PE各-20%|原始當期數字|主要障礙|狀態|",
        "|---:|---|---:|---:|---:|---|---|---|"]
    for x in report["verification_order"]:
        flags=(x["operating_evidence_gaps"]+x["capital_evidence_gaps"]+
               x["pe_evidence_gaps"]+x["other_critical_gaps"])
        brief="重大司法／治理事件待查，暫停推薦" if x.get('recommendation_blocked') else "、".join(flags[:2]) if flags else "完整附註與PIT待驗"
        lines.append(f"|{x['verification_priority_rank']}|{x['code']} {x['name']}|{x['prior_base_rank']}|"
                     f"{fmt(x['base_upside_pct'])}|{fmt(x['sensitivity_eps20_pe20_upside_pct'])}|"
                     f"{'已核數值' if x['original_current_numerics_checked'] else '待核原件'}|"
                     f"{brief}|{x['quality_review_status']}|")
    if report.get('governance_watch'):
        lines+=['','## 已登錄重大治理事件（包含未入榜公司）','']
        for item in report['governance_watch']:
            lines.append('- **'+item['code']+' '+(item.get('name') or '')+'：重大治理待查／暫停推薦。**')
        lines.append('已重開相關品質審查；起訴不等於定罪，沒有事件帳亦不代表全市場司法風險已排除。')
    if report.get("etf_focus_9802"):
        x=report["etf_focus_9802"]
        lines += ["", "## ETF成分股異動研究警示（9802）","",
            f"官方指數歷史：剔除{x['deletes']}次、納入{x['adds']}次；"
            f"最近120日有永久原件且符合提醒條件的剔除：{x['live_archived_deletions_120d']}次。",
            f"訊號：{x['research_review_status']}。2025歷史剔除不能充作今日的新撤退警示。",
            "未驗證ETF實際下單、全市場歷史成分股、真實PIT回測，僅作風險查核，不能調整Base或正式A+。"]
    lines+=["","## 適用限制","",
        "這是20檔研究估值的**查核排程**，未將任何股票認證為安全或可重押。",
        "Q3營收明顯減速／現金流缺口／CB條款及PE未核者顯示警戒，**不機械下修Base**，以免製造沒有事實支持的新版EPS。",
        "正式A+需要13項原始證據全數通過；目前全部個股仍列未完成。",
        "完整數值、核對原因、未簽核的13項情況見同名JSON。",""]
    if "9802_Q3_self_report" in report:
        x=report["9802_Q3_self_report"]
        lines+=["## 9802 特別提示（不在Top20）","",
            f"2026Q3自結未經查核 EPS {x['eps']}元、毛利率{x['gross_margin_pct']}%；此資訊已揭露，但2026Q3詳細附註與2027廠務成本橋接未完備。",
            "本次研究Base已依原始自結表重算；公司別2027營運橋接及完整季度認證仍待完成。" if x['impact_on_2027_base']=='UPDATED_FROM_RECONCILED_ORIGINAL_SELF_REPORT' else "過往2027 Base或條件式毛利復甦價不可視為已經受新Q3獲利校正。",""]
    return "\n".join(lines)+"\n"

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default=str(ROOT))
    args=p.parse_args()
    root=Path(args.data_dir)
    focuspath=root/"evidence/v880/issuer_reviews/9802_q3_20261020_self_report.json"
    focus=load_json(focuspath) if focuspath.exists() else None
    research=load_json(root/'rankings/latest_research.json')
    packed=(root/'rankings/v880_full_results.json.gz').read_bytes()
    require(hashlib.sha256(packed).hexdigest()==research['full_results']['sha256'],'DECISION_LANE_FULL_RESULTS_HASH_MISMATCH')
    full=json.loads(gzip.decompress(packed))
    require(full.get('estimate_vintage')==research['estimate_vintage'],'DECISION_LANE_MAIN_RESEARCH_VINTAGE_MISMATCH')
    main_update=next((r.get('fresh_earnings_update') for r in full.get('all_model_rows',[]) if r.get('code')=='9802'),None)
    etf_path=root/"rankings/v8a6_etf_rotation_watch.json"
    etf=load_json(etf_path) if etf_path.exists() else None
    result=prepare(load_json(root/"rankings/v892_top20_quality_audit.json"),
                   load_json(root/"rankings/v891_gate_progress.json"),
                   load_json(root/"prices/latest_manifest.json"),focus,etf_overlay=etf,main_update=main_update)
    (root/"rankings/v8a5_quality_decision_lane.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (root/"rankings/v8a5_quality_decision_lane.md").write_text(
        markdown(result),encoding="utf-8")
    print(json.dumps({"asof":result["asof_price_date"],
        "verified_formal_Aplus_added":0,"top20":result["issuer_count"],
        "priority":[x["code"] for x in result["verification_order"][:8]]},ensure_ascii=False))

if __name__=="__main__":main()
