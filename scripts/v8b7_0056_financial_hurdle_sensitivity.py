#!/usr/bin/env python3
"""0056 nine financial issuers: explicit Ke/g sensitivity of a reverse ROE hurdle.

Neither market-implied ROE nor nine mechanical stress cells constitutes a
sustainable ROE forecast, a probability, an independent 2027 fair value, or
proof of overvaluation. 2026H1 EPS*2/Q2 ending BVPS is only a proxy.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

INPUT="rankings/0056_financial_pb_hurdle_latest.json"
H1_INPUT="fundamentals/2026-Q2/TWSE_income.json"
PRICE_DIR="prices"
K_E_PCTS=(8,10,12)
G_PCTS=(0,3,5)
CODES={"2880","2883","2884","2885","2886","2887","2890","2891","5876"}
BASE_KE=10
BASE_G=3
SCHEMA="V8B7_0056_FINANCIAL_ROE_PB_CONDITIONAL_HURDLE_SENSITIVITY_NOT_PRICE_VALUATION"


def finite_number(x):
    return type(x) in (int,float) and math.isfinite(x)


def sensitivity(data,root):
    root=Path(root)
    if (data.get("nine_financial_ROE_PB_hurdle_only_count")!=9 or
        data.get("remaining_missing_comparable_count")!=7 or
        data.get("total_constituents")!=50 or
        data.get("finance_ranking_is_not_a_2027_return_ranking") is not True or
        data.get("exact_historical_original_BVPS_unverified") is not True or
        data.get("all_13_formal_gates_preserved") is not True or
        data.get("original_0056_top10_unchanged") is not True or
        data.get("same_day_intraday_PIT_proven") is not False or
        data.get("official_close_date")!="2026-10-22" or
        data.get("cost_of_equity_assumption_pct")!=BASE_KE or
        data.get("long_term_growth_assumption_pct")!=BASE_G):
        raise ValueError("0056_FINANCIAL_HURDLE_SOURCE_NOT_ELIGIBLE")
    rows=data.get("financials_sorted_by_conditional_hurdle_gap")
    if not isinstance(rows,list) or len(rows)!=9 or {r.get("code") for r in rows}!=CODES:
        raise ValueError("0056_FINANCIAL_HURDLE_NINE_IDENTITIES_INVALID")
    vintage=dt.datetime.fromisoformat(data["model_estimate_vintage"])
    if vintage.tzinfo is None:
        raise ValueError("0056_FINANCIAL_HURDLE_VINTAGE_UNAWARE")
    first_observed=dt.date.fromisoformat(data["secondary_financial_BVPS_first_reviewed_on"])
    if vintage.date()<first_observed:
        raise ValueError("0056_FINANCIAL_HURDLE_FUTURE_SOURCE")
    h1_bytes=(root/H1_INPUT).read_bytes()
    if hashlib.sha256(h1_bytes).hexdigest()!=data["H1_eps_source_sha256"]:
        raise ValueError("0056_FINANCIAL_SOURCE_H1_EPS_HASH_MISMATCH")
    price_date=data["official_close_date"]
    price_bytes=(root/PRICE_DIR/f"{price_date}.json").read_bytes()
    if hashlib.sha256(price_bytes).hexdigest()!=data["official_price_sha256"]:
        raise ValueError("0056_FINANCIAL_SOURCE_CLOSE_HASH_MISMATCH")
    finrows=json.loads(h1_bytes)["rows"]
    official={r["code"]:r for r in finrows if r.get("code") in CODES}
    if len(official)!=9:
        raise ValueError("0056_FINANCIAL_SOURCE_H1_EPS_NINE_MISSING")
    prices=json.loads(price_bytes)
    price_by_code={r["code"]:r for r in prices if r.get("code") in CODES}
    if len(price_by_code)!=9:
        raise ValueError("0056_FINANCIAL_SOURCE_PRICE_NINE_MISSING")
    result=[]
    for row in rows:
        code=row["code"]
        official_row=official[code]
        price_row=price_by_code[code]
        book=row.get("book_per_share_2026q2_ntd")
        price=row.get("official_reference_close_ntd")
        eps=row.get("eps_2026_h1_official_ytd")
        pb=row.get("current_pb_multiple")
        proxy=row.get("h1_annualized_eps_divided_by_end_book_proxy_pct")
        if (not all(finite_number(x) and x>0 for x in (book,price,eps,pb,proxy))
            or row.get("formal_Aplus") is not False
            or row.get("bvps_secondary_not_primary_verified") is not True
            or row.get("financial_original_ROE_and_capital_quality_not_reviewed") is not True
            or row.get("financial_2027_price_upside_pct") is not None
            or row.get("financial_base_2027_PB") is not None
            or row.get("financial_base_2027_eps_ntd") is not None):
            raise ValueError("0056_FINANCIAL_ORIGINAL_AND_CERTIFICATION_FALSIFIED_"+code)
        if (official_row.get("market")!="TWSE" or official_row.get("period")!="2026-Q2"
            or official_row.get("company_PIT_verified") is not False
            or price_row.get("date")!=price_date or price_row.get("market")!="TWSE"
            or not finite_number(official_row.get("basic_eps_ytd"))
            or not finite_number(price_row.get("close"))
            or abs(official_row["basic_eps_ytd"]-eps)>1e-8
            or abs(price_row["close"]-price)>1e-8):
            raise ValueError("0056_FINANCIAL_SECONDARY_HURDLE_VS_OFFICIAL_MIRROR_CONFLICT_"+code)
        if (abs(pb-price/book)>1e-8 or
            abs(proxy-200*eps/book)>1e-8 or
            abs(row["illustrative_required_sustainable_roe_pct"]-(BASE_G+(BASE_KE-BASE_G)*pb))>1e-8 or
            abs(row["illustrative_required_roe_minus_h1_proxy_pp"]-
                (BASE_G+(BASE_KE-BASE_G)*pb-proxy))>1e-8):
            raise ValueError("0056_FINANCIAL_BASE_ROE_HURDLE_ARITHMETIC_INCONSISTENT_"+code)
        cases=[]
        for ke in K_E_PCTS:
            for g in G_PCTS:
                if g>=ke:
                    raise ValueError("0056_FINANCIAL_G_NOT_BELOW_KE")
                required=g+(ke-g)*pb
                gap=required-proxy
                cases.append(dict(Ke_pct=ke,g_pct=g,required_roe_pct=required,
                                  gap_vs_h1_proxy_pp=gap,
                                  h1_proxy_above_required=gap<0))
        diffs=[x["gap_vs_h1_proxy_pp"] for x in cases]
        plus=sum(x>0 for x in diffs)
        result.append(dict(code=code,name=row["name"],
            BVPS_2026q2_ntd=book,official_close_ntd=price,P_B=pb,
            H1_EPS_2026=eps,annualized_H1_EPS_over_ending_BVPS_pct=proxy,
            base_assumption_gap_pp=row["illustrative_required_roe_minus_h1_proxy_pp"],
            min_conditional_hurdle_gap_pp=min(diffs),
            max_conditional_hurdle_gap_pp=max(diffs),
            positive_gap_scenario_count=plus,
            negative_gap_scenario_count=sum(x<0 for x in diffs),
            zero_gap_scenario_count=sum(x==0 for x in diffs),
            sign_invariant_positive_across_grid=plus==len(cases),
            stress_cases=cases,
            issuer_original_BVPS_not_yet_verified=True,
            hypothetical_ke_g_cells_not_calibrated_probabilities=True,
            original_2027_price_target_available=False,
            formal_Aplus=False))
    result.sort(key=lambda x:(x["base_assumption_gap_pp"],x["code"]))
    return dict(schema=SCHEMA,source_hurdle_file=INPUT,
        source_hurdle_sha256=hashlib.sha256((root/INPUT).read_bytes()).hexdigest(),
        source_model_vintage=data["model_estimate_vintage"],
        holdings_date=data["membership_date"],official_close_date=data["official_close_date"],
        assumed_cost_of_equity_pct=list(K_E_PCTS),assumed_perpetual_growth_pct=list(G_PCTS),
        grid_scenario_count=len(K_E_PCTS)*len(G_PCTS),
        no_probability_or_scenario_calibration=True,
        no_2027_BVPS_or_ROE_forecast=True,
        no_2027_fair_price_estimated=True,
        no_full_50_stock_return_ranking=True,
        baseline_hurdle_is_not_investment_buy_signal=True,
        double_counting_dividends_or_original_book_adjustments_not_done=True,
        formal_Aplus_count_added=0,
        original_0056_nonfinancial_top10_unchanged=True,
        member_count=9,
        all_financials=result)


def write(result,path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix==".json":
        body=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    else:
        lines=["# 0056 金融股 ROE/PB 門檻：Ke/g 敏感度（非合理價）","",
            f"原模型形成 {result['source_model_vintage']}；持股和股價 {result['official_close_date']}；"
            "Q2 BVPS仍為第三方資料，非發行人原始財報核定。","",
            "統一情境：Ke = 8%、10%、12%；g = 0%、3%、5%。"
            "九組情境不是等機率或經統計校準的情境。","",
            "|股票|原 Ke10%/g3% 門檻差|九組最小差|九組最大差|正差組數|是否九組均為正差|",
            "|---|---:|---:|---:|---:|---|"]
        for row in result["all_financials"]:
            lines.append(
                f"|{row['code']} {row['name']}|{row['base_assumption_gap_pp']:+.1f}pp|"
                f"{row['min_conditional_hurdle_gap_pp']:+.1f}pp|"
                f"{row['max_conditional_hurdle_gap_pp']:+.1f}pp|"
                f"{row['positive_gap_scenario_count']}/9|"
                f"{'是' if row['sign_invariant_positive_across_grid'] else '否'}|")
        lines+=["",
            "門檻差＝g+(Ke-g)×目前P/B−(2026H1 EPS×2÷2026Q2期末BVPS)。"
            "其中當期替代獲利率並未校正季節性、股東權益平均餘額與OCI，"
            "不能當真實ROE，更不是2027 ROE。",
            "9/9正差意指在九種假設下市場隱含門檻均高於此替代獲利率，"
            "**不是確定高估或未來股價下跌的機率**；9種情境為研究者挑選，"
            "不能把6/9解讀為66.7%勝率。",
            "下游不修改任何2027 EPS、合理PE、股價、0056 TOP10或13項品質門檻。",
            "正式2027金融股比較尚缺2027歸母ROE、股利與資本留存、期初期末普通股股權、"
            "可轉債股數稀釋和保險子公司資產負債核對。",""]
        body="\n".join(lines)
    path.write_text(body,encoding="utf-8")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,default=Path("tw-market-data"))
    p.add_argument("--out",type=Path)
    args=p.parse_args()
    root=args.root
    source=json.loads((root/INPUT).read_text(encoding="utf-8"))
    result=sensitivity(source,root)
    if args.out:
        write(result,args.out)
        write(result,args.out.with_suffix(".md"))
    print("BEGIN_0056_FINANCE_SENSITIVITY="+json.dumps(dict(
        model=result["source_model_vintage"],
        nine=result["member_count"],grid=result["grid_scenario_count"],
        robust_positive=[x["code"] for x in result["all_financials"] if
                         x["sign_invariant_positive_across_grid"]],
        details=[dict(code=x["code"],n_positive=x["positive_gap_scenario_count"],
                      min_pp=round(x["min_conditional_hurdle_gap_pp"],1),
                      max_pp=round(x["max_conditional_hurdle_gap_pp"],1))
                 for x in result["all_financials"]]),ensure_ascii=False))


if __name__=="__main__":
    main()
