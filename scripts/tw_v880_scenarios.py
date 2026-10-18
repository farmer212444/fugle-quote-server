#!/usr/bin/env python3
"""V8.8.0 three-scenario independent EPS/PE sensitivities; research-only."""
import argparse
import json
from pathlib import Path
from tw_v880_profit_bridge import forecast, number

def scenarios(payload):
    if not isinstance(payload,dict):raise ValueError("payload must be object")
    base=payload.get("financial_inputs")
    overrides=payload.get("scenario_assumptions")
    if not isinstance(base,dict) or not isinstance(overrides,dict):
        raise ValueError("financial inputs and scenario assumptions required")
    if set(overrides)!={"bear","base","bull"}:
        raise ValueError("all bear/base/bull scenarios required")
    out={}
    for name in ("bear","base","bull"):
        ov=overrides[name]
        if not isinstance(ov,dict):raise ValueError("scenario assumptions must be objects")
        permitted={"revenue_growth","gross_margin_delta","opex_growth","nonoperating_normalized",
                   "tax_rate","minority_profit","pe","weighted_diluted_shares_k"}
        if not ov or set(ov)-permitted:raise ValueError("unsupported or empty scenario override")
        out[name]=forecast(dict(base,**ov))
    prices=[out[k]["scenario_target_price"] for k in ("bear","base","bull")]
    if prices!=sorted(prices):
        raise ValueError("nonmonotonic bear/base/bull prices; reconcile assumptions")
    weights=payload.get("probabilities",{"bear":0.25,"base":0.5,"bull":0.25})
    if set(weights)!={"bear","base","bull"}:raise ValueError("invalid probability keys")
    weights={k:number(v,k) for k,v in weights.items()}
    if any(v<0 or v>1 for v in weights.values()) or abs(sum(weights.values())-1)>1e-8:
        raise ValueError("probabilities must total one")
    expected=sum(weights[k]*out[k]["scenario_target_price"] for k in weights)
    return {"model":"V8.8.0 independent 2027 three-scenario shadow",
            "scenario_results":out,"probabilities":weights,
            "probability_weighted_price":round(expected,2),
            "formal_grade":"NOT_CERTIFIED",
            "warning":"Research sensitivity only; no verified issuer PIT, share reconciliation, historical PE or walk-forward."}

def self_test():
    x={"revenue_h1":100000,"gross_profit_h1":20000,"operating_profit_h1":10000,
       "net_income_parent_h1":8000,"weighted_diluted_shares_k":10000,
       "share_price":50,"revenue_growth":0.1,"gross_margin_delta":0,
       "opex_growth":0.05,"nonoperating_normalized":0,"tax_rate":0.2,
       "minority_profit":0,"pe":15}
    p={"financial_inputs":x,"scenario_assumptions":{
       "bear":{"revenue_growth":0,"pe":10},
       "base":{"revenue_growth":0.1,"pe":15},
       "bull":{"revenue_growth":0.2,"pe":20}}}
    r=scenarios(p)
    assert r["scenario_results"]["base"]["diluted_eps_2027"]==1.84
    assert r["formal_grade"]=="NOT_CERTIFIED"
    for bad in (dict(p,probabilities={"bear":0.4,"base":0.5,"bull":0.5}),
                dict(p,scenario_assumptions={"bear":{"pe":30},"base":{"pe":15},"bull":{"pe":10}})):
        try:scenarios(bad)
        except ValueError:pass
        else:raise AssertionError("invalid scenario accepted")
    print("SELF_TEST_OK: bear/base/bull monotonic valuation and probabilities")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("payload",nargs="?")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.payload:p.error("scenario JSON required")
        print(json.dumps(scenarios(json.loads(Path(a.payload).read_text(encoding="utf-8"))),ensure_ascii=False,indent=2))
