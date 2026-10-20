#!/usr/bin/env python3
"""V8.9.0: fail-closed five-candidate earnings/cash/CB/stress research audit.

Reuses official-batch mirror reconciliation and archived model risk/shares audits.
These are screening facts, not original issuer-note, equity action, sector PE
or point-in-time certification. Never changes forecast EPS/PE, trading or A+.
"""
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.v887_top10_earnings_audit import (
    load, index_source, analyze, check_post_financial_quarter_revenue
)
DATA=Path("tw-market-data")
FOCUS=("8390","4739","5439","3305","5388")
SCENARIOS=(("base",1.0,1.0),("double10",.90,.90),("double20",.80,.80),
           ("double30",.70,.70))

def fail(condition,message):
    if not condition:raise ValueError(message)

def num(x,label):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x):
        raise ValueError("BAD_NUMERIC_"+label)
    return float(x)

def unique(items,code,kind):
    rows=[x for x in items if x.get("code")==code]
    fail(len(rows)==1,"MISSING_OR_DUPLICATE_"+kind+"_"+code)
    return rows[0]

def validate_vintage(research,documents):
    fail(bool(research.get("estimate_vintage")) and bool(research.get("asof_price_date")),
         "RESEARCH_VINTAGE_MISSING")
    fail(research.get("financial_last_quarter")=="2026-Q2","PERIOD_ROLLOVER_REQUIRES_NEW_FIVE_CANDIDATE_AUDIT")
    fail(research.get("revenue_month")=="2026-09","REVENUE_MONTH_NOT_YET_SUPPORTED")
    instant=dt.datetime.fromisoformat(research["estimate_vintage"])
    fail(instant.tzinfo is not None,"MODEL_CREATION_TIMESTAMP_UNZONED")
    for label,document in documents.items():
        fail(document.get("estimate_vintage")==research["estimate_vintage"],
             "VINTAGE_MISMATCH_"+label)
        fail(document.get("asof_price_date")==research["asof_price_date"],
             "PRICE_DATE_MISMATCH_"+label)
        fail(document.get("financial_last_quarter")==research["financial_last_quarter"],
             "FINANCIAL_PERIOD_MISMATCH_"+label)
        fail(document.get("formal_Aplus_count")==research["formal_Aplus_count"],
             "FORMAL_Aplus_COUNT_MISMATCH_"+label)
    return instant

def scenario_stress(base_eps,pe,close,shares,legal):
    eps=num(base_eps,"FORWARD_EPS")
    multiple=num(pe,"BASE_PE")
    price=num(close,"REFERENCE_CLOSE")
    denom=num(shares.get("base_shares"),"MODEL_SHARE_DENOMINATOR")
    fail(eps>0 and multiple>0 and price>0 and denom>0,"INVALID_VALUATION_INPUT")
    result={}
    for label,eps_w,pe_w in SCENARIOS:
        target=eps*eps_w*multiple*pe_w
        result[label]=dict(eps=round(eps*eps_w,3),
                           pe=round(multiple*pe_w,3),
                           target_price=round(target,2),
                           upside_pct=round(100*(target/price-1),2))
    extra=num(shares.get("conversion_price_down_10pct_full_conversion_shares"),"CB_STRESSED_SHARES")
    fail(extra>=denom,"MODEL_CB_STRESS_HAS_LESS_THAN_BASE_SHARES")
    # The model already includes reported outstanding CB in denominator. Extra is
    # ONLY the 10% conversion-price reset incremental shares, never all CB twice.
    reset_factor=denom/extra
    result["double10_plus_CB_reset_sensitivity"]=dict(
        additional_shares_over_baseline=round(extra-denom),
        dilution_from_additional_reset_pct=round(100*(1-reset_factor),2),
        target_price=round(result["double10"]["target_price"]*reset_factor,2),
        upside_pct=round(100*((eps*.9*multiple*.9*reset_factor)/price-1),2),
        current_legal_terms_verified=legal)
    return result

def equity_watch(review,issuer,forecast_eps,forecast_target,price,asof):
    """8390 8m/10m potential cash equity, no proceeds earnings, never effective assumption."""
    notes=[x for x in review.get("issuer_reviews",[]) if x.get("code")=="8390"]
    if len(notes)!=1:return dict(status="ISSUER_CORPORATE_ACTION_REVIEW_MISSING")
    item=notes[0].get("equity_issuance")
    if not isinstance(item,dict):return dict(status="EQUITY_ACTION_DETAIL_NOT_PROVIDED")
    scheduled=dt.date.fromisoformat(item["originally_scheduled_effective_date"])
    if asof>scheduled:
        return dict(status="SCHEDULED_EFFECTIVE_DATE_ELAPSED_REFRESH_OFFICIAL_STATUS",
            expected_effectiveness_date=scheduled.isoformat(),formal_certified=False)
    if item.get("issuance_completed") is not False or item.get("regulator_effectiveness_confirmed") is not False:
        return dict(status="CORPORATE_EVENT_CHANGED_REVALIDATE_MASTER",formal_certified=False)
    old=int(item["capital_master_shares_asof_2026_10_06"])
    outstanding=num(issuer.get("base_shares"),"8390_MODEL_SHARES")
    fail(abs(outstanding-old)<1,"8390_MODEL_SHARES_ALREADY_DIFFER_FROM_PREISSUE_REVIEW")
    amounts={"filed_8m_unconfirmed":int(item["filed_new_shares_from_nominal"]),
             "board_max_10m_unconfirmed":int(item["board_max_new_shares"])}
    fail(0<amounts["filed_8m_unconfirmed"]<=amounts["board_max_10m_unconfirmed"],
         "INVALID_8390_ISSUANCE_SHARE_COUNTS")
    scenarios={}
    for k,n in amounts.items():
        fraction=old/(old+n)
        scenarios[k]=dict(new_shares=n,
            proforma_eps_fixed_profit=round(forecast_eps*fraction,2),
            proforma_price_fixed_profit=round(forecast_target*fraction,2),
            upside_pct=round(100*(forecast_target*fraction/price-1),2),
            dilution_pct=round(100*(1-fraction),2),
            issuance_effective_or_completed_verified=False)
    return dict(status="SCENARIO_ONLY_NOT_EFFECTIVE_OR_COMPLETED",
          expected_effectiveness_date=scheduled.isoformat(),
          actual_offering_price_verified=False,
          issued_shares_verified=False,
          incremental_earnings_from_proceeds_assumed_zero=True,
          source_urls=[item["filed_amount_source"],item["board_source"]],
          modeled_current_share_denominator_already_adjusted=False,
          scenarios=scenarios,formal_certified=False)

def flags_and_next(code,analysis,share,cash,sales):
    flags=list(analysis.get("flags",[]))
    ocf=cash.get("cash",{}).get("ocf_k")
    if ocf is not None and ocf<0:
        flags.append("NEGATIVE_OCF_IS_CYCLE_OR_WORKING_CAPITAL_REVIEW_NOT_AUTO_EXIT")
    bonds=share.get("share_bridge",{}).get("bonds",[])
    for b in bonds:
        if not b.get("current_terms_verified"):
            flags.append("CB_LEGAL_TERMS_RECONCILE_"+str(b.get("code")))
        maturity=str(b.get("maturity",""))
        if maturity and maturity<="20261231":
            flags.append("CB_MATURITY_WITHIN_2026_CONFIRM_REPAYMENT_OR_CONVERSION")
        put=str(b.get("put_date",""))
        if put and put<="20261231" and put>="20261020":
            flags.append("CB_PUT_REDEMPTION_WINDOW_WITHIN_2026")
    if sales and sales.get("growth_decelerated_over_20pp"):
        flags.append("Q3_REVENUE_YOY_GROWTH_DECELERATED_OVER_20PP")
    if code=="8390":flags.extend(["AUDITOR_SCOPE_MATERIALITY_OPEN","CASH_EQUITY_RAISE_STATUS_UNVERIFIED"])
    if code=="5388":flags.append("GROSS_MARGIN_RECOVERY_CAUSAL_DRIVER_UNVERIFIED")
    return list(dict.fromkeys(flags))

def conduct(root=DATA):
    root=Path(root)
    research=load(root/"rankings/latest_research.json")
    sources={
        "cash":load(root/"rankings/latest_cash_quality.json"),
        "shares":load(root/"rankings/latest_share_audit.json"),
        "risk":load(root/"rankings/latest_risk_overlay.json")}
    modeltime=validate_vintage(research,sources)
    asof=modeltime.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    rows=research.get("top30_provisional",[])
    fail(all(x.get("formal_Aplus") is False for x in rows if x.get("code") in FOCUS),
         "EXISTING_FORMAL_Aplus_REQUIRES_SEPARATE_REVIEW")
    income={};cashflow={};source_receipts=[]
    for market in ("TWSE","TPEX"):
        for q,k in (("2025-Q2","income"),("2025-Q4","income"),("2026-Q2","income"),("2026-Q2","cashflow")):
            mapping,receipt=index_source(root,q,market,k)
            income[(market,q,k)]=mapping
            cap=receipt.get("captured_at_utc")
            if cap:
                stamp=dt.datetime.fromisoformat(cap.replace("Z","+00:00"))
                fail(stamp.tzinfo is not None and stamp<=modeltime,
                     "SOURCE_CAPTURE_AFTER_ESTIMATE_"+str(q)+market+k)
            source_receipts.append(receipt)
    now_map={}; prior_map={}
    for market in ("TWSE","TPEX"):
        for code,item in income[(market,"2026-Q2","income")].items():now_map[(market,code)]=item
        for code,item in income[(market,"2025-Q2","income")].items():prior_map[(market,code)]=item
    selected=[];missing_focus=[]
    for code in FOCUS:
        matches=[x for x in rows if x.get("code")==code]
        fail(len(matches)<=1,"DUPLICATE_FOCUS_TOP30_"+code)
        if matches:selected.append(matches[0])
        else:missing_focus.append(code)
    fail(bool(selected),"ALL_LEGACY_FOCUS_NAMES_LEFT_CURRENT_TOP30")
    revenue_watch=check_post_financial_quarter_revenue(root,research,now_map,prior_map,selected)
    index={x["code"]:x for x in revenue_watch.get("issuer_checks",[])}
    issuer_review=load(root/"evidence/v880/issuer_reviews/top3_20261020.json")
    review_date=dt.date.fromisoformat(issuer_review["review_date"])
    fail(review_date<=asof,"CORPORATE_ACTION_REVIEW_FROM_FUTURE")
    result=[]
    for row in selected:
        code=row["code"];market=row["market"]
        audit={k:unique(v["rows"],code,k) for k,v in sources.items()}
        shares=audit["shares"]["share_bridge"]
        cap=dict(unverified_bond_terms=[b for b in shares["bonds"] if not b.get("current_terms_verified")])
        financial=analyze(row,
            income[(market,"2025-Q2","income")].get(code),
            income[(market,"2026-Q2","income")].get(code),
            income[(market,"2026-Q2","cashflow")].get(code),
            income[(market,"2025-Q4","income")].get(code),
            cap,2)
        fail(financial.get("formal_Aplus") is False and financial.get("status")=="EVIDENCE_TRIAGE_ONLY_NOT_CERTIFIED",
             "FINANCIAL_TRIAGE_NOT_COMPLETE_"+code)
        prior_base=row["base"]
        eps=num(prior_base["eps"],code+"_BASE_EPS")
        pe=num(prior_base["pe"],code+"_PE")
        px=num(row["reference_close"],code+"_PRICE")
        modeled_target=num(prior_base["target_price"],code+"_TARGET")
        fail(abs(eps*pe-modeled_target)<.04,"FORWARD_EPS_PE_BRIDGE_MISMATCH_"+code)
        stressed=scenario_stress(eps,pe,px,shares,not bool(shares["unresolved_terms"]))
        rev=index.get(code)
        fx=flags_and_next(code,financial,audit["shares"],audit["cash"],rev)
        record=dict(code=code,name=row["name"],market=market,
          base_close=px,price_date=research["asof_price_date"],research_rank_within_all_786=row.get("market_research_rank"),
          base_2027_eps=round(eps,3),base_2027_pe=round(pe,2),
          base_2027_target_price=round(modeled_target,2),
          base_2027_upside_pct=round(100*(modeled_target/px-1),2),
          valuation_stress=stressed,
          observed_2025FY_eps=financial["prior_fy_basic_eps"],
          observed_H1_eps=financial["latest_ytd_basic_eps"],
          observed_H1_ocf_ntd_100m=round(financial["operating_cashflow_ytd_k"]/100000,3),
          observed_H1_gm_pct=financial["gross_margin_latest_pct"],
          q3_revenue_yoy=rev,
          cashflow_H1=audit["cash"].get("cash"),
          cb_current_legal_terms_verified=(len(shares["unresolved_terms"])==0 and
            shares.get("fully_diluted_shares_certified") is True),
          existing_model_cb_shares_count=round(shares["cb_additional_shares"]),
          CB_bond_issues=[dict(code=b["code"],face=b["face"],
             conversion_price_from_snapshot=b["conversion_price"],
             put_date=b.get("put_date"),maturity=b.get("maturity"),
             legal_price_and_outstanding_verified=b["current_terms_verified"]) for b in shares["bonds"]],
          remaining_unverified_gates=list(audit["shares"]["certification"]["gates_pending"]),
          flags=fx,
          forward_peer_PE_verified=False,
          actual_Q3_gm_and_eps_verified=False,
          issuer_specific_original_notes_and_PIT_verified=False,
          internal_Aplus_upgrade=False,
          proof_status="RESEARCH_ONLY_NOT_A_FORMAL_Aplus")
        if code=="8390":record["equity_raise_sensitivity"]=equity_watch(
            issuer_review,shares,eps,modeled_target,px,asof)
        result.append(record)
    return dict(status=("V890_FIVE_STOCK_RESEARCH_AUDIT_NOT_CERTIFIED"
                        if not missing_focus else
                        "V890_CURRENT_TOP30_SUBSET_AUDIT_NOT_CERTIFIED"),
        model=research["model"],estimate_vintage=research["estimate_vintage"],
        asof_price_date=research["asof_price_date"],
        latest_available_quarter=research["financial_last_quarter"],
        issuer_count=len(result),securities=result,
        legacy_focus_not_in_current_top30=missing_focus,
        official_mirror_receipts=source_receipts,
        next_quarter_revenue_status=revenue_watch["status"],
        publication_PIT_documented=False,
        legal_issuer_CB_terms_and_sector_PE_verified=False,
        standard_revenue_growth_is_not_EPS_confirmation=True,
        no_formal_Aplus_added=True,
        unchanged_market_ranking=True,
        assumptions="10%, 20%, 30% EPS and PE simultaneous markdown; CB conversion reset extra share sensitivity is hypothetical; 8390 equity issue is not confirmed",
        notes=["Negative OCF is not an automatic loss or exit.",
          "An issuer-specific official original filing, independent CB legal terms, matched PE peers, and a true PIT investment backtest remain outstanding."])

def markdown(report):
    lines=["# V8.9.0 五檔候選：EPS、現金流、CB與估值壓測","",
      f"資料版本：{report['estimate_vintage']}；價格日：{report['asof_price_date']}。",
      "**研究排查，不修改Top20，不產生正式A+、不視作買進訊號。**","",
      "|股票|2027 Base價|Base漲幅|EPS/PE各-20%|Q3營收年增|H1 OCF(億)|未確認CB|",
      "|---|---:|---:|---:|---:|---:|---:|"]
    for r in report["securities"]:
        rev=r["q3_revenue_yoy"] or {}
        yoy=rev.get("next_quarter_revenue_yoy_pct")
        sales=f"{yoy:.1f}%" if yoy is not None else "待核"
        lines.append(f"|{r['code']} {r['name']}|{r['base_2027_target_price']:.2f}|"
                     f"{r['base_2027_upside_pct']:+.1f}%|"
                     f"{r['valuation_stress']['double20']['upside_pct']:+.1f}%|{sales}")
        lines[-1]+=f"|{r['observed_H1_ocf_ntd_100m']:+.2f}|{sum(not x['legal_price_and_outstanding_verified'] for x in r['CB_bond_issues'])}|"
    lines+=["","## 逐股待處理",""]
    for r in report["securities"]:
        lines.append(f"### {r['code']} {r['name']}")
        lines.append(f"Base價 {r['base_2027_target_price']:.2f}、20%雙壓價 {r['valuation_stress']['double20']['target_price']:.2f}、10%雙壓加CB價 {r['valuation_stress']['double10_plus_CB_reset_sensitivity']['target_price']:.2f}。")
        lines.append("尚未核實項目："+("、".join(r["flags"][:9]) if r["flags"] else "原始財報與法律文件仍待核") )
        if "equity_raise_sensitivity" in r:
            issue=r["equity_raise_sensitivity"]
            lines.append("現金增資狀態："+issue["status"]+"。")
            for label,s in issue.get("scenarios",{}).items():
                lines.append(f"- {label}（未生效假設）：EPS {s['proforma_eps_fixed_profit']:.2f}，價 {s['proforma_price_fixed_profit']:.2f}")
        lines.append("")
    lines+=["## 重要限制","",
       "1. 雙10%/20%/30%是敏感度；不是機率、績效回測或已驗證的安全邊際。",
       "2. CB現有額度已計入模型base_shares，重設敏感度只增加額外股數，不重複扣一次。",
       "3. 發債/現金增資是否生效、償付、最新轉換價需當日正式文件審查。",
       "4. 季營收成長不能證明毛利率、EPS改善。負OCF應分辨備貨、應收與投資，不能自動判賣。",
       "5. 官方鏡像與SHA擷取不等於原件核閱或個別公司公告PIT，13項證據門檻仍待核。",""]
    return "\n".join(lines)

def main():
    report=conduct()
    dest=DATA/"rankings"
    dest.mkdir(parents=True,exist_ok=True)
    (dest/"v890_five_candidate_audit.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (dest/"v890_five_candidate_audit.md").write_text(markdown(report)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],
       "issuers":[{"code":r["code"],"double20_upside_pct":r["valuation_stress"]["double20"]["upside_pct"],
         "ocf_100m":r["observed_H1_ocf_ntd_100m"],
         "q3_sales_yoy":(r["q3_revenue_yoy"] or {}).get("next_quarter_revenue_yoy_pct")}
                for r in report["securities"]],"new_Aplus":0},ensure_ascii=False))

if __name__=="__main__":
    main()
