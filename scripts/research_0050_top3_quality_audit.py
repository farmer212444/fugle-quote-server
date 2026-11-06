#!/usr/bin/env python3
"""Reproducible 0050 Top-3 valuation risk audit; does not certify returns or A+.

Uses V8.10.8 original research model bytes. Public issuer announcements listed
below are context inputs, not proof that 2027 earnings will materialize.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

OFFICIAL_DISCLOSURE_OBSERVATIONS = {
    "2317": {
        "last_known_earnings_period": "2026-H1",
        "reported_eps": 7.84,
        "revenue_ytd_yoy_pct": 39.53,
        "h1_gross_margin_pct": 6.15,
        "h1_operating_margin_pct": 3.67,
        "source_url": "https://www.foxconn.com.tw/zh-tw/press-center/press-releases/latest-news/2094",
        "monthly_revenue_url": "https://www.honhai.com.tw/zh-tw/investor-relations/financial-information/reports?category=monthly",
        "available_by": "2026-10-05",
        "watch": ["2027 AI-rack volume-to-parent-profit bridge",
                  "inventories / receivables / cash-conversion cycle",
                  "2027 net margin and FX assumptions"],
    },
    "2382": {
        "last_known_earnings_period": "2026-H1",
        "reported_eps": 12.93,
        "revenue_ytd_yoy_pct": 99.41,
        "h1_gross_margin_pct": 4.92,
        "new_ordinary_shares_effective_2026_09_08": 245000000,
        "ordinary_shares_before_issuance": 3862627432,
        "ordinary_shares_after_issuance": 4107627432,
        "source_url": "https://goodinfo.tw/tw/StockAnnounceDetail.asp?CLAIM_TIME=2026%2F08%2F13+14%3A30%3A31&STOCK_ID=2382&SUBJECT=%E5%85%AC%E5%91%8A%E6%9C%AC%E5%85%AC%E5%8F%B8%E8%91%A3%E4%BA%8B%E6%9C%83%E9%80%9A%E9%81%8E115%E5%B9%B4%E7%AC%AC%E4%BA%8C%E5%AD%A3%E8%B2%A1%E5%8B%99%E5%A0%B1%E5%91%8A",
        "monthly_revenue_url": "https://tw.stock.yahoo.com/news/%E5%85%AC%E5%91%8A-%E5%BB%A3%E9%81%94-2026%E5%B9%B49%E6%9C%88%E5%90%88%E4%BD%B5%E7%87%9F%E6%94%B63253%E5%84%84%E5%85%83-%E5%B9%B4%E5%A2%9E76-69-072341501.html",
        "issuance_url": "https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=31fa3db0-def1-44dd-8f66-e94681835c1a",
        "available_by": "2026-10-07",
        "watch": ["MUST reconcile new 4,107,627,432 shares vs model EPS denominator",
                  "rack sales growth vs low-single-digit gross margin",
                  "overseas capacity funding, tax and one-time effects"],
    },
    "6505": {
        "last_known_earnings_period": "2026-9M",
        "reported_eps": 7.08,
        "revenue_ytd_yoy_pct": 22.03,
        "q3_inventory_valuation_reversal_ntd_billion": 2.79,
        "source_url": "https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=59ee37d9-5c28-4a08-ac01-bbd63c91ef79",
        "available_by": "2026-10-12",
        "watch": ["oil crack-spread normalization, not a structural AI growth stock",
                  "purchase / inventory gains and losses can reverse",
                  "petrochemical olefin utilization and external demand"],
    },
}


def q(v, digits=2):
    return None if v is None else round(v, digits)


def target(eps, pe):
    if not isinstance(eps,(int,float)) or not isinstance(pe,(int,float)):
        raise ValueError("NONNUMERIC_EPS_PE")
    if not math.isfinite(eps) or not math.isfinite(pe) or eps<=0 or pe<=0:
        raise ValueError("INVALID_EPS_PE")
    return eps * pe


def pct(value, close):
    if close<=0:raise ValueError("INVALID_PRICE")
    return 100*(value/close-1)


def build(root):
    root=Path(root)
    compact=json.loads((root/"rankings/latest_research.json").read_text(encoding="utf-8"))
    blob=gzip.decompress((root/"rankings/v880_full_results.json.gz").read_bytes())
    digest=hashlib.sha256(blob).hexdigest()
    if digest!=compact["full_results"]["json_sha256"]:
        raise ValueError("MODEL_ORIGINAL_HASH_MISMATCH")
    model=json.loads(blob)
    if model["model"]!="V8.10.8" or compact["asof_price_date"]!="2026-10-22":
        raise ValueError("WRONG_ESTIMATE_VINTAGE")
    rows={r["code"]:r for r in model["all_model_rows"]}
    report=[]
    for code,observed in OFFICIAL_DISCLOSURE_OBSERVATIONS.items():
        r=rows[code]
        if not r["rankable"] or r.get("formal_Aplus"):
            raise ValueError("UNEXPECTED_0050_ISSUER_GATE_STATE")
        base=r["base"]
        close=r["reference_close"]
        if abs(base["target_price"]-target(base["eps"],base["pe"]))>0.01:
            raise ValueError("MODEL_BASE_ARITHMETIC_INCONSISTENT_"+code)
        scenarios={
            "original_model": {"eps":q(base["eps"]), "pe":q(base["pe"]),
                               "target":q(target(base["eps"],base["pe"])),
                               "upside_pct":q(pct(target(base["eps"],base["pe"]),close))},
            "eps_pe_each_minus_20pct": {
                "eps":q(.8*base["eps"]), "pe":q(.8*base["pe"]),
                "target":q(.64*base["target_price"]),
                "upside_pct":q(pct(.64*base["target_price"],close))},
        }
        details={
            "code":code,"name":r["name"],
            "reference_close":close,
            "2027_model_net_profit_k":q(base.get("parent_profit_k"),3),
            "2027_model_shares":base.get("shares"),
            "2027_model_eps":base["eps"],
            "model_source_tier":r.get("source_tier"),
            "financial_period":r.get("financial_period"),
            "current_original_notes_verified":False,
            "formal_Aplus":False,
            "actual_verified_investment_return":None,
            "disclosure":observed,
            "scenarios":scenarios,
            "source_2027_not_independently_certified":True,
            "model_warning_flags":r.get("warning_flags",[])
        }
        if code in ("2317","2382"):
            # Just a growth plausibility comparator. Does NOT predict full-year EPS:
            # seasonality, GDR denominators and one-off earnings differ.
            details["2027_model_eps_divided_by_double_H1_reported_eps"]=q(
                base["eps"]/(2*observed["reported_eps"]),4)
            details["annualizing_H1_is_not_an_earnings_forecast"]=True
        if code=="2382":
            new=observed["ordinary_shares_after_issuance"]
            old=observed["ordinary_shares_before_issuance"]
            if new-old!=observed["new_ordinary_shares_effective_2026_09_08"]:
                raise ValueError("GDR_SHARE_COUNT_INCONSISTENT")
            shares=base.get("shares")
            shares_ok=isinstance(shares,(int,float)) and shares>=new
            details["gdr_post_issue_share_basis_pass"]=shares_ok
            details["gdr_model_denominator_review"]="PASS_MECHANICAL_SHARE_COUNT_ONLY" if shares_ok \
                else "BLOCK_MODEL_2027_EPS_MAY_IGNORE_EFFECTIVE_GDR"
            details["gdr_pct_of_postissue_shares"]=q(100*(new-old)/new)
            details["gdr_mechanical_2027_eps_fixed_profit"]=q(
                1000*base["parent_profit_k"]/max(shares if isinstance(shares,(int,float)) else 0,new))
            # 2026 H1 EPS reported with time-weighted, pre-issuance denominator;
            # comparison here is illustrative, not a restated EPS filing.
            details["2026_H1_eps_at_fully_diluted_shares_illustrative"]=q(
                observed["reported_eps"]*old/new)
        if code=="6505":
            details["industry_cycle_PE_sensitivity_FIXED_model_EPS"]=[
                {"pe":pe, "price":q(target(base["eps"],pe)),
                 "upside_pct":q(pct(target(base["eps"],pe),close))}
                for pe in (8,10,12,14,16,18)
            ]
            details["illustrative_earnings_normalization_NOT_A_FORECAST"]=[
                {"eps":eps,"pe":pe,"target":q(target(eps,pe)),
                 "upside_pct":q(pct(target(eps,pe),close))}
                for eps,pe in [(6,10),(7,12),(8,12),(9,14)]
            ]
        report.append(details)
    return {
        "schema":"RESEARCH_0050_TOP3_2027_ISSUER_DISCLOSURE_AUDIT_V1",
        "vintage":compact["estimate_vintage"],
        "price_reference_date":compact["asof_price_date"],
        "original_model_digest":digest,
        "research_only":True,
        "Aplus_unchanged":True,
        "not_yet_fully_issuer_PIT_verified":True,
        "no_autotrading":True,
        "observations":report,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",default="tw-market-data")
    p.add_argument("--output",default="/tmp/0050-top3-risk-audit.json")
    args=p.parse_args()
    out=build(args.root)
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "model":out["vintage"],
        "quality_diagnostics":[{
            "code":r["code"],"name":r["name"],"2027_model_eps":q(r["2027_model_eps"]),
            "model_shares":r["2027_model_shares"],
            "gdr_model_denominator_review":r.get("gdr_model_denominator_review"),
            "model_base":r["scenarios"]["original_model"],
            "eps_pe_minus_20":r["scenarios"]["eps_pe_each_minus_20pct"],
            "cycle_sensitivity":r.get("industry_cycle_PE_sensitivity_FIXED_model_EPS"),
            "reported_period":r["disclosure"]["last_known_earnings_period"],
            "reported_eps":r["disclosure"]["reported_eps"]
        } for r in out["observations"]]
    },ensure_ascii=False))


if __name__=="__main__":
    main()
