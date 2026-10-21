#!/usr/bin/env python3
"""2069 independent 2027 cyclical operating-profit bridge (research shadow).

Never silently promote a company to formal A+, replace original financial
filing certification, use unverified brokerage fills or rewrite model Base.
The prior 33 NTD sketch used 6% operating expenses and 0.15 億 nonop drag,
both requiring explicit company-specific evidence before accepting.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

CODE="2069"
SHARES=166_386_836
STOCK_SHARES_SUPPORT_SOURCE=("https://stockgo.tw/stock/2069/")  # 2026-06-01 dividend declaration
SHARE_NUMBER_ORIGINAL_SIGNOFF=False
SUPPLEMENTAL_NONOP_H1_NTD_THOUSANDS=-39657
SUPPLEMENTAL_REPUBLICATION_SOURCE=(
    "https://m.esunsec.com.tw/news/instant-detail.aspx?id=%7BB1C04183-0628-46B6-8299-4ECF75F96661%7D"
)
# Conservative, transparent assumptions, NOT an estimate from analyst targets.
ASSUMPTIONS={
    "Bear":dict(revenue_2027_yi=95.0,gross_margin_pct=11.0,
                operating_expense_pct=7.25,nonop_2027_yi=-0.8,
                cash_tax_rate_pct=20.0,reasonable_pe=9.0),
    "Base":dict(revenue_2027_yi=105.0,gross_margin_pct=12.5,
                operating_expense_pct=7.0,nonop_2027_yi=-0.6,
                cash_tax_rate_pct=20.0,reasonable_pe=11.0),
    "Bull":dict(revenue_2027_yi=110.0,gross_margin_pct=15.0,
                operating_expense_pct=7.0,nonop_2027_yi=-0.4,
                cash_tax_rate_pct=20.0,reasonable_pe=12.5),
}

def require(condition,message):
    if not condition:raise ValueError(message)

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def official_integral_thousands(v):
    """MOPS normalization may serialize exact integer NTD-thousands as 1.0.

    Accept only genuinely integral, finite values; never truncate an amount,
    accept bools, or round away a sub-thousand accounting discrepancy.
    """
    return (type(v) in (int,float) and math.isfinite(v)
            and v>=0 and int(v)==v)

def result_row(root,quarter,kind):
    path=Path(root)/f"fundamentals/{quarter}/TWSE_{kind}.json"
    data=read(path)
    require(data.get("period")==quarter and data.get("market")=="TWSE"
            and data.get("kind")==kind
            and data.get("company_PIT_verified") is False
            and data.get("raw_sha256"),"INVALID_OFFICIAL_BATCH_SOURCE_RECEIPT")
    matches=[r for r in data.get("rows",[]) if r.get("code")==CODE]
    require(len(matches)==1 and matches[0].get("period")==quarter
            and matches[0].get("year_to_date_values") is True,
            "MISSING_OR_DUPLICATE_2069_QUARTERLY_ROW")
    return matches[0]

def scenario(name, args, reference_close, issued=SHARES):
    rev=float(args["revenue_2027_yi"])
    gm=float(args["gross_margin_pct"])/100
    opex=float(args["operating_expense_pct"])/100
    nonop=float(args["nonop_2027_yi"])
    tax=float(args["cash_tax_rate_pct"])/100
    pe=float(args["reasonable_pe"])
    require(all(math.isfinite(x) for x in (rev,gm,opex,nonop,tax,pe,reference_close))
            and 0<rev<10000 and 0<=gm<1 and 0<=opex<1
            and -100<nonop<100 and 0<=tax<1 and 0<pe<=40
            and reference_close>0
            and isinstance(issued,int) and not isinstance(issued,bool) and issued>0,
            "INVALID_2069_VALUATION_INPUT")
    operating_profit=rev*(gm-opex)
    pretax=operating_profit+nonop
    profit=pretax*(1-tax)
    eps=profit*100_000_000/issued
    target=eps*pe
    return dict(name=name, assumptions=args,
                operating_profit_2027_yi=round(operating_profit,4),
                pre_tax_income_2027_yi=round(pretax,4),
                net_income_2027_yi=round(profit,4),
                issued_shares_denominator=issued,
                eps_2027_scenario=round(eps,4),
                fair_price_scenario=round(target,2),
                reference_price_upside_pct=round(100*(target/reference_close-1),2),
                earnings_forecast_is_verified=False,
                peer_pe_original_audit_complete=False,
                share_dilution_fully_certified=False)

def margin_needed_for_return(price,return_pct,params,issued=SHARES):
    rev=params["revenue_2027_yi"]
    pe=params["reasonable_pe"]
    opex=params["operating_expense_pct"]/100
    nonop=params["nonop_2027_yi"]
    net_income=(price*(1+return_pct/100)/pe)*issued/100_000_000
    pretax=net_income/(1-params["cash_tax_rate_pct"]/100)
    return round(100*(opex+(pretax-nonop)/rev),2)

def analyze(root, comparison_price=None):
    root=Path(root)
    scan=read(root/"fundamentals/latest_scan.json")
    manifest=read(root/"prices/latest_manifest.json")
    reference_date=manifest["date"]
    path=(root.parent/manifest["path"]) if str(root)=="tw-market-data" else (
        root.parent/manifest["path"] if Path(manifest["path"]).parts[0]==root.name
        else root/manifest["path"])
    # Path check is independent from fund manifest's source assertions.
    root_abs=root.resolve()
    path=path.resolve()
    require(path.is_relative_to(root_abs/"prices")
            and path.name==reference_date+".json", "INVALID_OFFICIAL_PRICE_PATH")
    raw=path.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==manifest["normalized_sha256"],
            "LATEST_OFFICIAL_PRICE_ARCHIVE_HASH_MISMATCH")
    rows=json.loads(raw)
    matches=[v for v in rows if v.get("code")==CODE and v.get("market")=="TWSE"]
    require(len(matches)==1 and matches[0].get("date")==reference_date,
            "MISSING_OR_MISDATED_2069_OFFICIAL_PRICE")
    quote=matches[0]["close"]
    require(type(quote) in (float,int) and math.isfinite(quote) and quote>0,
            "INVALID_2069_EXCHANGE_PRICE")
    if comparison_price is not None:
        require(isinstance(comparison_price,(float,int)) and not isinstance(comparison_price,bool)
                and math.isfinite(comparison_price) and comparison_price>0,
                "INVALID_USER_QUOTED_REFERENCE")
    price=quote if comparison_price is None else float(comparison_price)
    p25=result_row(root,"2025-Q4","income")
    q1=result_row(root,"2026-Q1","income")
    q2=result_row(root,"2026-Q2","income")
    flow=result_row(root,"2026-Q2","cashflow")
    sales=q2["revenue_ytd_k"]
    gross=q2["gross_profit_ytd_k"]
    operating=q2["operating_profit_ytd_k"]
    cost=gross-operating
    quarter_sales=sales-q1["revenue_ytd_k"]
    quarter_cost=cost-(q1["gross_profit_ytd_k"]-q1["operating_profit_ytd_k"])
    require(all(official_integral_thousands(v) for v in
                (sales,gross,operating,cost,quarter_sales,quarter_cost))
            and sales>0 and quarter_sales>0
            and q2["basic_eps_ytd"]==1.66 and
            p25["basic_eps_ytd"]==1.62 and
            flow["operating_cashflow_ytd_k"]==-114454,
            "2069_FINANCIAL_BASIS_CHANGED_REVIEW_ASSUMPTIONS:"+
            json.dumps(dict(sales=sales,gross=gross,operating=operating,cost=cost,
                q2_sales=quarter_sales,q2_cost=quarter_cost,
                q2_eps=q2["basic_eps_ytd"],prior_eps=p25["basic_eps_ytd"],
                h1_cfo=flow["operating_cashflow_ytd_k"],
                data_sources=[q2.get("source"),flow.get("source")]),sort_keys=True))
    # Captured source data is company_PIT_verified=False; don't relabel.
    income_revenue_2025_yi=round(p25["revenue_ytd_k"]/100000,4)
    scenarios={k:scenario(k,v,price) for k,v in ASSUMPTIONS.items()}
    base=scenarios["Base"]
    # Explicitly reconcile original 33 NTD sketch: its 6% expense and
    # -0.15 億 nonop each require proof and are not adopted.
    prior_sketch=scenario("REJECTED_OLD_33NTD_COST_ASSUMPTION",
        dict(revenue_2027_yi=105.0,gross_margin_pct=12.0,
             operating_expense_pct=6.0,nonop_2027_yi=-0.15,
             cash_tax_rate_pct=20.0,reasonable_pe=11.0),price)
    status=("HISTORICAL_2026_H1_BASIS_REQUIRES_NEW_QUARTER_REVIEW"
            if scan.get("last_eligible_quarter")!="2026-Q2"
            else "INDEPENDENT_2027_CYCLICAL_SCENARIO_RESEARCH_ONLY")
    return dict(schema="V8A7_2069_INDEPENDENT_OPERATING_BRIDGE",
        issuer="2069",name="運錩",financial_last_used="2026-Q2",
        upstream_financial_last_eligible=scan.get("last_eligible_quarter"),
        status=status,official_reference_price_date=reference_date,
        official_reference_close=quote,
        comparison_reference_close=price,
        comparison_source=("USER_STATED_UNVERIFIED_INTRADAY_PRICE_NOT_A_BROKER_FILL"
                           if comparison_price is not None
                           else "SHA_CHECKED_DAILY_ARCHIVE_NOT_A_BROKER_FILL"),
        official_current_financials_are_batch_not_issuer_PIT_certified=True,
        source_receipts=dict(
            official_price_sha256=manifest["normalized_sha256"],
            official_price_archive=manifest["path"],
            first_half_2026_operating_cashflow_is_ytd=True),
        historical=dict(
            reported_2025_fy_revenue_yi=income_revenue_2025_yi,
            reported_2025_fy_eps=p25["basic_eps_ytd"],
            reported_2026_h1_revenue_yi=round(sales/100000,4),
            reported_2026_h1_gross_margin_pct=round(100*gross/sales,2),
            reported_2026_h1_operating_expense_pct=round(100*cost/sales,2),
            reported_2026_q2_operating_expense_pct=round(100*quarter_cost/quarter_sales,2),
            reported_2026_h1_operating_profit_yi=round(operating/100000,4),
            reported_2026_h1_eps=q2["basic_eps_ytd"],
            reported_2026_h1_operating_cashflow_yi=round(
                flow["operating_cashflow_ytd_k"]/100000,5),
            h1_nonop_net_yi_republished_not_sha_certified=round(
                SUPPLEMENTAL_NONOP_H1_NTD_THOUSANDS/100000,5),
            research_dividend_issued_share_count=SHARES,
            original_diluted_share_reconciliation_complete=False),
        original_shares_source=STOCK_SHARES_SUPPORT_SOURCE,
        nonop_source=SUPPLEMENTAL_REPUBLICATION_SOURCE,
        scenarios=scenarios,
        old_33_valuation_assumptions_rejected=dict(
            operating_expense_pct=6.0,nonop_yi=-0.15,
            comparable_price=prior_sketch["fair_price_scenario"],
            previous_33_is_validated=False),
        at_27_35_only_if_user_provided=True,
        margin_needed_to_break_even_at_reference_pct=margin_needed_for_return(
            price,0,ASSUMPTIONS["Base"]),
        margin_needed_for_30pct_upside_at_reference_pct=margin_needed_for_return(
            price,30,ASSUMPTIONS["Base"]),
        gross_margin_reversion_will_change_eps_materially=True,
        q3_2026_earnings_not_yet_verified=True,
        RnD_2026Q2_67_55m_secondary_source_not_normalized_and_nonrecurring_not_proven=True,
        standard_fcf_after_only_ppe_purchase_not_derived_due_to_missing_capex=True,
        all_investing_cash_flow_not_identical_to_capex=True,
        original_financial_notes_and_dilution_pending=True,
        formal_gates_passed_by_this_work=0,formal_Aplus_added=0,
        base_2027_model_auto_modified=False,
        no_calibrated_scenario_probabilities=True,
        no_trade_or_automatic_exit=True)

def markdown(r):
    h=r["historical"]
    fmt=lambda x:f"{x:+.1f}%" if x>=0 else f"{x:.1f}%"
    lines=["# 運錩2069｜2027獨立合理價重新查核（V8.A7研究版）","",
        f"官方參考價：{r['official_reference_close']:.2f}元，交易日{r['official_reference_price_date']}；"
        f"估值比較價：{r['comparison_reference_close']:.2f}元（{r['comparison_source']}）。",
        f"2026上半年營收{h['reported_2026_h1_revenue_yi']}億元，毛利率{h['reported_2026_h1_gross_margin_pct']}%，"
        f"費用率{h['reported_2026_h1_operating_expense_pct']}%，第二季費用率"
        f"{h['reported_2026_q2_operating_expense_pct']}%；EPS{h['reported_2026_h1_eps']}元。",
        f"上半年營業現金流{h['reported_2026_h1_operating_cashflow_yi']}億元，"
        "只核對營業現金流；原始資本支出現金項目未對帳，不混稱標準自由現金流。",
        f"業外淨支出上半年約{-h['h1_nonop_net_yi_republished_not_sha_certified']:.3f}億元"
        "（交易所揭露數字之二手轉載，仍待原始季報對帳）。","",
        "|情境|2027收入(億)|毛利率|費用率|業外淨額(億)|EPS|PE|合理價|價差|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k,s in r["scenarios"].items():
        a=s["assumptions"]
        lines.append(f"|{k}|{a['revenue_2027_yi']:.0f}|{a['gross_margin_pct']:.2f}%|"
            f"{a['operating_expense_pct']:.2f}%|{a['nonop_2027_yi']:.2f}|"
            f"{s['eps_2027_scenario']:.2f}|{a['reasonable_pe']:g}|"
            f"{s['fair_price_scenario']:.2f}|{fmt(s['reference_price_upside_pct'])}|")
    lines.extend(["",
        f"同樣以11倍PE、7%營業費用率、業外-{abs(ASSUMPTIONS['Base']['nonop_2027_yi']):.1f}億推演："
        f"要達到30% Base潛在價差，2027全年毛利率需約"
        f"**{r['margin_needed_for_30pct_upside_at_reference_pct']:.2f}%**。"
        "這是條件式敏感度，不是財報預測或A+正式通過。","",
        "## 修正緣由","",
        "上版33元簡算採6%費用率、全年業外僅-0.15億元，"
        "相較實際H1約7.05%營業費用與已發生約-0.397億元業外支出，"
        "均過度樂觀；本版明確下修或留有緩衝。",
        "2026Q2研發費用顯著上升，是否屬單次性費用尚無原始證據，不得自行剔除。",
        "2026H1 OCF負數不能自動證明本業惡化；先核對應收、庫存、資本支出與全年回收。",
        "公司2027訂單、營業費用正常化、完整Q3季報、稀釋股數與同業PE尚未正式簽核。",
        "這是額外公司別研究影子，不變更全市場既有Base、正式13門檻與交易判斷；不提供無回測支持的勝率。",""])
    if r["status"]!="INDEPENDENT_2027_CYCLICAL_SCENARIO_RESEARCH_ONLY":
        lines.insert(2,"**警告：原始最新財報期間已超過2026-Q2，本估值因未接新季度須重新查核，不能當最新合理價。**")
    return "\n".join(lines)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-dir",default="tw-market-data")
    parser.add_argument("--out-dir")
    parser.add_argument("--comparison-price",type=float)
    args=parser.parse_args()
    root=Path(args.data_dir)
    report=analyze(root,args.comparison_price)
    out=Path(args.out_dir) if args.out_dir else root/"rankings"
    out.mkdir(parents=True,exist_ok=True)
    (out/"v8a7_2069_independent_valuation.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"v8a7_2069_independent_valuation.md").write_text(
        markdown(report)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in (
        "status","official_reference_price_date","official_reference_close",
        "comparison_reference_close","formal_Aplus_added")},ensure_ascii=False))

if __name__=="__main__":
    main()
