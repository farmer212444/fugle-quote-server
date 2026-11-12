#!/usr/bin/env python3
"""2027 scenario ranking restricted to actual 0050 2026-10-22 holdings.

Research-only: no recommendation, no backtest, no live orders, no modifications
to V8.10.8 input data or formal A+ gates.
"""
import csv
import gzip
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PRICE_DATE = "2026-10-22"
MODEL_VERSION = "V8.10.8"
# Periods and sources are separate from the model's own FY2027 estimates.
# These independently published earnings are OBSERVATIONS, not a new projection.
PUBLIC_EPS_OBSERVATIONS = {
    "2317": {
        "period": "2026-H1", "months": 6, "eps": 7.84, "audited": False,
        "source_url": "https://www.foxconn.com.tw/zh-tw/press-center/press-releases/latest-news/2094",
        "published_on": "2026-08-12", "source_type": "ISSUER_H1_RELEASE",
        "warning": "H1_X2_IGNORES_STRONG_CONSUMER_ELECTRONICS_H2_SEASONALITY"
    },
    "2382": {
        "period": "2026-H1", "months": 6, "eps": 12.93, "audited": False,
        "source_url": "https://goodinfo.tw/tw/StockAnnounceDetail.asp?STOCK_ID=2382",
        "published_on": "2026-08-13", "source_type": "ISSUER_DISCLOSURE_MIRROR_H1",
        "warning": "H1_X2_IGNORES_AI_RAMP_SEASONALITY_AND_DECLINING_GROSS_MARGIN"
    },
    "6505": {
        "period": "2026-9M", "months": 9, "eps": 7.08, "audited": False,
        "source_url": "https://wwwc.twse.com.tw/IIH2/zh/company/information.html?code=6505",
        "published_on": "2026-10-12", "source_type": "COMPANY_Q3_SELF_REPORTED_UNAUDITED",
        "warning": "REFINING_SPREAD_UTILIZATION_AND_INVENTORY_GAINS_CANNOT_BE_EXTRAPOLATED"
    },
}

def mechanical_sensitivity(close, target, eps, pe):
    """Counterfactual simultaneous EPS/PE haircuts, NOT calibrated probabilities."""
    if not all(proper_positive(x) for x in (close, target, eps, pe)):
        raise ValueError("INVALID_PRICE_OR_EARNINGS_FOR_STRESS")
    if abs(eps * pe - target) > 0.01:
        raise ValueError("BASE_TARGET_NOT_EQUAL_EPS_TIMES_PE")
    return {
        "upside_eps_pe_both_minus_10_pct": round(100 * (.9*.9*target/close-1), 2),
        "upside_eps_pe_both_minus_20_pct": round(100 * (.8*.8*target/close-1), 2),
        "minimum_2027_eps_for_30_pct_upside_at_base_pe": round(1.3*close/pe, 2),
        "minimum_2027_eps_for_break_even_at_base_pe": round(close/pe, 2),
        "can_keep_30_pct_upside_under_20_20_stress": .64*target/close >= 1.3,
    }
CODES = (
    "2330 2454 2308 2317 3711 1303 2383 2303 3037 2891 "
    "2881 2882 3017 2887 2345 2382 2885 2884 2327 2360 "
    "2886 2357 2890 3443 2412 2883 3008 6669 3231 2059 "
    "2408 3653 2301 2344 2892 2880 4958 1216 2368 6446 "
    "3665 8046 5880 2395 2449 7769 2603 4904 3045 6505"
).split()

def proper_positive(v):
    return isinstance(v,(float,int)) and v>0

def snapshot(base=ROOT/"tw-market-data", out=Path("/tmp/0050-2027")):
    if len(CODES)!=50 or len(set(CODES))!=50:raise ValueError("0050_SCOPE_MUST_EQUAL_50")
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    compact=json.loads((base/"rankings/latest_research.json").read_text())
    if compact["model"]!=MODEL_VERSION or compact["asof_price_date"]!=PRICE_DATE:
        raise ValueError("MODEL_OR_PRICE_VINTAGE_DIFFERENT_FROM_2026_10_22_HOLDINGS")
    raw=gzip.decompress((base/"rankings/v880_full_results.json.gz").read_bytes())
    sha=hashlib.sha256(raw).hexdigest()
    if sha != compact["full_results"]["json_sha256"]:
        raise ValueError("FULL_RESULTS_SHA256_MISMATCH")
    expanded=json.loads(raw)
    rows=expanded.get("all_model_rows")
    if not isinstance(rows,list):raise ValueError("MISSING_FULL_UNIVERSE")
    by_code={}
    for r in rows:
        code=str(r.get("code",""))
        if code in by_code:raise ValueError("DUPLICATE_ISSUER_CODE")
        by_code[code]=r
    missing=[code for code in CODES if code not in by_code]
    if missing:raise ValueError("0050_ISSUERS_NOT_IN_MODEL:"+",".join(missing))
    base_rows=[];excluded=[]
    for code in CODES:
        rec=by_code[code]
        scenario=rec.get("base") or {}
        valid=(rec.get("rankable") is True and proper_positive(rec.get("reference_close"))
               and proper_positive(scenario.get("eps")) and proper_positive(scenario.get("pe"))
               and proper_positive(scenario.get("target_price"))
               and isinstance(scenario.get("price_upside_pct"),(float,int)))
        if valid:
            close=rec["reference_close"];target=scenario["target_price"]
            upside=100*(target/close-1)
            if abs(upside-scenario["price_upside_pct"])>0.001:
                raise ValueError("UPSIDE_NOT_REPRODUCED_"+code)
            def target_for_scenario(label):
                s=rec.get(label) or {}
                return s.get("target_price") if proper_positive(s.get("target_price")) else None
            row={
                "code":code,"name":rec.get("name"),"reference_price_date":PRICE_DATE,
                "reference_close":round(close,2),
                "eps_2027_base":round(scenario["eps"],2),
                "pe_2027_base":round(scenario["pe"],2),
                "target_2027_base":round(target,2),
                "upside_2027_base_pct":round(upside,2),
                "bear_price":round(target_for_scenario("bear"),2) if target_for_scenario("bear") is not None else None,
                "bull_price":round(target_for_scenario("bull"),2) if target_for_scenario("bull") is not None else None,
                "source_tier":rec.get("source_tier"),
                "formal_Aplus":bool(rec.get("formal_Aplus",False)),
                "key_model_warnings":(rec.get("warning_flags") or [])[:5],
                "estimated_total_return_pct":None,
            }
            row.update(mechanical_sensitivity(close,target,scenario["eps"],scenario["pe"]))
            row["model_financial_period"] = rec.get("financial_period")
            row["model_eps_pe_stress_is_not_forecast"] = True
            # Observations NEVER modify the existing base EPS/PE/target/rank.
            if code in PUBLIC_EPS_OBSERVATIONS:
                obs = PUBLIC_EPS_OBSERVATIONS[code]
                annualized = obs["eps"] * 12 / obs["months"]
                row["published_earnings_observation"] = {
                    **obs,
                    "simple_annualized_eps_not_forecast": round(annualized,2),
                    "base_2027_eps_vs_linear_runrate_pct":
                        round(100*(scenario["eps"]/annualized-1),2),
                    "newer_than_model_financial_period":
                        code=="6505" and rec.get("financial_period")=="2026-Q2",
                    "changes_existing_base_rank": False,
                    "source_document_original_bytes_independently_audited":False
                }
            base_rows.append(row)
        else:
            excluded.append({"code":code,"name":rec.get("name"),"model_status":rec.get("status"),
                             "rankable":rec.get("rankable"),
                             "exclusion_reasons":rec.get("exclusion_reasons",[])})
    base_rows.sort(key=lambda x:x["upside_2027_base_pct"],reverse=True)
    top=base_rows[:10]
    for i,r in enumerate(top,1):r["rank_0050_by_model"]=i
    compact_rows={r["code"]:r for r in compact.get("all_model_row_summary",[])}
    for r in top:
        other=compact_rows.get(r["code"])
        if not other or abs(other["scenario_upside_pct"]-r["upside_2027_base_pct"])>0.011:
            raise ValueError("LATEST_COMPACT_RANKING_MISMATCH_"+r["code"])
    output={
        "schema":"V8108_0050_ASOF20261022_2027_BASE_RESEARCH_TOP10",
        "model":compact["model"],
        "model_estimate_vintage":compact["estimate_vintage"],
        "price_asof":PRICE_DATE,
        "holdings_source":"https://www.yuantaetfs.com/product/detail/0050/ratio",
        "holdings_crosscheck":"https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid=0050.TW",
        "holdings_count":len(CODES),
        "rankable":len(base_rows),
        "excluded":len(excluded),
        "official_full_results_json_sha256":sha,
        "strategy":"MODEL_2027_BASE_TARGET_DIVIDED_BY_2026_10_22_CLOSE",
        "formal_Aplus_count":sum(r["formal_Aplus"] for r in top),
        "research_only_not_forward_return":True,
        "mechanical_stress_rule":"EPS_AND_PE_EACH_DOWN_10_OR_20_PERCENT_NOT_NEW_BASE",
        "real_earnings_obs_are_context_only":True,
        "source_documents_original_bytes_independently_audited":False,
        "ranking_passes_30pct_after_20_20_stress":sum(
            1 for row in top if row["can_keep_30_pct_upside_under_20_20_stress"]),
        "dividends_and_transaction_costs_included":False,
        "excluded_issuers":excluded,
        "top10":top,
        "all_comparable_0050":base_rows
    }
    (out/"top10_2027.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n")
    with (out/"top10_2027.csv").open("w",encoding="utf-8-sig",newline="") as file:
        cols=["rank_0050_by_model","code","name","reference_close","eps_2027_base",
              "pe_2027_base","target_2027_base","upside_2027_base_pct",
              "bear_price","bull_price","source_tier",
              "upside_eps_pe_both_minus_10_pct","upside_eps_pe_both_minus_20_pct",
              "minimum_2027_eps_for_30_pct_upside_at_base_pe"]
        writer=csv.DictWriter(file,fieldnames=cols,extrasaction="ignore")
        writer.writeheader();writer.writerows(top)
    print(json.dumps({
        "holdings_count":len(CODES),"rankable":len(base_rows),"excluded":len(excluded),
        "top10":top,"excluded_issuers":excluded
    },ensure_ascii=False))
    return output

if __name__=="__main__":
    snapshot()
