#!/usr/bin/env python3
"""V8.9.2: whole TOP20 EPS/PE/cash/CB evidence triage, research-only.

Reads synchronized model and risk/cash/share outputs, validates current official
summary mirrors and date consistency, and prioritizes *verification work*.
Scores are transparent workload ordering heuristics, NOT probabilities,
formal grades, investment signals, or adjustments to model Base assumptions.
"""
import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0,str(PROJECT))
from scripts.v887_top10_earnings_audit import load, index_source, analyze, check_post_financial_quarter_revenue
from scripts.v890_five_candidate_audit import scenario_stress

AUDITS=("cash","shares","risk")
FILE_STEMS={"cash":"latest_cash_quality","shares":"latest_share_audit","risk":"latest_risk_overlay"}
TARGET_COUNT=20

def require(flag,code):
    if not flag: raise ValueError(code)

def indexed(rows,kind):
    ret={}
    for r in rows:
        code=str(r.get("code",""))
        require(re.fullmatch(r"\\d{4}",code) and code not in ret,
                "INVALID_OR_DUPLICATE_"+kind+"_"+code)
        ret[code]=r
    return ret

def validate(research,audits):
    require(research.get("model")=="V8.8.2","MODEL_REQUIRES_NEW_AUDIT")
    instant=dt.datetime.fromisoformat(research["estimate_vintage"])
    require(instant.tzinfo is not None,"UNZONED_VINTAGE")
    require(research.get("asof_price_date") and
            research["asof_price_date"]<=instant.date().isoformat(),"PRICE_FROM_FUTURE")
    rows=research.get("top30_provisional",[])
    require(len(rows)>=TARGET_COUNT,"TOP20_SOURCE_INCOMPLETE")
    top=rows[:TARGET_COUNT]
    require(len({(r["market"],str(r["code"])) for r in top})==TARGET_COUNT,
            "DUPLICATE_TOP20")
    require(all(r.get("rankable") is True and r.get("base") and
                r.get("market") in ("TWSE","TPEX") for r in top),
            "TOP20_NOT_COMPARABLE")
    sha=research.get("model_code_sha256")
    for kind,doc in audits.items():
        require(doc.get("estimate_vintage")==research["estimate_vintage"]
                and doc.get("asof_price_date")==research["asof_price_date"]
                and doc.get("financial_last_quarter")==research["financial_last_quarter"]
                and doc.get("formal_Aplus_count")==research.get("formal_Aplus_count")
                and doc.get("source_model_code_sha256")==sha,
                "AUDIT_VINTAGE_OR_MODEL_MISMATCH_"+kind)
    quarter=research["financial_last_quarter"]
    match=re.fullmatch(r"(20\\d{2})-Q([1-4])",quarter)
    require(match is not None,"INVALID_QUARTER")
    year,q=map(int,match.groups())
    require(year>=2025,"INVALID_QUARTER_YEAR")
    return top,instant,quarter,f"{year-1}-Q{q}",f"{year-1}-Q4",q

def priority(record):
    """Heuristic triage order, explicitly not a performance probability."""
    v=record["analysis"]
    strength=0
    reasons=[]
    if record["source_tier"]=="ORIGINAL_CURRENT_ISSUER_NUMERICS":
        strength+=2
    else: reasons.append("ISSUER_ORIGINAL_NUMERICS_NOT_CROSSCHECKED")
    if v.get("operating_cashflow_ytd_k") is not None:
        if v["operating_cashflow_ytd_k"]>0: strength+=2
        else: reasons.append("NEGATIVE_OR_ZERO_H1_OCF_REQUIRES_WORKING_CAPITAL_BRIDGE")
    else: reasons.append("OCF_MISSING")
    if record["base_2027_pe"]<=20: strength+=1
    else: reasons.append("HIGH_FORWARD_PE_UNVERIFIED_PEERS")
    x=v.get("2027_eps_over_ytd_runrate")
    if x is not None and 0<x<=1.30: strength+=2
    else: reasons.append("FORWARD_EPS_ABOVE_1_3X_H1_ANNUALIZED_OR_UNAVAILABLE")
    if not record["cb_unverified_issues"]: strength+=1
    else: reasons.append("CB_LEGAL_TERMS_UNVERIFIED")
    if record["stress_double20_upside_pct"]>=30: strength+=2
    else: reasons.append("EPS_PE_DOUBLE20_LOSES_30PCT_NUMERICAL_THRESHOLD")
    q3=record["q3_revenue_yoy_pct"]
    if q3 is not None and q3>0:strength+=1
    else: reasons.append("Q3_SALES_GROWTH_UNVERIFIED_OR_NONPOSITIVE")
    if record["code"]=="8390":
        strength-=3
        reasons.append("EQUITY_ISSUANCE_NOT_CONFIRMED")
        reasons.append("AUDITOR_QUALIFIED_SCOPE_MATERIALITY_PENDING")
    if record["source_tier"]!="ORIGINAL_CURRENT_ISSUER_NUMERICS" and x is None:
        strength-=1
    return strength,reasons

def build(research,audits,mirrors,quarter_revenue=None):
    top,instant,quarter,prior,prior_fy,q=validate(research,audits)
    lookup={key:indexed(audits[key]["rows"],key) for key in AUDITS}
    income={}
    for m in ("TWSE","TPEX"):
        for period,kind in ((prior,"income"),(quarter,"income"),(quarter,"cashflow"),
                            (prior_fy,"income")):
            require((m,period,kind) in mirrors,"FINANCIAL_MIRROR_MISSING")
            income[(m,period,kind)]=mirrors[(m,period,kind)]
    revmap={x["code"]:x for x in (quarter_revenue or {}).get("issuer_checks",[])}
    records=[]
    for rank,row in enumerate(top,1):
        code=str(row["code"]);market=row["market"]
        audit={k:lookup[k].get(code) for k in AUDITS}
        require(all(x is not None for x in audit.values()),"AUDIT_ISSUER_MISSING_"+code)
        share=audit["shares"]["share_bridge"]
        unresolved=list(share.get("unresolved_terms") or [])
        financial=analyze(
            row,income[(market,prior,"income")].get(code),
            income[(market,quarter,"income")].get(code),
            income[(market,quarter,"cashflow")].get(code),
            income[(market,prior_fy,"income")].get(code),
            {"unverified_bond_terms":unresolved},q
        )
        eps=float(row["base"]["eps"]);pe=float(row["base"]["pe"])
        px=float(row["reference_close"]);base_price=float(row["base"]["target_price"])
        require(all(math.isfinite(x) and x>0 for x in (eps,pe,px,base_price))
                and abs(eps*pe-base_price)<.04,"EPS_PE_PRICE_BRIDGE_"+code)
        stress=scenario_stress(eps,pe,px,share,legal=False)
        cb_stress=stress["double10_plus_CB_reset_sensitivity"]
        q3=revmap.get(code)
        item=dict(rank=rank,code=code,name=row["name"],market=market,
                  price_date=research["asof_price_date"],
                  source_tier=row.get("source_tier"),
                  reference_close=px,base_2027_eps=round(eps,3),
                  base_2027_pe=round(pe,3),base_2027_target=round(base_price,2),
                  base_2027_upside_pct=round(100*(base_price/px-1),2),
                  stress_double10_upside_pct=stress["double10"]["upside_pct"],
                  stress_double20_upside_pct=stress["double20"]["upside_pct"],
                  cb_reset_double10_upside_pct=cb_stress["upside_pct"],
                  cb_reset_terms_verified=False,
                  cb_unverified_issues=unresolved,
                  modeled_CB_share_included=round(float(share.get("cb_additional_shares") or 0)),
                  q3_revenue_yoy_pct=(q3 or {}).get("next_quarter_revenue_yoy_pct"),
                  q3_revenue_extrapolation_not_earnings=True,
                  analysis=financial,
                  cash_quality=audit["cash"]["cash"],
                  source_flags=audit["risk"].get("warning_flags",[]),
                  formal_Aplus=bool(row.get("formal_Aplus")),
                  valuation_revised=False)
        score,issues=priority(item)
        item.update(verification_priority_score=score,critical_evidence_gaps=issues,
                    high_quality_Aplus_certified=False)
        records.append(item)
    require(len(records)==TARGET_COUNT,"TOP20_REVIEW_INCOMPLETE")
    # Sort only a separate evidence-review queue. Published Base ranking stays untouched.
    review=sorted(records,key=lambda r:(-r["verification_priority_score"],
                                        -r["stress_double20_upside_pct"],r["rank"]))
    return dict(status="TOP20_EVIDENCE_TRIAGE_NOT_CERTIFIED",model=research["model"],
                estimate_vintage=research["estimate_vintage"],
                asof_price_date=research["asof_price_date"],
                financial_last_quarter=quarter,
                top20_count=TARGET_COUNT,
                top20_base_rank_unchanged=True,
                formal_Aplus_from_source=research["formal_Aplus_count"],
                automatically_certified_Aplus=0,
                next_quarter_revenue_status=(quarter_revenue or {}).get("status","NOT_EVALUATED"),
                issuer_ranked=records,
                verification_priority=[dict(rank=r["rank"],code=r["code"],name=r["name"],
                    verification_priority_score=r["verification_priority_score"],
                    base_upside_pct=r["base_2027_upside_pct"],
                    stress_double20_upside_pct=r["stress_double20_upside_pct"],
                    critical_evidence_gaps=r["critical_evidence_gaps"])
                    for r in review],
                limits=[
                    "YTD basic EPS annualization is a seasonal-neutral proxy, not 2027 diluted EPS validation.",
                    "OCF is YTD operating cash flow, not free cash flow. Negative OCF is not automatic issuer FAIL.",
                    "PE>20 is a peer-validation flag, not proof that a stock is overvalued.",
                    "The model's reported CB shares are already in its denominator; extra CB reset stress is incremental only.",
                    "No issuer-specific original notes, PE peer cycle, CB terms, PIT trading backtest or formal certificate is established.",
                    "Verification priority scores order next investigations and are NOT calibrated probabilities, formal ratings or trading signals."
                ])

def render(r):
    def fmt(x,nd=1,sgn=False):
        return "待驗" if x is None else (("%+."+str(nd)+"f") if sgn else ("%."+str(nd)+"f"))%x
    out=["# V8.9.2 全市場2027 Base TOP20：EPS／PE／現金流／稀釋逐檔排查","",
         f"更新：{r['estimate_vintage']}；收盤基準 {r['asof_price_date']}；已公告財務期 {r['financial_last_quarter']}。","",
         "**前20為既有Base漲幅排名；研究預檢、不產生正式A+，也不改寫EPS、PE或交易指令。**","",
         "## 20檔完整風險表","",
         "|原序|股票|Base漲幅|2027 EPS / H1年化EPS|模型PE|H1 OCF(億)|未核CB|EPS、PE各-20%漲幅|優先查核分|",
         "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s in r["issuer_ranked"]:
        a=s["analysis"]
        ratio=a.get("2027_eps_over_ytd_runrate")
        v=a.get("operating_cashflow_ytd_k")
        out.append("|%s|%s %s|%s%%|%s倍|%s|%s|%s|%s%%|%s|"%
              (s["rank"],s["code"],s["name"],fmt(s["base_2027_upside_pct"],1,True),
               fmt(ratio,2),fmt(s["base_2027_pe"],2),
               fmt(None if v is None else v/100000,2,True),
               len(s["cb_unverified_issues"]),
               fmt(s["stress_double20_upside_pct"],1,True),
               s["verification_priority_score"]))
    out+=["","## 證據查核優先順位（不是投資報酬率排名）","",
          "|優先序|股票|Base漲幅|20%雙壓漲幅|最大待解缺口|",
          "|---:|---|---:|---:|---|"]
    for i,s in enumerate(r["verification_priority"][:12],1):
        issue="、".join(s["critical_evidence_gaps"][:3]) if s["critical_evidence_gaps"] else "仍需13項正式原件簽核"
        out.append("|%s|%s %s|%+.1f%%|%+.1f%%|%s|"%
                   (i,s["code"],s["name"],s["base_upside_pct"],
                    s["stress_double20_upside_pct"],issue))
    out+=["","## 注意事項",""]
    for z in r["limits"]:out.append("- "+z)
    out+=["","完整逐檔原始數值及對應風險旗標見同名JSON。",""]
    return "\n".join(out)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-dir",default="tw-market-data")
    a=parser.parse_args();root=Path(a.data_dir);out=root/"rankings"
    research=load(out/"latest_research.json")
    audits={k:load(out/(FILE_STEMS[k]+".json")) for k in AUDITS}
    top,instant,q,prev,fy,quarter_num=validate(research,audits)
    mirrors={};receipts=[]
    for market in ("TWSE","TPEX"):
        for period,kind in ((prev,"income"),(q,"income"),(q,"cashflow"),(fy,"income")):
            rows,receipt=index_source(root,period,market,kind)
            stamp=receipt.get("captured_at_utc")
            if stamp:
                measured=dt.datetime.fromisoformat(stamp.replace("Z","+00:00"))
                require(measured.tzinfo is not None and measured<=instant,
                        "FUTURE_FINANCIAL_CAPTURE")
            receipts.append(receipt)
            mirrors[(market,period,kind)]=rows
    now={(market,code):row for (market,period,kind),listing in mirrors.items()
         if period==q and kind=="income" for code,row in listing.items()}
    prior={(market,code):row for (market,period,kind),listing in mirrors.items()
         if period==prev and kind=="income" for code,row in listing.items()}
    # If not every official next-quarter revenue shard exists, keep Q3 as UNKNOWN.
    try: revenues=check_post_financial_quarter_revenue(root,research,now,prior,top)
    except (FileNotFoundError,KeyError,ValueError) as e:
        revenues=dict(status="REVENUE_CHECK_PENDING",note=str(e)[:160],issuer_checks=[])
    report=build(research,audits,mirrors,revenues)
    report["financial_mirror_receipts"]=receipts
    (out/"v892_top20_quality_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"v892_top20_quality_audit.md").write_text(render(report),encoding="utf-8")
    print(json.dumps(dict(status=report["status"],top20=20,ranked_review=report["verification_priority"][:5],
                          formal_new_Aplus=0),ensure_ascii=False))

if __name__=="__main__":main()
