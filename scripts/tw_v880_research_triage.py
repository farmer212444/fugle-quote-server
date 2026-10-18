#!/usr/bin/env python3
"""V8.8.0 research-only triage. Never certifies A+/A++ or makes trading decisions."""
import argparse
import json
import math
from pathlib import Path

def triage(payload):
    if not isinstance(payload, dict):
        raise ValueError("ranking payload must be an object")
    if payload.get("formal_Aplus_count") != 0 or payload.get("formal_Aplusplus_count") != 0:
        raise ValueError("input claims unverified formal certification")
    rows = payload.get("top30_provisional", [])
    if not isinstance(rows, list):
        raise ValueError("top30_provisional must be an array")
    seen = set()
    out = []
    for row in rows:
        code = str(row.get("code", ""))
        if not code or code in seen:
            raise ValueError("missing or duplicate issuer code")
        seen.add(code)
        upside = row.get("scenario_upside_pct")
        score = row.get("score")
        if (isinstance(upside, bool) or isinstance(score, bool)
                or not isinstance(upside, (int,float)) or not isinstance(score,(int,float))
                or not math.isfinite(upside) or not math.isfinite(score)):
            raise ValueError("missing, non-finite, or invalid numeric score/upside")
        # Prioritize due diligence, NOT certification; do not treat negative FCF as automatic failure.
        lane = ("EARLY_TURNAROUND_REVIEW" if upside >= 25 else "WATCH")
        out.append({"code":code,"name":row.get("name"),"research_lane":lane,
                    "scenario_upside_pct":upside,"quality_score":score,
                    "formal_grade":"NOT_CERTIFIED",
                    "needs":["issuer_original_8q_PIT","diluted_share_bridge","OCF_CAPEX_context",
                             "sector_PE_history","2027_EPS_profit_bridge","exit_stress"]})
    out.sort(key=lambda x:(x["research_lane"]=="EARLY_TURNAROUND_REVIEW",x["quality_score"],x["scenario_upside_pct"]),reverse=True)
    return {"model":"V8.8.0 research triage / shadow only","source_model":payload.get("model"),
            "source_price_date":payload.get("asof_price_date"),"universe_scope":"legacy provisional top30 only",
            "formal_Aplus_count":0,"formal_Aplusplus_count":0,
            "candidates":out,"warning":"No 2000-issuer coverage, no 2027 EPS recalibration, no backtest; research only."}

def self_test():
    base={"formal_Aplus_count":0,"formal_Aplusplus_count":0,
          "top30_provisional":[{"code":"9802","name":"鈺齊-KY","score":70,"scenario_upside_pct":27}]}
    r=triage(base)
    assert r["candidates"][0]["research_lane"]=="EARLY_TURNAROUND_REVIEW"
    assert r["candidates"][0]["formal_grade"]=="NOT_CERTIFIED"
    assert r["formal_Aplus_count"]==0
    assert triage({"formal_Aplus_count":0,"formal_Aplusplus_count":0,
                   "top30_provisional":[{"code":"6206","score":60,"scenario_upside_pct":24.9}]})["candidates"][0]["research_lane"]=="WATCH"
    for bad in ({"formal_Aplus_count":1,"formal_Aplusplus_count":0,"top30_provisional":[]},
                {"formal_Aplus_count":0,"formal_Aplusplus_count":0,"top30_provisional":[{"code":"1","score":1,"scenario_upside_pct":25},{"code":"1","score":1,"scenario_upside_pct":26}]}):
        try:triage(bad)
        except ValueError:pass
        else:raise AssertionError("fail-closed check missed")
    for invalid in (float("nan"), float("inf"), True):
        bad={"formal_Aplus_count":0,"formal_Aplusplus_count":0,
             "top30_provisional":[{"code":"9802","score":70,"scenario_upside_pct":invalid}]}
        try:triage(bad)
        except ValueError:pass
        else:raise AssertionError("invalid numeric scenario accepted")
    print("SELF_TEST_OK: V8.8.0 shadow-only triage")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("source",nargs="?")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.source:p.error("source JSON required")
        print(json.dumps(triage(json.loads(Path(a.source).read_text(encoding="utf-8"))),ensure_ascii=False,indent=2))
