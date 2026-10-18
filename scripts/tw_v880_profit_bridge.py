#!/usr/bin/env python3
"""V8.8.0 issuer-level scenario profit bridge; research only, not a formal A+."""
import argparse
import json
import math
from pathlib import Path

def number(v, name):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
        raise ValueError("invalid "+name)
    return float(v)

def forecast(data):
    """All amounts in the same currency/unit, share count in matching thousands."""
    required=("revenue_h1","gross_profit_h1","operating_profit_h1",
              "net_income_parent_h1","weighted_diluted_shares_k",
              "share_price","revenue_growth","gross_margin_delta",
              "opex_growth","nonoperating_normalized","tax_rate",
              "minority_profit","pe")
    v={k:number(data.get(k),k) for k in required}
    if v["revenue_h1"]<=0 or v["weighted_diluted_shares_k"]<=0 or v["share_price"]<=0 or v["pe"]<=0:
        raise ValueError("invalid denominator, price or PE")
    if not (0<=v["tax_rate"]<=0.5 and -0.95<=v["revenue_growth"]<=2 and -0.5<=v["gross_margin_delta"]<=0.5):
        raise ValueError("scenario assumptions outside explicit bounds")
    # Annualization is a transparent starting assumption, not a seasonal forecast.
    revenue_base=v["revenue_h1"]*2
    gross_margin=v["gross_profit_h1"]/v["revenue_h1"]+v["gross_margin_delta"]
    if not 0<=gross_margin<=1:raise ValueError("impossible gross margin")
    opex_h1=v["gross_profit_h1"]-v["operating_profit_h1"]
    if opex_h1<0 or v["opex_growth"]< -0.95 or v["opex_growth"]>2:
        raise ValueError("invalid operating expense bridge")
    revenue=revenue_base*(1+v["revenue_growth"])
    gross_profit=revenue*gross_margin
    opex=opex_h1*2*(1+v["opex_growth"])
    operating_profit=gross_profit-opex
    pretax=operating_profit+v["nonoperating_normalized"]
    aftertax=pretax-max(pretax,0)*v["tax_rate"]
    parent_profit=aftertax-v["minority_profit"]
    eps=parent_profit/v["weighted_diluted_shares_k"]
    target=eps*v["pe"]
    return {"model":"V8.8.0 profit bridge shadow","revenue_2027":round(revenue,3),
            "gross_profit_2027":round(gross_profit,3),
            "operating_profit_2027":round(operating_profit,3),
            "parent_profit_2027":round(parent_profit,3),
            "diluted_eps_2027":round(eps,4),"research_pe":v["pe"],
            "scenario_target_price":round(target,2),
            "scenario_upside_pct":round((target/v["share_price"]-1)*100,2),
            "formal_grade":"NOT_CERTIFIED",
            "assumptions":"H1x2 seasonal-neutral starting point; verify issuer PIT, tax, minority, share dilution, sector PE."}

def self_test():
    x={"revenue_h1":100000,"gross_profit_h1":20000,"operating_profit_h1":10000,
       "net_income_parent_h1":8000,"weighted_diluted_shares_k":10000,
       "share_price":50,"revenue_growth":0.1,"gross_margin_delta":0,
       "opex_growth":0.05,"nonoperating_normalized":0,"tax_rate":0.2,
       "minority_profit":0,"pe":15}
    r=forecast(x)
    assert r["operating_profit_2027"]==23000
    assert r["diluted_eps_2027"]==1.84
    assert r["scenario_target_price"]==27.6
    assert r["formal_grade"]=="NOT_CERTIFIED"
    for bad in (dict(x,weighted_diluted_shares_k=0),dict(x,pe=float("nan")),
                dict(x,gross_margin_delta=0.95)):
        try:forecast(bad)
        except ValueError:pass
        else:raise AssertionError("invalid scenario passed")
    print("SELF_TEST_OK: revenue/gross profit/opex/nonop/tax/minority/dilution/PE")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("scenario",nargs="?")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.scenario:p.error("scenario JSON path required")
        print(json.dumps(forecast(json.loads(Path(a.scenario).read_text(encoding="utf-8"))),ensure_ascii=False,indent=2))
