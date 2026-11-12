#!/usr/bin/env python3
"""V8.8.0 point-in-time walk-forward signal audit. No hindsight prices or formal grades."""
import argparse
import json
from datetime import date
from pathlib import Path

def day(value):
    if not isinstance(value,str):raise ValueError("date must be ISO string")
    d=date.fromisoformat(value)
    if d.isoformat()!=value:raise ValueError("noncanonical date")
    return d

def audit(records):
    if not isinstance(records,list):raise ValueError("records must be a list")
    seen=set()
    outputs=[]
    for row in records:
        if not isinstance(row,dict):raise ValueError("record must be object")
        code=str(row.get("code",""))
        decision=day(row.get("decision_date"))
        released=day(row.get("financial_publication_date"))
        price_date=day(row.get("entry_price_date"))
        key=(code,decision)
        if not (len(code)==4 and code.isascii() and code.isdigit()) or key in seen:
            raise ValueError("invalid or duplicate issuer/decision")
        seen.add(key)
        if released>decision:raise ValueError("LOOKAHEAD: financial statement released after decision")
        if price_date>decision:raise ValueError("LOOKAHEAD: price snapshot after decision")
        if row.get("issuer_original_verified") is not True:
            outputs.append({"code":code,"decision_date":str(decision),"status":"EXCLUDED_UNVERIFIED_ORIGINAL"})
            continue
        exit_date=day(row.get("exit_price_date"))
        if exit_date<=decision:raise ValueError("exit must occur after decision")
        entry=row.get("entry_price")
        exit_price=row.get("exit_price")
        if (type(entry) not in (int,float) or type(exit_price) not in (int,float)
                or not 0<entry<1e9 or not 0<exit_price<1e9):
            raise ValueError("invalid prices")
        outputs.append({"code":code,"decision_date":str(decision),"status":"PIT_ELIGIBLE",
                        "gross_return_pct":round((exit_price/entry-1)*100,4),
                        "warning":"Gross price-only return, not net of fees, dividends, slippage or market benchmark"})
    return {"model":"V8.8.0 PIT walk-forward audit",
            "total":len(outputs),"eligible":sum(x["status"]=="PIT_ELIGIBLE" for x in outputs),
            "excluded":sum(x["status"]!="PIT_ELIGIBLE" for x in outputs),
            "records":outputs,"formal_Aplus_count":0,"formal_Aplusplus_count":0,
            "warning":"No historical backtest result unless genuine dated records supplied."}

def self_test():
    a={"code":"9802","decision_date":"2026-07-31","financial_publication_date":"2026-05-15",
       "entry_price_date":"2026-07-31","issuer_original_verified":True,
       "exit_price_date":"2026-10-16","entry_price":80,"exit_price":88}
    assert audit([a])["records"][0]["gross_return_pct"]==10
    assert audit([dict(a,issuer_original_verified=False)])["excluded"]==1
    for bad in (dict(a,financial_publication_date="2026-08-15"),
                dict(a,entry_price_date="2026-08-01"),
                dict(a,exit_price_date="2026-07-30")):
        try:audit([bad])
        except ValueError:pass
        else:raise AssertionError("lookahead accepted")
    print("SELF_TEST_OK: PIT publication, price dates, issuer originals, exit chronology")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("records",nargs="?")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.records:p.error("historical records JSON required")
        print(json.dumps(audit(json.loads(Path(a.records).read_text(encoding="utf-8"))),ensure_ascii=False,indent=2))
