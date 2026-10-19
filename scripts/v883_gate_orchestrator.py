#!/usr/bin/env python3
"""Fail-closed V8.8.3 evidence-gate work dispatcher; no automatic PASS or trades.

Turns each current issuer's already-computed pending gates into dated, prioritized
collection/review jobs. A job is NOT a certificate or evidence of completion.
"""
import argparse
import collections
import json
import math
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880.evidence import GATES

# These are routing destinations, not source attestations or PASS predicates.
ROUTES = {
    "original_eight_quarter_statements": ("FINANCIAL_ORIGINALS", "Fetch eight dated issuer originals, verify units, revisions and notes"),
    "cash_and_working_capital": ("FINANCIAL_CASH", "Reconcile operating cash flow, receivables, inventory, payables and capex"),
    "nonoperating_components": ("FINANCIAL_NOTES", "Reconcile recurring versus volatile nonoperating income components"),
    "fully_diluted_shares": ("CAPITAL_LEGAL", "Verify current common shares, outstanding CB, resets and conversion terms"),
    "matched_peers_and_cycle": ("VALUATION_REVIEW", "Verify business-matched peer sample and full-cycle PE assumptions"),
    "management_promises": ("HUMAN_REVIEW", "Verify management guidance and subsequent delivery from dated source"),
    "auditor_scope": ("HUMAN_REVIEW", "Assess qualified reviews, emphasis paragraphs and materiality"),
    "tradability": ("MARKET_HISTORY", "Collect 20+ dated sessions, spreads and position exit-capacity stress"),
    "forecast_bridge": ("OPERATING_BRIDGE", "Verify issuer capacity, utilization, ASP, orders, costs and EPS bridge"),
    "insider_claims": ("DISCLOSURE_REVIEW", "Match signed insider trade disclosures to issuer, person and date"),
    "dividend_window": ("CORPORATE_ACTIONS", "Verify ex-date, payment, distribution amount and relevant window"),
    "point_in_time": ("HISTORICAL_PIT", "Verify original public timestamps, revisions and then-known issuer universe"),
    "out_of_sample_validation": ("HISTORICAL_BACKTEST", "Require frozen historical model vintages, actions, fees and prices"),
}

if set(ROUTES) != set(GATES):
    raise RuntimeError("ROUTER_MISSING_OR_EXTRA_CERTIFICATION_GATE")

LANES = ("HIGH_UPSIDE_GE30", "DISCOVERY_25_TO30", "VALUED_BELOW25", "INPUT_REPAIR")

def build(research, pending, top=50):
    if top < 1:
        raise ValueError("TOP_MUST_BE_POSITIVE")
    for field in ("model", "estimate_vintage"):
        if not research.get(field) or research[field] != pending.get(field if field=="model" else "asof"):
            raise ValueError("STALE_OR_MISMATCHED_RANKING_AND_PENDING_EVIDENCE_" + field)
    rows = research.get("all_model_row_summary")
    tasks = pending.get("rows")
    if not isinstance(rows, list) or not isinstance(tasks, list):
        raise ValueError("MISSING_ISSUER_INPUTS")
    count = research.get("data_scope", {}).get("model_rows")
    if count != len(rows):
        raise ValueError("MARKET_UNIVERSE_COUNT_MISMATCH")
    def as_map(xs, name):
        out={}
        for x in xs:
            code=str(x.get("code",""))
            if not code or code in out:
                raise ValueError("DUPLICATE_OR_EMPTY_ISSUER_" + name)
            out[code]=x
        return out
    task_map=as_map(tasks,"TASK")
    row_map=as_map(rows,"RESEARCH")
    if set(task_map) != set(row_map):
        raise ValueError("PENDING_GATE_UNIVERSE_NOT_IDENTICAL_TO_RANKING")
    result=[]
    for code,row in row_map.items():
        t=task_map[code]
        if t.get("status") != row.get("status"):
            raise ValueError("STALE_GATE_STATUS_" + code)
        gates=t.get("pending_gates")
        if not isinstance(gates,list) or len(set(gates)) != len(gates) or any(g not in ROUTES for g in gates):
            raise ValueError("INVALID_PENDING_GATES_" + code)
        upside=row.get("scenario_upside_pct")
        if upside is not None and (isinstance(upside,bool) or not isinstance(upside,(int,float)) or not math.isfinite(upside)):
            raise ValueError("INVALID_RESEARCH_UPSIDE_" + code)
        valued=bool(row.get("rankable")) and upside is not None
        if valued and not gates and research.get("formal_Aplus_count",0)==0:
            raise ValueError("RANKABLE_ISSUER_MISSING_CERTIFICATION_GATE_EVIDENCE_" + code)
        lane=("INPUT_REPAIR" if not valued else
              "HIGH_UPSIDE_GE30" if upside>=30 else
              "DISCOVERY_25_TO30" if upside>=25 else "VALUED_BELOW25")
        routes=[dict(gate=g,route=ROUTES[g][0],next_check=ROUTES[g][1],verified=False) for g in GATES if g in gates]
        result.append(dict(code=code,name=row.get("name"),market=row.get("market"),
                           research_upside_pct=upside if valued else None,
                           research_source_tier=row.get("source_tier"),
                           lane=lane,source_status=row.get("status"),
                           pending_gates=gates,route_jobs=routes,
                           next_route=(routes[0]["route"] if routes else "REPAIR_VALUATION_INPUTS" if not valued else None),
                           evidence_state="PENDING_NOT_CERTIFIED",
                           formal_Aplus=False))
    result.sort(key=lambda r:(LANES.index(r["lane"]),
                              -(r["research_upside_pct"] if r["research_upside_pct"] is not None else float("-inf")),r["code"]))
    ranked=[r for r in result if r["lane"]!="INPUT_REPAIR"]
    queue=result[:]
    bygate=collections.Counter(g for r in ranked for g in r["pending_gates"])
    byroute=collections.Counter(j["route"] for r in ranked for j in r["route_jobs"])
    return dict(model=research["model"],vintage=research["estimate_vintage"],
                price_date=research.get("asof_price_date"),
                eligible_research_count=len(ranked),
                tracked_issuer_count=len(result),formal_Aplus_source_count=research.get("formal_Aplus_count"),
                requested_top_n=top,active_priority=ranked[:top],
                all_issuer_jobs=queue,gate_pending_counts={g:bygate.get(g,0) for g in GATES},
                route_pending_counts=dict(sorted(byroute.items())),
                lane_counts={k:sum(r["lane"]==k for r in result) for k in LANES},
                source_errors=research.get("source_failures",[]),
                certification_from_dispatch=0,auto_PASSED_gates_from_dispatch=0,
                real_issuer_original_filing_notes_audited=False,
                historical_PIT_backtest_completed=False,
                interpretation="Jobs are requests for source collection or review; NO certificate is minted. Missing, stale, non-original, or unauthenticated inputs remain PENDING.")

def render_md(o):
    out=["# Evidence dispatch – "+o["model"],"",
         "研究估計："+o["vintage"]+"；參考價格日："+str(o["price_date"])+"。",
         "可估值："+str(o["eligible_research_count"])+"；逐家列管："+str(o["tracked_issuer_count"])+"；正式新增A+：0。",
         "此檔只列示證據蒐集與人工覆核工作，不構成品質通過或投資報酬回測。","",
         "## 前"+str(o["requested_top_n"])+"名應驗證候選","",
         "|順位|公司|研究漲幅|待驗門檻數|下一個工作|",
         "|---:|---|---:|---:|---|"]
    for i,r in enumerate(o["active_priority"],1):
        out.append("|%d|%s %s|%+.1f%%|%d|%s|"%(i,r["code"],r["name"] or "",r["research_upside_pct"],len(r["pending_gates"]),r["next_route"] or "無"))
    out+=["","## 13項待驗數量","",
          "|門檻|待驗股票數|蒐集／覆核路線|",
          "|---|---:|---|"]
    for g in GATES:
        out.append("|%s|%d|%s|"%(g,o["gate_pending_counts"][g],ROUTES[g][0]))
    out+=["","注意：管理層承諾、查核意見重要性、特殊產業營運假設等需要有可稽核來源的覆核；本排程不會自動標PASS。"]
    return "\n".join(out)+"\n"

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--research",default="tw-market-data/rankings/latest_research.json")
    p.add_argument("--pending",default="tw-market-data/rankings/v880_pending_work.json")
    p.add_argument("--output",default="tw-market-data/rankings/v883_gate_dispatch.json")
    p.add_argument("--markdown",default="tw-market-data/rankings/v883_gate_dispatch.md")
    p.add_argument("--top",type=int,default=50)
    a=p.parse_args()
    r=json.loads(Path(a.research).read_text(encoding="utf-8"))
    t=json.loads(Path(a.pending).read_text(encoding="utf-8"))
    result=build(r,t,a.top)
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    m=Path(a.markdown);m.parent.mkdir(parents=True,exist_ok=True)
    m.write_text(render_md(result),encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("model","eligible_research_count","tracked_issuer_count","lane_counts","certification_from_dispatch")},ensure_ascii=False))

if __name__=="__main__":
    main()
