#!/usr/bin/env python3
"""6206 primary-source-linked operating-bridge shadow valuation; not certified A+.

Uses Flytech IR presentation page text, dated official 9M monthly revenue and
official archived closing price. This does not alter the common-universe model.
"""
import datetime as dt
import gzip
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tw_model_v880.math import operating_scenario, returns

DATA=Path("tw-market-data")
CODE="6206"
SCENARIOS={
 "bear":dict(revenue_m=6900,gross_margin=.43,opex_ratio=.19,nonop_m=-140,tax=.20,pe=12),
 "base":dict(revenue_m=7600,gross_margin=.45,opex_ratio=.17,nonop_m=-50,tax=.20,pe=16),
 "bull":dict(revenue_m=8400,gross_margin=.46,opex_ratio=.158,nonop_m=-20,tax=.20,pe=18)
}
COMMON_SHARE_PROXY_M=143.1  # 2026/03 official investor slide, not diluted certification
FORECAST_2026_FULL_YEAR_M=6600

def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def require(cond,msg):
    if not cond:raise ValueError(msg)

def positive(v):
    try:
        if isinstance(v,bool):return None
        x=float(v)
        return x if math.isfinite(x) and x>0 else None
    except (TypeError,ValueError):return None

def observe(manifest,date_token):
    items=[x for x in manifest.get("presentations",[]) if
           x.get("event_date")==date_token and x.get("code")==CODE]
    require(len(items)==1,"INVESTOR_SLIDE_EVENT_IDENTITY_MISSING_OR_DUPLICATE")
    x=items[0]
    require(x.get("source_url","").startswith("https://www.flytech.com.tw/data/investor_law/attached/"),
            "NOT_OFFICIAL_FLYTECH_IR_URL")
    require(x.get("gate_pass") is False and x.get("formal_Aplus_unchanged") is True,
            "RECEIPT_CERTIFICATION_SAFETY_FLAGS_MISSING")
    p=ROOT/x["text_path"]
    raw=p.read_bytes()
    require(sha(raw)==x.get("extracted_text_sha256"),"EXTRACTED_IR_TEXT_HASH_MISMATCH")
    require(x.get("pdf_sha256") and len(x["pdf_sha256"])==64,"IR_ORIGINAL_PDF_SHA_MISSING")
    return raw.decode("utf-8"),x

def source_snapshot():
    manifest=read(DATA/"ir/6206/manifest.json")
    h1,h1doc=observe(manifest,"2026-08-12")
    annual,annualdoc=observe(manifest,"2026-03-20")
    p7=h1.split("=== Page 7 ===")[1].split("=== Page 8 ===")[0]
    p8=h1.split("=== Page 8 ===")[1].split("=== Page 9 ===")[0]
    p6=h1.split("=== Page 6 ===")[1].split("=== Page 7 ===")[0]
    p9=annual.split("=== Page 9 ===")[1].split("=== Page 10 ===")[0]
    p7fy=annual.split("=== Page 7 ===")[1].split("=== Page 8 ===")[0]
    # Anchored to company-presented label/value pairs, not NLP inference.
    expectations={
      "H1_2026_REVENUE_NTD_M":"營業收入\\s+3,392",
      "H1_2026_GP_NTD_M":"營業毛利\\s+1,543",
      "H1_2026_OP_NTD_M":"營業利益\\s+1,006",
      "H1_2026_PARENT_NTD_M":"淨利歸屬母公司\\s+848",
      "H1_2026_EPS":"EPS\\s+5\\.93"}
    for key,pattern in expectations.items():
        require(re.search(pattern,p7),key+"_OFFICIAL_IR_MISMATCH")
    for key,pat,txt in [
      ("H1_2026_INVENTORY_NTD_M",r"存貨\s+1,510",p8),
      ("H1_2026_AR_NTD_M",r"應收帳款\s+1,617",p8),
      ("H1_2026_CASH_NTD_M",r"現金及約當現金\s+2,428",p8),
      ("Q2_2026_EPS",r"EPS\s+3\.42",p6),
      ("2025_FY_REVENUE_NTD_M",r"Revenue\s+5,033",p7fy),
      ("2025_FY_EPS",r"EPS\s+6\.90",p7fy),
      ("COMMON_SHARE_PROXY",r"Shares outstanding approx\.\s*143\.1mn",p9)]:
        require(re.search(pat,txt,re.I),key+"_OFFICIAL_IR_MISMATCH")
    return dict(IR_h1=h1doc,IR_fy=annualdoc,observations=dict(
      H1_2026_revenue_m=3392,H1_2026_gross_profit_m=1543,
      H1_2026_operating_profit_m=1006,H1_2026_parent_profit_m=848,
      H1_2026_eps=5.93,H1_2026_gm_pct=45.5,H1_2026_op_margin_pct=29.6,
      H1_2026_inventory_m=1510,H1_2026_receivables_m=1617,
      H1_2026_cash_m=2428,FY_2025_revenue_m=5033,FY_2025_eps=6.90))

def official_revenue():
    manifest=read(DATA/"latest_manifest.json")
    require(manifest.get("period")=="2026-09","REVENUE_MONTH_NOT_2026_09")
    require(manifest.get("capture_utc"),"REVENUE_SNAPSHOT_TIMESTAMP_MISSING")
    found=[]
    for x in manifest.get("shards",[]):
        path=ROOT/x["path"]
        raw=path.read_bytes()
        require(sha(raw)==x.get("sha256"),"OFFICIAL_REVENUE_SHARD_SHA_MISMATCH")
        for r in json.loads(raw):
            if r.get("code")==CODE and r.get("market")=="TWSE":
                found.append(r)
    require(len(found)==1,"REVENUE_6206_MISSING_OR_DUPLICATE")
    row=found[0]
    require(row.get("report_month")=="11509","WRONG_MOPS_REPORT_MONTH")
    ytd=positive(row.get("ytd_revenue_k"))
    require(ytd and ytd>3392000,"INVALID_9M_REVENUE_OR_UNIT")
    return dict(revenue_9m_ntd_m=ytd/1000,
                september_2026_ntd_m=positive(row["monthly_revenue_k"])/1000,
                ytd_yoy_pct=float(row["ytd_yoy_pct"]),
                provenance=dict(report_month="2026-09",capture_utc=manifest["capture_utc"],
                    official_sources=manifest.get("original_receipts",[])))

def official_price():
    manifest=read(DATA/"prices/latest_manifest.json")
    path=ROOT/manifest["path"]
    raw=path.read_bytes()
    require(sha(raw)==manifest.get("normalized_sha256"),
            "OFFICIAL_PRICE_SNAPSHOT_SHA_MISMATCH")
    rows=[x for x in json.loads(raw) if x.get("code")==CODE and x.get("market")=="TWSE"]
    require(len(rows)==1,"REFERENCE_CLOSE_IDENTITY_AMBIGUOUS")
    row=rows[0]
    require(row.get("date")==manifest.get("date"),"PRICE_MANIFEST_VINTAGE_MISMATCH")
    close=positive(row.get("close"))
    require(close is not None,"REFERENCE_PRICE_INVALID")
    return dict(close=close,date=row["date"],source=manifest.get("sources",{}).get("TWSE"))

def main_model_baseline():
    meta=read(DATA/"rankings/latest_research.json")
    loc=DATA/"rankings/v880_full_results.json.gz"
    raw=loc.read_bytes()
    require(sha(raw)==meta.get("full_results",{}).get("sha256"),
           "MAIN_MODEL_BASELINE_FULL_SHA_MISMATCH")
    full=json.loads(gzip.decompress(raw))
    require(meta.get("estimate_vintage")==full.get("estimate_vintage"),
           "MAIN_MODEL_BASELINE_VINTAGE_MISMATCH")
    rows=[x for x in full["all_model_rows"] if x.get("market")=="TWSE" and x.get("code")==CODE]
    require(len(rows)==1,"MAIN_MODEL_6206_MISSING_OR_DUPLICATE")
    row=rows[0]
    return dict(model_version=meta.get("model"),
       model_vintage=meta["estimate_vintage"],price_date=meta["asof_price_date"],
       current_financial_period=full["financial_last_quarter"],
       rankable=row.get("rankable"),
       existing_base_2027=row.get("base",{}) if row.get("rankable") else None,
       Aplus=row.get("formal_Aplus",False),gates_pending=row.get("certification",{}).get("gates_pending",[]))

def calculate(base,src,revenue,price):
    require(base["price_date"]==price["date"],"MAIN_MODEL_PRICE_DATE_NOT_MATCHED")
    require(base["current_financial_period"]=="2026-Q2",
            "Q3_FINANCIAL_MODEL_ROLLOVER_REQUIRES_NEW_ASSUMPTIONS")
    cap=src["IR_h1"]["first_captured_utc"]
    model_date=dt.datetime.fromisoformat(base["model_vintage"])
    capture=dt.datetime.fromisoformat(cap.replace("Z","+00:00"))
    revenue_capture=dt.datetime.fromisoformat(revenue["provenance"]["capture_utc"].replace("Z","+00:00"))
    require(model_date.tzinfo is not None and capture<=model_date and revenue_capture<=model_date,
            "FORWARD_VINTAGE_IR_OR_REVENUE_AFTER_MODEL")
    year_end=dt.date.fromisoformat(price["date"])
    require(year_end.year==2026 and year_end.month>=9,"QUOTE_TOO_OLD_FOR_Q3_RESEARCH")
    # Forecast 2026 Q4 revenue is hypothetical, based on 9M actual plus target 2026FY.
    revenue_q4_est_m=FORECAST_2026_FULL_YEAR_M-revenue["revenue_9m_ntd_m"]
    require(0<revenue_q4_est_m<2500,"IMPLAUSIBLE_Q4_REVENUE_ASSUMPTION")
    estimates={}
    for name,sc in SCENARIOS.items():
        result=operating_scenario(sc["revenue_m"]*1000,sc["gross_margin"],sc["opex_ratio"],
           sc["nonop_m"]*1000,sc["tax"],1.0,COMMON_SHARE_PROXY_M*1e6,sc["pe"])
        result.update(returns(result["target_price"],price["close"],None,
                      price["date"],"2027-12-31"))
        estimates[name]=dict(revenue_m=sc["revenue_m"],
            yoy_vs_2026_fy_pct=(sc["revenue_m"]/FORECAST_2026_FULL_YEAR_M-1)*100,
            gross_margin_pct=sc["gross_margin"]*100,
            opex_ratio_pct=sc["opex_ratio"]*100,
            operating_margin_pct=(sc["gross_margin"]-sc["opex_ratio"])*100,
            nonop_m=sc["nonop_m"],tax_pct=sc["tax"]*100,
            parent_earnings_m=result["parent_profit_k"]/1000,
            diluted_share_proxy_m=COMMON_SHARE_PROXY_M,
            eps=result["eps"],pe=sc["pe"],target_price=result["target_price"],
            price_upside_pct=result["price_upside_pct"])
    return dict(status="SOURCE_RECONCILED_RESEARCH_ONLY_UNCERTIFIED",
          model="V8.8.8 6206 independent source-linked operating bridge",
          evaluated_for="2027-12-31",issuer=CODE,
          actual_ir=src["observations"],
          official_revenue=revenue,official_reference_price=price,
          source_receipts=[{k:e[k] for k in ("event_date","source_url","pdf_sha256","extracted_text_sha256",
                     "first_captured_utc")} for e in (src["IR_h1"],src["IR_fy"])],
          estimated_2026_revenue_m=FORECAST_2026_FULL_YEAR_M,
          estimated_2026_Q4_revenue_m=revenue_q4_est_m,
          scenarios=estimates,
          original_common_model=base,
          assumptions_status=dict(tax_rate_uncertified=True,
                forward_revenue_not_guidance=True,margin_and_pe_not_company_forecast=True,
                AI_premium_not_auto_added=True,
                common_shares_are_proxy_not_diluted_certified=True,
                q3_2026_eps_still_unknown=True,free_cash_flow_untested=True,
                IR_original_PIT_not_independently_verified=True),
          risk=dict(H1_2026_inventory_m=src["observations"]["H1_2026_inventory_m"],
             H1_2026_accounts_receivable_m=src["observations"]["H1_2026_receivables_m"],
             inventory_days_H1_2026=114,inventory_days_Q2_2025=80,
             inventory_up_yoy_pct=(1510/767-1)*100,
             receivables_up_yoy_pct=(1617/1206-1)*100),
          formal_Aplus=False,formal_Aplusplus=False,formal_quality_gates_passed_by_this_report=0,
          common_market_rank_unchanged=True,no_automatic_orders=True)

def markdown(result):
    if result.get("status")!="SOURCE_RECONCILED_RESEARCH_ONLY_UNCERTIFIED":
        return ("# 6206 飛捷：獨立合理價研究\n\n目前證據待補："+result.get("error","")+
                "\n正式A+不變；原研究榜不變。\n")
    p=result["official_reference_price"]; rev=result["official_revenue"]
    lines=["# 6206 飛捷｜2027年合理價：官方法說與營收證據橋接","",
           f"研究狀態：{result['status']}，**尚非正式A+**。",
           f"官方收盤參考價：{p['date']}，{p['close']:.2f}元。",
           f"官方2026年1–9月營收：{rev['revenue_9m_ntd_m']/100:.2f}億元（年增{rev['ytd_yoy_pct']:.2f}%）。",
           f"假設2026全年營收66億元，意味Q4須達{result['estimated_2026_Q4_revenue_m']/100:.2f}億元。","",
           "|2027情境|營收(億元)|毛利率|費用率|EPS|PE|合理價|相對官方收盤漲幅|",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for lane in ("bear","base","bull"):
        a=result["scenarios"][lane]
        lines.append(f"|{lane}|{a['revenue_m']/100:.1f}|{a['gross_margin_pct']:.1f}%|"
                     f"{a['opex_ratio_pct']:.1f}%|{a['eps']:.2f}|{a['pe']:.1f}|"
                     f"{a['target_price']:.1f}|{a['price_upside_pct']:+.1f}%|")
    main=result["original_common_model"]
    old=main.get("existing_base_2027") or {}
    lines+=["",f"**模型本體比較**：{main['model_version']} 的2027 Base EPS "+
             (f"{old.get('eps',0):.2f}、價{old.get('target_price',0):.1f}元" if old else "待補")+
             "；目前這份獨立情境不取代全市場共同排名。",
            "",
            "## 估值前提與需查核風險",
            "- 2026H1官方法說EPS 5.93、毛利率45.5%、營益率29.6%。",
            "- 2027 Base營收76億元、毛利45%、營業費用17%，扣業外5000萬元與20%估計稅率。",
            "- 約1.431億股是2026年3月法說揭露近似普通股數，尚未確認完整稀釋股數與CB條款。",
            "- 存貨15.10億元，去年同期7.67億元；銷貨日數由80升至114天；應收帳款16.17億元。",
            "- 新法說PDF只證明截至該簡報的觀察；不代表Q3 EPS已公告、也不保證AI新案轉化現金流。",
            "- 正式13項認證仍須個別來源與營運橋接、現金流、稀釋、公告PIT與樣本外驗證。",
            "","## 已核驗官方原件"]
    for x in result["source_receipts"]:
        lines.append(f"- {x['event_date']}：{x['source_url']}；PDF SHA256 `{x['pdf_sha256']}`")
    return "\n".join(lines)+"\n"

def main():
    output=DATA/"rankings";output.mkdir(parents=True,exist_ok=True)
    try:
        src=source_snapshot()
        revenue=official_revenue()
        price=official_price()
        baseline=main_model_baseline()
        res=calculate(baseline,src,revenue,price)
    except (ValueError,KeyError,TypeError,FileNotFoundError,OverflowError) as e:
        res=dict(status="6206_EVIDENCE_OR_VINTAGE_PENDING",
                 error=type(e).__name__+":"+str(e)[:200],
                 issuer=CODE,formal_Aplus=False,common_market_rank_unchanged=True)
    (output/"v888_6206_independent_valuation.json").write_text(
        json.dumps(res,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (output/"v888_6206_independent_valuation.md").write_text(markdown(res),encoding="utf-8")
    print(json.dumps(dict(status=res["status"],
             base_price=res.get("scenarios",{}).get("base",{}).get("target_price"),
             error=res.get("error")),ensure_ascii=False))

if __name__=="__main__":
    main()
