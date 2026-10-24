#!/usr/bin/env python3
"""9 0056 financial constituents: dated, secondary BVPS plus *reverse* ROE hurdle.

No fair-price, return target, actual clean-surplus ROE, A+ upgrade or bank PB
certification is produced. Financial sector remains outside the 34-stock Base
ranking until original common-equity and sustainable 2027 ROE are certified.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

from scripts.v8b4_0056_forward_top10 import filter_top10,load_inputs

SOURCE="config/0056_financial_bvps_2026-Q2_watch.json"
PRICE_MANIFEST="prices/latest_manifest.json"
FINANCIAL_STATEMENT="fundamentals/2026-Q2/TWSE_income.json"
SCHEMA="V8B6_SECONDARY_Q2_2026_FINANCIAL_BVPS_WATCH_V1"
KE=0.10  # illustration, not empirical cost of capital
G=0.03   # illustration, not forecasted book growth


def numeric(x):
    return type(x) in (int,float) and math.isfinite(x)


def validate_bvps(source,holdings,read_at):
    if (source.get("schema")!=SCHEMA or source.get("etf")!="0056" or
        source.get("period")!="2026-Q2" or source.get("asof_holdings_date")!=holdings["asof_date"] or
        source.get("source_is_third_party_aggregated_not_an_issuer_report") is not True or
        source.get("issuer_original_financial_statements_PIT_verified") is not False or
        source.get("formal_financial_PE_ROE_PB_valuation_certified") is not False or
        source.get("observed_time_conservative_not_issuer_release_time") is not True or
        source.get("corporate_actions_adjusted_since_quarter_end") is not False or
        source.get("preferred_common_equity_and_noncontrolling_reconciled") is not False):
        raise ValueError("0056_FINANCIAL_SECONDARY_PROVENANCE_OR_SCOPE_INVALID")
    observed=dt.datetime.fromisoformat(source["observed_first_at"])
    checked=dt.datetime.fromisoformat(read_at.replace("Z","+00:00"))
    if observed.tzinfo is None or checked.tzinfo is None or checked<observed:
        raise ValueError("0056_FINANCIAL_BVPS_NOT_OBSERVED_AS_OF_TIME")
    etf_codes={p["code"] for p in holdings["positions"]}
    positions=source.get("positions")
    if not isinstance(positions,list) or len(positions)!=9:
        raise ValueError("0056_FINANCIAL_BVPS_NINE_CONSTITUENTS_REQUIRED")
    found=set()
    for r in positions:
        code=r.get("code")
        if (code in found or code not in etf_codes or
            code not in {"2880","2883","2884","2885","2886","2887","2890","2891","5876"}
            or r.get("source_quarter")!="2026-Q2" or
            r.get("source_url")!=f"https://statementdog.com/analysis/{code}/nav" or
            r.get("original_issuer_BVPS_fully_reconciled") is not False or
            not numeric(r.get("bvps_ntd")) or not 0<r["bvps_ntd"]<500):
            raise ValueError("0056_FINANCIAL_BVPS_ISSUER_QUARTER_OR_SOURCE_INVALID")
        found.add(code)
    return positions


def screen(root,read_at):
    root=Path(root)
    holdings,compact,full=load_inputs(root)
    previously=filter_top10(holdings,full)
    source=json.loads((root/SOURCE).read_text(encoding="utf-8"))
    positions=validate_bvps(source,holdings,read_at)
    manifest=json.loads((root/PRICE_MANIFEST).read_text(encoding="utf-8"))
    close_path=root/manifest["path"]
    price_bytes=close_path.read_bytes()
    if (hashlib.sha256(price_bytes).hexdigest()!=manifest["normalized_sha256"] or
        manifest["date"]!=full["asof_price_date"]):
        raise ValueError("0056_FINANCIAL_PRICE_SOURCE_DATE_OR_SHA_MISMATCH")
    quoted=json.loads(price_bytes)
    matched_price={}
    for row in quoted:
        code=row.get("code")
        if code in {p["code"] for p in positions}:
            if code in matched_price:
                raise ValueError("0056_FINANCIAL_DUPLICATE_OFFICIAL_PRICE")
            if row.get("market")!="TWSE" or row.get("date")!=manifest["date"] or not numeric(row.get("close")) or row["close"]<=0:
                raise ValueError("0056_FINANCIAL_OFFICIAL_CLOSE_IDENTITY_INVALID")
            matched_price[code]=row
    official_bytes=(root/FINANCIAL_STATEMENT).read_bytes()
    financials=json.loads(official_bytes)["rows"]
    eps_mirror={r["code"]:r for r in financials if r["code"] in matched_price}
    if len(eps_mirror)!=len(positions) or len(matched_price)!=len(positions):
        raise ValueError("0056_FINANCIAL_PRICE_OR_EPS_MIRROR_MISSING")
    result=[]
    for item in positions:
        code=item["code"];quote=matched_price[code];fin=eps_mirror[code]
        if (fin.get("market")!="TWSE" or fin.get("period")!="2026-Q2" or
            fin.get("year_to_date_values") is not True or
            fin.get("company_PIT_verified") is not False or
            not numeric(fin.get("basic_eps_ytd")) or fin["basic_eps_ytd"]<=0):
            raise ValueError("0056_FINANCIAL_2026_H1_EPS_INVALID_"+code)
        book=item["bvps_ntd"];p=quote["close"];eps=fin["basic_eps_ytd"]
        pb=p/book
        annualized_eps=eps*2
        h1_roe_proxy=annualized_eps/book
        # Inverting steady-state justified PB = (ROE - g)/(Ke - g).
        # This requires constant equity base, book-growth and dividend payout;
        # not a bank-specific forecast or validated cost of equity.
        implied_roe=G+(KE-G)*pb
        result.append(dict(code=code,name=item["name"],
            official_reference_close_ntd=p,book_per_share_2026q2_ntd=book,
            current_pb_multiple=pb,
            eps_2026_h1_official_ytd=eps,
            eps_2026_h1_twice_reference=annualized_eps,
            h1_annualized_eps_divided_by_end_book_proxy_pct=h1_roe_proxy*100,
            illustrative_required_sustainable_roe_pct=implied_roe*100,
            illustrative_required_roe_minus_h1_proxy_pp=(implied_roe-h1_roe_proxy)*100,
            model_ke_assumption_pct=KE*100,model_g_assumption_pct=G*100,
            bvps_url=item["source_url"],
            bvps_secondary_not_primary_verified=True,
            quarterly_end_roe_proxy_not_true_annual_roe=True,
            financial_original_ROE_and_capital_quality_not_reviewed=True,
            financial_base_2027_eps_ntd=None,
            financial_base_2027_PB=None,
            financial_2027_price_upside_pct=None,
            formal_Aplus=False))
    result.sort(key=lambda r:(r["illustrative_required_roe_minus_h1_proxy_pp"],r["code"]))
    return dict(schema="V8B6_0056_FINANCIAL_REVERSE_ROE_HURDLE_RESEARCH_ONLY",
        membership_date=holdings["asof_date"],
        official_close_date=full["asof_price_date"],
        model_estimate_vintage=full["estimate_vintage"],
        secondary_financial_BVPS_observed_first_at=source["observed_first_at"],
        assessment_not_an_original_market_PIT_vintage=True,
        cost_of_equity_assumption_pct=KE*100,long_term_growth_assumption_pct=G*100,
        total_constituents=50,other_sector_base_price_comparable_count=previous["rankable_count"],
        nine_financial_ROE_PB_hurdle_only_count=len(result),
        remaining_missing_comparable_count=previous["unrankable_count"]-len(result),
        finance_ranking_is_not_a_2027_return_ranking=True,
        exact_historical_original_BVPS_unverified=True,
        H1_eps_source_sha256=hashlib.sha256(official_bytes).hexdigest(),
        official_price_sha256=hashlib.sha256(price_bytes).hexdigest(),
        original_0056_top10_unchanged=True,
        all_13_formal_gates_preserved=True,
        required_next_evidence=["issuer-signed 2026Q2 common BVPS/reconciliation","3y normalized ROE/OCI",
          "insurance subsidiaries capital ratio and investment income","preferred/common/dilution",
          "company-specific risk-adjusted Ke,g and 2027 parent profit/BVPS bridge",
          "corporate-action-adjusted price and dividend comparability"],
        financials_sorted_by_conditional_hurdle_gap=result)


def write_report(data,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix==".json":
        text=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    else:
        x=data
        lines=["# 0056 金融股：每股淨值與市場隱含ROE門檻（不屬2027合理價）","",
            f"0056成分股基準 {x['membership_date']}；官方收盤 {x['official_close_date']}；"
            f"本次第三方財報BVPS第一次查閱 {x['secondary_financial_BVPS_observed_first_at']}。","",
            f"可比2027 EPS×PE情境 {x['other_sector_base_price_comparable_count']}檔；"
            f"金融ROE/PB**研究門檻** {x['nine_financial_ROE_PB_hurdle_only_count']}檔；"
            f"尚不可比 {x['remaining_missing_comparable_count']}檔。"
            "無法據此重新正式排序50檔。","",
            "模型設定Ke=10%、g=3%，僅作公開假設下的**反向估值門檻**，不是估出的金融股合理Ke/g或2027 ROE。",
            "條件公式：P/B=(ROE-g)/(Ke-g)，所以持有現價所隱含的長期ROE"
            "=g+(Ke-g)×現有P/B；2026上半年EPS×2÷2026Q2末每股淨值只是一個"
            "未校正季節性與期初平均股東權益的**替代指標**，不能視為真實ROE或2027 ROE。","",
            "|公司|BVPS Q2|10/22收盤|目前P/B|H1 EPS|簡化獲利/期末淨值|條件ROE門檻|門檻差|",
            "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for r in x["financials_sorted_by_conditional_hurdle_gap"]:
            lines.append(
                f"|{r['code']} {r['name']}|{r['book_per_share_2026q2_ntd']:.2f}|"
                f"{r['official_reference_close_ntd']:.2f}|{r['current_pb_multiple']:.2f}|"
                f"{r['eps_2026_h1_official_ytd']:.2f}|"
                f"{r['h1_annualized_eps_divided_by_end_book_proxy_pct']:.1f}%|"
                f"{r['illustrative_required_sustainable_roe_pct']:.1f}%|"
                f"{r['illustrative_required_roe_minus_h1_proxy_pp']:+.1f}pp|")
        lines+=["","BVPS為第三方StatementDog對2026Q2財報的整理（非原始MOPS稽核簽章），"
            "各來源由紀錄中的發行人網址核對；H1 EPS及10/22收盤價係本模型具SHA的官方標準化資料。",
            "保險業OCI、持股淨值、資本適足率、稀釋及除權息使跨產業P/B不可直接排名。",
            "正式2027 EPS、BVPS、合理P/B、合理價與漲幅**全部維持空值**；不變更原34檔排名、A+或宣稱勝過0056。",""]
        text="\n".join(lines)
    path.write_text(text,encoding="utf-8")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=Path("tw-market-data"))
    parser.add_argument("--out",type=Path)
    parser.add_argument("--observed-at",default="2026-10-24T19:00:00+08:00")
    args=parser.parse_args()
    result=screen(args.root,args.observed_at)
    if args.out:
        write_report(result,args.out)
        write_report(result,args.out.with_suffix(".md"))
    print("BEGIN_0056_FINANCE_HURDLE="+json.dumps(
        {"finance_count":len(result["financials_sorted_by_conditional_hurdle_gap"]),
         "other_comparable":result["other_sector_base_price_comparable_count"],
         "remaining_unrankable":result["remaining_missing_comparable_count"],
         "rows":[{"code":r["code"],"pb":round(r["current_pb_multiple"],3),
                  "h1_proxy":round(r["h1_annualized_eps_divided_by_end_book_proxy_pct"],1),
                  "required_roe":round(r["illustrative_required_sustainable_roe_pct"],1),
                  "gap_pp":round(r["illustrative_required_roe_minus_h1_proxy_pp"],1)}
                 for r in result["financials_sorted_by_conditional_hurdle_gap"]]},
        ensure_ascii=False,separators=(",",":")))


if __name__=="__main__":
    main()
