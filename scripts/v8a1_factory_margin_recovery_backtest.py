#!/usr/bin/env python3
"""V8.9.11: exploratory issuer-level gross/operating margin drawdown recovery.

Purpose: answer the *financial margin recovery proxy*, never an actual
new-factory commissioning success-rate claim. Historical issuer PIT publication
time and documented factory startup population are NOT verified. No trading.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path

QUARTERS = ("2024-Q3","2024-Q4","2025-Q1","2025-Q2","2025-Q3","2025-Q4","2026-Q1","2026-Q2")
STANDALONE = QUARTERS[1:]
MARKETS = ("TWSE","TPEX")
FIELDS = ("revenue_ytd_k","gross_profit_ytd_k","operating_profit_ytd_k")
MIN_QUARTER_REVENUE_K = 100_000  # NT$100m
GROSS_DROP = .02
OPERATING_DROP = .01
GROSS_REBOUND = .02
OPERATING_REBOUND = .01
ASOF_DEFAULT = "2026-10-21T23:59:59+08:00"


def _time(raw):
    if not isinstance(raw,str):
        raise ValueError("BACKTEST_SOURCE_TIMESTAMP_MISSING")
    try:
        t=datetime.fromisoformat(raw.replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("BACKTEST_SOURCE_TIMESTAMP_INVALID") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("BACKTEST_TIMEZONE_REQUIRED")
    return t.astimezone(timezone.utc)


def _number(raw):
    if isinstance(raw,bool) or not isinstance(raw,(float,int)) or not math.isfinite(raw):
        raise ValueError("BACKTEST_MISSING_OR_NONFINITE_FINANCIAL")
    return float(raw)


def load_quarters(root, asof):
    """Read company/period batches; no claims of historical real-time data."""
    time=_time(asof)
    maps, provenance = {}, []
    issuer_ids=set()
    for quarter in QUARTERS:
        year, q = quarter.split("-Q")
        for market in MARKETS:
            path=root/"fundamentals"/quarter/(market+"_income.json")
            data=json.loads(path.read_text(encoding="utf-8"))
            if (data.get("period"),data.get("market"),data.get("kind")) != (quarter,market,"income"):
                raise ValueError("BACKTEST_FINANCIAL_WRONG_BATCH")
            archive_at=_time(data.get("capture_utc"))
            if archive_at>time:
                raise ValueError("BACKTEST_ARCHIVE_FUTURE_AT_ASOF")
            if not isinstance(data.get("rows"),list):
                raise ValueError("BACKTEST_ROWS_NOT_ARRAY")
            by_code={}
            for row in data["rows"]:
                if not isinstance(row,dict) or row.get("market")!=market or row.get("period")!=quarter:
                    raise ValueError("BACKTEST_PERIOD_OR_MARKET_ROW_MISMATCH")
                code=str(row.get("code",""))
                if code in by_code:
                    raise ValueError("BACKTEST_DUPLICATE_COMPANY")
                by_code[code]=row
                if "2025-Q1" <= quarter <= "2025-Q4":
                    issuer_ids.add((market,code))
            maps[quarter,market]=by_code
            provenance.append(dict(period=quarter,market=market,captured_at=data["capture_utc"],
                                   batch_raw_sha256=data.get("raw_sha256"),
                                   company_original_PIT_verified=data.get("company_PIT_verified") is True,
                                   issuer_count=len(by_code)))
    return maps,provenance,sorted(issuer_ids)


def standalone(rows, quarter, market, code):
    row=rows.get((quarter,market),{}).get(code)
    if row is None or row.get("year_to_date_values") is not True or row.get("unit")!="NTD_thousands_except_EPS":
        return None
    year, q = quarter.split("-Q")
    prev=rows.get((f"{year}-Q{int(q)-1}",market),{}).get(code) if int(q)>1 else None
    if int(q)>1 and (prev is None or prev.get("year_to_date_values") is not True or prev.get("unit")!="NTD_thousands_except_EPS"):
        return None
    try:
        values=[_number(row.get(k)) - (_number(prev.get(k)) if prev is not None else 0)
                for k in FIELDS]
    except ValueError:
        return None
    rev,gp,op=values
    if rev<MIN_QUARTER_REVENUE_K:
        return None
    gm,om=gp/rev,op/rev
    # Eliminate pathological non-comparable consolidations and incoherent lines.
    if not (-.30<=gm<=1.00 and -.60<=om<=1.00):
        return None
    return dict(quarter=quarter,revenue_k=rev,gm=gm,om=om)


def wilson(k,n):
    if n==0:return None
    z=1.959963984540054
    p=k/n;den=1+z*z/n
    mid=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [round(100*(mid-half),2),round(100*(mid+half),2)]


def _pct(k,n):
    return round(100*k/n,2) if n else None


def evaluate_records(sequences, horizon):
    """Choose FIRST qualifying drawdown per issuer within a predeclared horizon.

    A current-below-prior 2pp GM +1pp operating margin shock must be observable.
    Subsequent missing quarters censor the issuer; don't select later wins.
    For horizon 2, entry = 2025Q1-Q4; horizon 4, entry=2025Q1-Q2.
    """
    if horizon not in (2,4):
        raise ValueError("BACKTEST_HORIZON_UNSUPPORTED")
    cohort=[]
    censored=[]
    byentry=defaultdict(lambda: dict(events=0,matured=0,censored=0,rebound=0,full=0,sustained=0))
    for key,values in sequences:
        if len(values)!=len(STANDALONE):
            raise ValueError("BACKTEST_SEQUENCE_LENGTH_MISMATCH")
        idx=None
        for i in range(1,min(4,6-horizon)+1):
            prev,current=values[i-1],values[i]
            if prev is None or current is None:
                continue
            if current["gm"]-prev["gm"] <= -GROSS_DROP and current["om"]-prev["om"] <= -OPERATING_DROP:
                idx=i
                break
        if idx is None:
            continue
        current,prior=values[idx],values[idx-1]
        entry=current["quarter"]
        byentry[entry]["events"]+=1
        future=values[idx+1:idx+1+horizon]
        if len(future)<horizon or any(x is None for x in future):
            censored.append(dict(market=key[0],code=key[1],entry=entry,reason="MISSING_OR_UNUSABLE_FOLLOWUP_ACCOUNTING"))
            byentry[entry]["censored"]+=1
            continue
        base_ok=[x["gm"]>=current["gm"]+GROSS_REBOUND
                 and x["om"]>=current["om"]+OPERATING_REBOUND for x in future]
        strict_ok=[x["gm"]>=prior["gm"] and x["om"]>=prior["om"] for x in future]
        gm_only=[x["gm"]>=current["gm"]+GROSS_REBOUND for x in future]
        row=dict(market=key[0],code=key[1],entry=entry,prior=prior["quarter"],
            gm_before_pp=round(prior["gm"]*100,3),gm_at_trough_pp=round(current["gm"]*100,3),
            operating_before_pp=round(prior["om"]*100,3),operating_at_trough_pp=round(current["om"]*100,3),
            recovery_2pp_gm_1pp_op_any=any(base_ok),
            returned_to_pre_drop_both_margins_any=any(strict_ok),
            recovery_meets_threshold_at_horizon=base_ok[-1],
            recovery_threshold_two_consecutive_quarters=any(base_ok[j] and base_ok[j-1] for j in range(1,len(base_ok))),
            returned_to_pre_drop_both_two_consecutive_quarters=any(strict_ok[j] and strict_ok[j-1] for j in range(1,len(strict_ok))),
            gm_only_2pp_any=any(gm_only),
            first_recovery_quarter=next((j+1 for j,ok in enumerate(base_ok) if ok),None))
        cohort.append(row)
        a=byentry[entry]
        a["matured"]+=1
        a["rebound"]+=row["recovery_2pp_gm_1pp_op_any"]
        a["full"]+=row["returned_to_pre_drop_both_margins_any"]
        a["sustained"]+=row["recovery_threshold_two_consecutive_quarters"]
    n=len(cohort)
    stats={}
    for metric,name in [
        ("recovery_2pp_gm_1pp_op_any","threshold_rebound_any"),
        ("returned_to_pre_drop_both_margins_any","full_pre_drop_recovery_any"),
        ("recovery_meets_threshold_at_horizon","threshold_met_last_quarter"),
        ("recovery_threshold_two_consecutive_quarters","threshold_two_consecutive_quarters"),
        ("returned_to_pre_drop_both_two_consecutive_quarters","full_pre_drop_two_consecutive_quarters"),
        ("gm_only_2pp_any","gross_margin_only_rebound")]:
        k=sum(bool(x[metric]) for x in cohort)
        stats[name]=dict(success=k,total=n,pct=_pct(k,n),wilson95pct=wilson(k,n))
    return dict(horizon_quarters=horizon,first_event_per_company=True,
                eligible_company_events=n+len(censored),matured_company_events=n,
                censored_company_events=len(censored),outcomes=stats,
                entry_quarter_cohorts={q:byentry[q] for q in sorted(byentry)},
                censored_issuers=censored,issuer_outcomes=cohort)


def build(root,asof):
    data,archive,ids=load_quarters(root,asof)
    sequences=[]
    for market,code in ids:
        sequences.append(((market,code),[standalone(data,q,market,code) for q in STANDALONE]))
    horizons={str(h):evaluate_records(sequences,h) for h in (2,4)}
    return dict(model="V8.9.11_MARGIN_RECOVERY_RESEARCH_NOT_FACTORY_RAMP_SUCCESS",
        asof=asof,financial_coverage_first=QUARTERS[0],
        financial_coverage_latest=QUARTERS[-1],
        historical_issuer_financial_release_PIT_verified=False,
        archival_batches_downloaded_2026_not_available_historically_to_strategy=True,
        company_universe_size=len(ids),
        gross_drop_threshold_pp=100*GROSS_DROP,
        operating_drop_threshold_pp=100*OPERATING_DROP,
        gross_recovery_threshold_pp=100*GROSS_REBOUND,
        operating_recovery_threshold_pp=100*OPERATING_REBOUND,
        minimum_prior_and_event_quarter_revenue_ntd=MIN_QUARTER_REVENUE_K*1000,
        quarterly_accounting_year_to_date_subtraction=True,
        original_factory_startup_event_cohort_verified=False,
        true_new_factory_ramp_success_rate_pct=None,
        true_new_factory_ramp_matured_cohort_count=None,
        stock_total_return_backtest_done=False,statistically_calibrated_strategy_alpha=None,
        source_archives=archive,horizons=horizons,
        case_9802=dict(code="9802",status="FACTORY_STARTUP_IN_2025H2_DOCUMENTED_BUT_OUTCOME_UNMATURED",
            latest_accounting="2026-Q2",next_income_quarter="2026-Q3",
            latest_q3_revenue_reported_not_a_gross_margin_release=True,
            current_factory_utilization_and_unit_material_labor_costs_not_verified=True,
            not_part_of_any_verified_factory_success_denominator=True),
        disclaimer=[
            "All reported percentages measure financial gross/operating margin drawdown recovery, NOT new-factory startup success.",
            "All 2024-2026 historic standardized statements were archived in October 2026; company-level original release timing is not PIT verified.",
            "A dip in margin may result from seasonality, price mix, FX, materials, inventory and accounting changes rather than factory startup.",
            "No actual predeclared new-factory commissioning sample is available; a factory success percentage would be an invention.",
            "Success within any future 2 or 4 quarters is a retrospective outcome, not a prospective signal known at entry.",
            "Only first eligible drawdown by issuer and each time horizon counted; missing follow-up censored, not assumed successful.",
            "Four-quarter success has more recovery opportunities and a smaller/different entry cohort; it must not be read as an improvement in certainty.",
            "To estimate true factory ramp success require issuer timestamped factory commencement, utilization/volume, unit labor and material, peer controls and at least 4-8 subsequent quarters.",
            "No EPS/PE/Base target changes, no A+/A++ upgrades, no trading actions, no valid stock return strategy backtest."
        ],
        formal_Aplus_changed=False,base_eps_pe_target_changed=False)


def report_md(r):
    lines=["# V8.9.11｜毛利衰退回升的歷史代理回測（非新廠成功率）","",
        f"會計資料範圍：{r['financial_coverage_first']}～{r['financial_coverage_latest']}；公司母體：{r['company_universe_size']}。",
        "**真正有明確新廠建置／投產日期且完成觀察期的同質樣本未建立，因此『新廠爬坡成功率』= 無法估計（不是0%）。**",
        "",
        "## 回測規則（不可用事後成功股反挑樣本）","",
        "- 從各公司『單季』2025Q1～Q4（4季期限僅2025Q1～Q2），首次發生毛利率比前季降至少2pp、營業利益率降至少1pp且前後季度營收均達1億元者視為財務低谷事件。",
        "- 成功定義A：未來觀察期限內同一季毛利率相對低谷提升至少2pp、營業利益率提升至少1pp。",
        "- 成功定義B：未來某一季毛利率和營業利益率**都回到跌落前一季的水準**。",
        "- 另外計算A及B是否連續2季達標，避免把一次季節性反彈當成功。",
        "- 若期間有財報缺漏，一律列截尾，不補完後面的季度，也不改選同一家較晚的漂亮進場點。",
        "",
        "|期限|第一事件數|成熟可評樣本|截尾|A：小幅反彈|B：回到跌前|A連兩季|B連兩季|",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for key in ("2","4"):
        x=r["horizons"][key];o=x["outcomes"]
        lines.append(f"|{key}季|{x['eligible_company_events']}|{x['matured_company_events']}|{x['censored_company_events']}|"
                     f"{o['threshold_rebound_any']['success']}/{o['threshold_rebound_any']['total']}（{o['threshold_rebound_any']['pct']:.1f}%）|"
                     f"{o['full_pre_drop_recovery_any']['success']}/{o['full_pre_drop_recovery_any']['total']}（{o['full_pre_drop_recovery_any']['pct']:.1f}%）|"
                     f"{o['threshold_two_consecutive_quarters']['pct']:.1f}%|"
                     f"{o['full_pre_drop_two_consecutive_quarters']['pct']:.1f}%|")
    lines += ["","## 抽樣統計不確定性（不是模型回報預測信賴區間）",""]
    for key in ("2","4"):
        x=r["horizons"][key]
        for stat in ("threshold_rebound_any","full_pre_drop_recovery_any"):
            y=x["outcomes"][stat]
            lines.append(f"- {key}季 {stat}：{y['pct']:.2f}%；Wilson描述性95%區間：{y['wilson95pct'][0]:.2f}%～{y['wilson95pct'][1]:.2f}%。")
    lines += ["","## 入選季別與存活／資料缺漏","",
              "|觀察期限|衰退起始季|符合事件數|未截尾|反彈成功|恢復原有利潤|",
              "|---|---|---:|---:|---:|---:|"]
    for key in ("2","4"):
        for q,record in r["horizons"][key]["entry_quarter_cohorts"].items():
            lines.append(f"|{key}季|{q}|{record['events']}|{record['matured']}|{record['rebound']}|{record['full']}|")
    lines += ["","## 鞋業與9802可使用的結論","",
        "- 這是全市場不同產業的**一般財務回升機率描述**，尚未以『確定有新廠投產』分層，也未控制景氣、競爭、產業毛利常態及企業結構。",
        "- 鈺齊9802新廠2025年下半年開始試量產，2026Q2 GM 13.94%；截至2026/10/21只公布Q3營收，**未公布Q3毛利/人工材料費**，故不能判定它已經完成爬坡。",
        "- 尤其2026Q2鈺齊直接材料/人工成本負擔相較2025Q2增加約5.25pp，未有各廠人工訓練成本或材料/售價可逆性的充分原件。",
        "- 將『小幅反彈』和『完全恢復原先獲利率』分開，是為了避免把一般均值回歸當成2027年17%～18%毛利率復甦的證據。",
        "","## 資料證據與回測限制","",*("- "+s for s in r["disclaimer"]),"",
        "**結論：不可將上表任何百分比用作9802新廠成功機率，亦不變更正式EPS/PE/Base/A+。**",""]
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="tw-market-data")
    p.add_argument("--asof",default=ASOF_DEFAULT)
    args=p.parse_args()
    root=Path(args.data_dir)
    out=build(root,args.asof)
    target=root/"rankings";target.mkdir(parents=True,exist_ok=True)
    (target/"v8a1_factory_margin_recovery_backtest.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (target/"v8a1_factory_margin_recovery_backtest.md").write_text(report_md(out),encoding="utf-8")
    print(json.dumps({"company_universe_size":out["company_universe_size"],
                      "mature_2q":out["horizons"]["2"]["matured_company_events"],
                      "rebound_2q":out["horizons"]["2"]["outcomes"]["threshold_rebound_any"]["pct"],
                      "full_2q":out["horizons"]["2"]["outcomes"]["full_pre_drop_recovery_any"]["pct"],
                      "mature_4q":out["horizons"]["4"]["matured_company_events"],
                      "rebound_4q":out["horizons"]["4"]["outcomes"]["threshold_rebound_any"]["pct"],
                      "full_4q":out["horizons"]["4"]["outcomes"]["full_pre_drop_recovery_any"]["pct"],
                      "true_factory_ramp_success_rate":None},ensure_ascii=False))


if __name__=="__main__":
    main()
