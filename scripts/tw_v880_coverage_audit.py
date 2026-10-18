#!/usr/bin/env python3
"""V8.8.0 full-universe coverage audit; evidence coverage is NOT formal A+."""
import argparse
import json
from pathlib import Path

def audit(scan):
    if not isinstance(scan,dict):raise ValueError("invalid financial scan manifest")
    total=scan.get("companies_with_some_data")
    full=scan.get("companies_with_full_8Q_income")
    batches=scan.get("verified_batches")
    missing=scan.get("missing_batches")
    if any(type(x) is not int or x<0 for x in (total,full,batches,missing)):
        raise ValueError("invalid count fields")
    if full>total:raise ValueError("8-quarter issuers exceed issuer universe")
    if batches+missing!=scan.get("expected_market_quarter_statement_batches"):
        raise ValueError("batch coverage inconsistent")
    if scan.get("formal_Aplus_count")!=0 or scan.get("formal_Aplusplus_count")!=0:
        raise ValueError("uncertified A+ in financial scan")
    return {"model":"V8.8.0 coverage audit","asof":scan.get("asof_taipei"),
            "companies_with_some_data":total,"mirror_full_8q_income":full,
            "missing_8q_income_or_incomplete":total-full,
            "mirror_income_coverage_pct":round(100*full/total,2) if total else 0,
            "batches_present":batches,"missing_batches":missing,
            "original_issuer_8q_PIT_certified":False,
            "formal_Aplus_count":0,"formal_Aplusplus_count":0,
            "status":"RESEARCH_MIRROR_ONLY_NOT_FORMAL"}

def self_test():
    x={"companies_with_some_data":1978,"companies_with_full_8Q_income":1887,
       "verified_batches":32,"missing_batches":0,"expected_market_quarter_statement_batches":32,
       "formal_Aplus_count":0,"formal_Aplusplus_count":0}
    r=audit(x)
    assert r["missing_8q_income_or_incomplete"]==91
    assert r["original_issuer_8q_PIT_certified"] is False
    for bad in (dict(x,companies_with_full_8Q_income=2000),
                dict(x,missing_batches=1),dict(x,formal_Aplus_count=1)):
        try:audit(bad)
        except ValueError:pass
        else:raise AssertionError("invalid coverage accepted")
    print("SELF_TEST_OK: 1978 universe, 1887 mirror 8Q, 91 incomplete")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("manifest",nargs="?")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.manifest:p.error("manifest path required")
        print(json.dumps(audit(json.loads(Path(a.manifest).read_text(encoding="utf-8"))),ensure_ascii=False,indent=2))
