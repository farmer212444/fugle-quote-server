#!/usr/bin/env python3
"""Optional no-lookahead research for V8.8.1's excluded thin-turnover companies.

Does NOT change latest_research.json, primary Top10, the official A+ certificate
rules, or the observed issuer data. Share and security-master data must exist.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tw_v880_run import public_row
from tw_model_v880.data import MarketData
from tw_model_v880.calibration import fit_accounting
from tw_model_v880.model import estimate, RESEARCH_MIN_TURNOVER_NTD
from tw_model_v880.math import number

def discover_shadow(data, report, calibrated):
    modeled_codes = {str(r["code"]) for r in report["all_model_row_summary"]}
    filtered_codes = {str(r["code"]) for r in report["all_model_row_summary"]
                      if r.get("status") in ("PRICE_FILTER_BELOW_8_TWD", "TURNOVER_FILTER_BELOW_1M_TWD")}
    examined, eligible, shadow, failures = 0, 0, [], []
    asof = report["estimate_vintage"]
    target = report["target_date"]
    master = data.evidence.get("master", {})
    for (market, code), history in sorted(data.history.items()):
        if code in modeled_codes and code not in filtered_codes:
            continue
        examined += 1
        p = data.prices.get((market, code))
        if (data.period not in history or p is None or code not in data.revenue
                or code not in master):
            continue
        close = number(p.get("close"))
        volume = number(p.get("volume_shares"))
        if close is None or volume is None or close <= 0:
            continue
        if not (close < 8 or close * volume < RESEARCH_MIN_TURNOVER_NTD):
            failures.append({"market":market,"code":code,"reason":"UNEXPECTED_NON_THIN_MODEL_EXCLUSION"})
            continue
        eligible += 1
        try:
            row = estimate(data, (market, code), calibrated, asof, target,
                           shadow_thin=True)
            if row is not None:
                if row.get("rankable") or row.get("formal_Aplus") or row.get("formal_Aplusplus"):
                    raise ValueError("THIN_SHADOW_MUST_NEVER_BE_CERTIFIED_OR_PRIMARY_RANKED")
                shadow.append(row)
        except (ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError) as exc:
            failures.append({"market":market,"code":code,"reason":str(exc)})
    return examined, eligible, shadow, failures

def build(data_dir, research_path, output):
    report = json.loads(pathlib.Path(research_path).read_text(encoding="utf-8"))
    data = MarketData(data_dir, report["estimate_vintage"])
    sector = {c:r.get("industry", "") for c,r in data.revenue.items()}
    calibrated = fit_accounting(data.history, data.period, sector)
    n, e, rows, failures = discover_shadow(data, report, calibrated)
    scored = sorted([r for r in rows if r.get("point_valuation_available")
                     and r.get("base", {}).get("price_upside_pct") is not None],
                    key=lambda r:r["base"]["price_upside_pct"], reverse=True)
    result = {
        "model":report["model"],"estimate_vintage":report["estimate_vintage"],
        "reference_price_date":report["asof_price_date"],"target_date":report["target_date"],
        "normalized_nonmodeled_examined":n,"thin_price_eligible_for_shadow":e,
        "shadow_model_rows":len(rows),"shadow_point_valuation_rows":len(scored),
        "input_model_primary_top10_unchanged":True,
        "source_primary_top10_codes":[r["code"] for r in report.get("top10_primary_research", [])],
        "formal_Aplus_from_shadow":0,"thin_company_tradability_verified":False,
        "PIT_master_verified":False,"certified_marketwide_top10":False,
        "shadow_valuation_role":"INDEPENDENT_RESEARCH_DIAGNOSTIC_ONLY_UNTRADEABLE_UNTIL_MULTI_SESSION_LIQUIDITY_CHECK",
        "top30_thin_shadow": [public_row(x) for x in scored[:30]],
        "shadow_status_counts": {s:sum(r.get("status")==s for r in rows)
                                 for s in sorted({r.get("status") for r in rows})},
        "issuer_failures":failures,
        "all_thin_shadow": [{"market":r.get("market"),"code":r["code"],"name":r.get("name"),
                             "status":r.get("status"),
                             "point_price":r.get("base", {}).get("target_price"),
                             "price_upside_pct":r.get("base", {}).get("price_upside_pct"),
                             "warning_flags":r.get("warning_flags",[]),
                             "formal_Aplus":False,"rankable":False} for r in rows]
    }
    out = pathlib.Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("normalized_nonmodeled_examined",
                                            "thin_price_eligible_for_shadow",
                                            "shadow_model_rows","shadow_point_valuation_rows",
                                            "formal_Aplus_from_shadow")},
                     ensure_ascii=False))
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="tw-market-data")
    p.add_argument("--research",default="tw-market-data/rankings/latest_research.json")
    p.add_argument("--output",default="tw-market-data/rankings/v881_thin_shadow.json")
    args=p.parse_args()
    build(args.data_dir,args.research,args.output)

if __name__=="__main__":
    main()
