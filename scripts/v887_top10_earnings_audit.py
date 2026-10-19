#!/usr/bin/env python3
"""V8.8.7 Top10 earnings/cash/CB triage. Research only; never certifies A+."""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

DEFAULT_ROOT = Path("tw-market-data")
REQUIRED = ("revenue_ytd_k", "gross_profit_ytd_k", "operating_profit_ytd_k",
            "net_income_ytd_k", "basic_eps_ytd")

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def numeric(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("INVALID_NUMERIC_" + label)
    return float(value)

def pct(a, b):
    return round(100 * a / b, 2) if b != 0 else None

def index_source(root, period, market, kind):
    path = root / "fundamentals" / period / (market + "_" + kind + ".json")
    if not path.exists():
        raise FileNotFoundError("REQUIRED_MIRROR_MISSING:" + str(path))
    doc = load(path)
    if any((doc.get("period") != period, doc.get("market") != market,
            doc.get("kind") != kind)):
        raise ValueError("QUARTER_MARKET_KIND_MISMATCH:" + str(path))
    sha = str(doc.get("raw_sha256", ""))
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("INVALID_SOURCE_RECEIPT_SHA:" + str(path))
    mapped = {}
    for item in doc.get("rows", []):
        if item.get("period") != period or item.get("market") != market:
            raise ValueError("ISSUER_ROW_PERIOD_MARKET_MISMATCH")
        key = str(item.get("code"))
        if key in mapped:
            raise ValueError("DUPLICATE_ISSUER_IN_MIRROR:" + key)
        if item.get("unit") != "NTD_thousands_except_EPS" or item.get("year_to_date_values") is not True:
            raise ValueError("UNVERIFIED_UNITS_OR_YTD:" + key)
        mapped[key] = item
    return mapped, {"path": str(path), "raw_sha256": sha,
                    "captured_at_utc": doc.get("capture_utc"),
                    "company_PIT_verified": doc.get("company_PIT_verified") is True,
                    "independent_original_audit": False}

def analyze(row, prior, now, cash, oldyear, capital, quarter_num):
    code = str(row["code"])
    if any(x is None for x in (prior, now, cash, oldyear)):
        return {"code": code, "name": row.get("name"), "status": "MISSING_REQUIRED_FINANCIAL_SOURCE",
                "formal_Aplus": False, "flags": ["MISSING_REQUIRED_FINANCIAL_SOURCE"]}
    if not all(str(x.get("code")) == code for x in (prior, now, cash, oldyear)):
        raise ValueError("ISSUER_CODE_CROSS_PERIOD_MISMATCH")
    for report in (prior, now, oldyear):
        for key in REQUIRED:
            numeric(report.get(key), key)
    for key in ("operating_cashflow_ytd_k",):
        numeric(cash.get(key), key)
    a = {k:numeric(now[k],k) for k in REQUIRED}
    b = {k:numeric(prior[k],k) for k in REQUIRED}
    old_eps = numeric(oldyear["basic_eps_ytd"], "prior_fy_eps")
    if a["revenue_ytd_k"] <= 0 or b["revenue_ytd_k"] <= 0:
        raise ValueError("INVALID_REVENUE_DENOMINATOR")
    cf = numeric(cash["operating_cashflow_ytd_k"], "ocf")
    base = row["base"]
    ep = numeric(base.get("eps"), "forward_eps")
    pe = numeric(base.get("pe"), "forward_pe")
    price = numeric(row.get("reference_close"), "reference_close")
    target = numeric(base.get("target_price"), "target_price")
    if price <= 0 or pe <= 0 or target < 0 or abs(target-ep*pe) > 0.03:
        raise ValueError("VALUATION_BRIDGE_INCONSISTENT:" + code)
    gm = pct(a["gross_profit_ytd_k"], a["revenue_ytd_k"])
    oldgm = pct(b["gross_profit_ytd_k"], b["revenue_ytd_k"])
    om = pct(a["operating_profit_ytd_k"], a["revenue_ytd_k"])
    oldom = pct(b["operating_profit_ytd_k"], b["revenue_ytd_k"])
    ytd_eps = a["basic_eps_ytd"]
    run_rate = ytd_eps * 4 / quarter_num
    eps_runrate_multiple = round(ep / run_rate, 3) if run_rate > 0 else None
    co_to_ni = pct(cf, a["net_income_ytd_k"])
    flags = []
    if cf < 0:
        flags.append("NEGATIVE_YTD_OPERATING_CASHFLOW_CHECK_WORKING_CAPITAL")
    elif co_to_ni is not None and a["net_income_ytd_k"] > 0 and co_to_ni < 30:
        flags.append("LOW_OCF_RELATIVE_TO_TOTAL_NET_INCOME")
    if gm - oldgm <= -3:
        flags.append("GROSS_MARGIN_DOWN_AT_LEAST_3PP")
    if om - oldom <= -2:
        flags.append("OPERATING_MARGIN_DOWN_AT_LEAST_2PP")
    if eps_runrate_multiple is not None and eps_runrate_multiple >= 1.30:
        flags.append("FORWARD_EPS_AT_LEAST_30PCT_ABOVE_NONSEASONAL_YTD_RUNRATE")
    if pe >= 20:
        flags.append("FORWARD_PE_AT_LEAST_20_REQUIRES_MATCHED_PEERS")
    if old_eps <= 0:
        flags.append("PRIOR_FULL_YEAR_NONPOSITIVE_EPS_TURNAROUND_TO_VALIDATE")
    if row.get("original_current_issuer_numeric_checked") is not True:
        flags.append("CURRENT_NUMERICS_BULK_ONLY_NOT_ORIGINAL_CHECKED")
    if capital.get("unverified_bond_terms"):
        flags.append("LISTED_CB_TERMS_UNVERIFIED")
    flags.append("MANUAL_FILING_NOTES_AND_PIT_UNVERIFIED")
    out = {
        "code":code,"name":row.get("name"),"rank":None,"market":row.get("market"),
        "prior_fy_basic_eps":round(old_eps,3),
        "prior_ytd_basic_eps":round(b["basic_eps_ytd"],3),
        "latest_ytd_basic_eps":round(ytd_eps,3),
        "ytd_annualized_basic_eps":round(run_rate,3),
        "2027_model_diluted_eps":round(ep,3),
        "2027_eps_over_ytd_runrate":eps_runrate_multiple,
        "latest_ytd_revenue_k":a["revenue_ytd_k"],
        "revenue_yoy_pct":pct(a["revenue_ytd_k"]-b["revenue_ytd_k"],b["revenue_ytd_k"]),
        "gross_margin_prior_pct":oldgm,"gross_margin_latest_pct":gm,
        "gross_margin_delta_pp":round(gm-oldgm,2),
        "operating_margin_prior_pct":oldom,"operating_margin_latest_pct":om,
        "operating_margin_delta_pp":round(om-oldom,2),
        "operating_profit_ytd_k":a["operating_profit_ytd_k"],
        "net_income_total_ytd_k":a["net_income_ytd_k"],
        "operating_cashflow_ytd_k":cf,
        "operating_cashflow_to_total_net_income_pct":co_to_ni,
        "forward_PE":round(pe,3),
        "reference_price":price,
        "model_base_target_price":round(target,2),
        "model_base_upside_pct":pct(target-price,price),
        "double_10pct_stress_price":round(target*.81,2),
        "double_10pct_stress_upside_pct":pct(target*.81-price,price),
        "double_20pct_stress_price":round(target*.64,2),
        "double_20pct_stress_upside_pct":pct(target*.64-price,price),
        "unverified_listed_CB_count":len(capital.get("unverified_bond_terms",[])),
        "formal_Aplus":False,
        "status":"EVIDENCE_TRIAGE_ONLY_NOT_CERTIFIED",
        "flags":flags
    }
    return out

def run(root):
    rankings = root / "rankings"
    research = load(rankings / "latest_research.json")
    progress = load(rankings / "v884_evidence_progress.json")
    if (research.get("estimate_vintage") != progress.get("estimate_vintage")
        or research.get("asof_price_date") != progress.get("asof_price_date")):
        raise ValueError("RESEARCH_EVIDENCE_VINTAGE_MISMATCH")
    if research.get("formal_Aplus_count", 0) != 0 or progress.get("newly_certified_Aplus", 0) != 0:
        raise ValueError("FORMAL_CERTIFICATION_MUST_BE_HANDLED_BY_MAIN_ENGINE")
    quarter = str(research.get("financial_last_quarter",""))
    import re
    m = re.fullmatch(r"(20\d{2})-Q([1-4])",quarter)
    if m is None:
        raise ValueError("UNKNOWN_FINANCIAL_QUARTER")
    year, q = int(m.group(1)), int(m.group(2))
    previous = f"{year-1}-Q{q}"
    previous_fy = f"{year-1}-Q4"
    mirrors, receipts = {}, []
    for period in (previous,quarter,previous_fy):
        for market in ("TWSE","TPEX"):
            for kind in (("income","cashflow") if period==quarter else ("income",)):
                key=(period,market,kind)
                if key not in mirrors:
                    mirrors[key], receipt = index_source(root,period,market,kind)
                    receipts.append(receipt)
    top = research.get("top10_market_research", [])
    if len(top) != 10 or len(set((r.get("market"),str(r.get("code"))) for r in top))!=10:
        raise ValueError("TOP10_DUPLICATE_OR_INCOMPLETE")
    evidence = {(x.get("market"),str(x.get("code"))):x for x in progress.get("top_priority_evidence",[])}
    out=[]
    for position, row in enumerate(top,1):
        market,code=row.get("market"),str(row.get("code"))
        if market not in ("TWSE","TPEX"):
            raise ValueError("INVALID_MARKET")
        capital=evidence.get((market,code),{}).get("capital",{})
        entry=analyze(row,
            mirrors[(previous,market,"income")].get(code),
            mirrors[(quarter,market,"income")].get(code),
            mirrors[(quarter,market,"cashflow")].get(code),
            mirrors[(previous_fy,market,"income")].get(code),
            capital,q)
        entry["rank"]=position
        entry["source_tier"]=row.get("source_tier")
        out.append(entry)
    result={
        "model":research.get("model"),"estimate_vintage":research.get("estimate_vintage"),
        "asof_price_date":research.get("asof_price_date"),
        "financial_period":quarter,"prior_comparable":previous,
        "financial_sources":receipts,
        "ranked_diagnostics":out,
        "all_ten_financial_mirrors_present":all(x["status"]=="EVIDENCE_TRIAGE_ONLY_NOT_CERTIFIED" for x in out),
        "formal_Aplus_added":0,"valuation_or_rankings_modified":False,
        "automatic_formal_gate_PASS_added":0,
        "limitations":[
            "Historical company-specific release PIT is not independently authenticated; capture receipts are not original legal attestation.",
            "Basic YTD EPS annualization is seasonal-neutral context only, not a 2027 forecast or the diluted forward denominator.",
            "OCF/total consolidated net income is a screening ratio, not recurring profit, FCF or a substitute for working-capital notes.",
            "CB absence in listed summary is not proof of no other dilution; conversion terms and weighted shares require legal review.",
            "Double 10% and double 20% EPS-PE stresses are independent sensitivity arithmetic; not probabilities or model Base revisions.",
            "PE needs matched sector validation. No valuation, entry trade or A+ certification is approved by this triage."
        ]}
    dst=rankings/"v887_top10_earnings_audit.json"
    dst.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    def val(v,suffix=""):
        return "待驗" if v is None else f"{v:.2f}{suffix}"
    lines=["# V8.8.7 2027 Top10 獲利品質預檢（不修改正式排名）","",
           f"形成：{result['estimate_vintage']}；收盤基準：{result['asof_price_date']}；財報：{quarter}。","",
           "十檔只完成已有官方來源鏡像的數字交叉分析；不表示原始財報附註、CB法律條款、PIT、流動性已簽核。**正式新增A+：0。**","",
           "|原序|公司|2025FY EPS|2026 YTD EPS|2027 模型EPS|YTD營收YoY|毛利率上期→本期|現金流(億)|訊號數|",
           "|---:|---|---:|---:|---:|---:|---|---:|---:|"]
    for a in out:
        ocf=a.get("operating_cashflow_ytd_k")
        cf=f"{ocf/100000:.2f}" if ocf is not None else "待補"
        lines.append(f"|{a['rank']}|{a['code']} {a.get('name') or ''}|{val(a.get('prior_fy_basic_eps'))}|{val(a.get('latest_ytd_basic_eps'))}|{val(a.get('2027_model_diluted_eps'))}|{val(a.get('revenue_yoy_pct'),'%')}|{val(a.get('gross_margin_prior_pct'))}%→{val(a.get('gross_margin_latest_pct'))}%|{cf}|{len(a['flags'])}|")
    lines+=["","## 估值下修壓力測試","",
            "以下 EPS 與 PE 同時下修的情境只是計算敏感度，**沒有**自動改寫模型 Base。",
            "|公司|Base漲幅|EPS、PE各-10%|EPS、PE各-20%|2027 EPS/YTD年化EPS|",
            "|---|---:|---:|---:|---:|"]
    for a in out:
        lines.append(f"|{a['code']} {a.get('name') or ''}|{val(a.get('model_base_upside_pct'),'%')}|{val(a.get('double_10pct_stress_upside_pct'),'%')}|{val(a.get('double_20pct_stress_upside_pct'),'%')}|{val(a.get('2027_eps_over_ytd_runrate'))}倍|")
    lines+=["","## 待補證據（依原始順位）",""]
    for a in out:
        lines.append(f"- {a['code']} {a.get('name') or ''}："+("、".join(a["flags"]) if a["flags"] else "未驗證完整原件"))
    lines+=["","## 限制",""]+["- "+s for s in result["limitations"]]
    (rankings/"v887_top10_earnings_audit.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"status":"RESEARCH_EVIDENCE_DIAGNOSTIC_ONLY","financial_period":quarter,
                      "audited_n":len(out),"negative_OCF_codes":[x["code"] for x in out if x.get("operating_cashflow_ytd_k") is not None and x["operating_cashflow_ytd_k"] < 0],
                      "formal_Aplus_added":0},ensure_ascii=False))
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="tw-market-data")
    args=p.parse_args()
    run(Path(args.data_dir))

if __name__=="__main__":
    main()
