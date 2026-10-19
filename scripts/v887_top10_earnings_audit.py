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


def check_post_financial_quarter_revenue(root, research, now_income, prior_income, top):
    """Watch next-quarter published YTD monthly sales without treating it as Q3 profits.

    Checks captured source receipt and each issuer's shard bytes; fails closed on
    mixed periods/duplicate codes, missing same-basis H1 income or future capture.
    Does not mutate model EPS or A+ decisions.
    """
    import datetime as datetime_module
    from zoneinfo import ZoneInfo
    result = {"status":"NOT_YET_CHECKED","issuer_checks":[],
              "issuer_filing_PIT_verified":False,"recognized_quarterly_profit_verified":False}
    path = root / "latest_manifest.json"
    if not path.exists():
        result["status"]="NO_MONTHLY_MANIFEST"
        return result
    manifest=load(path)
    fin=str(research.get("financial_last_quarter",""))
    import re
    match=re.fullmatch(r"(20\d{2})-Q([1-4])",fin)
    if match is None:
        raise ValueError("INVALID_FINANCIAL_PERIOD_FOR_REVENUE_CROSSCHECK")
    year,quarter=map(int,match.groups())
    next_month=quarter*3+3
    if next_month>12:
        result["status"]="NEXT_QUARTER_AFTER_YEAR_END_NOT_SUPPORTED_YET"
        return result
    expected=f"{year:04d}-{next_month:02d}"
    if manifest.get("period")!=expected:
        result["status"]="NEXT_QUARTER_MONTH_NOT_PUBLISHED"
        result["expected"]=expected
        result["published_month"]=manifest.get("period")
        return result
    stamp=datetime_module.datetime.fromisoformat(str(manifest.get("capture_utc","")).replace("Z","+00:00"))
    estimate=datetime_module.datetime.fromisoformat(str(research.get("estimate_vintage","")).replace("Z","+00:00"))
    if stamp.tzinfo is None or estimate.tzinfo is None or stamp>estimate:
        raise ValueError("MONTHLY_REVENUE_RECEIPT_FUTURE_OR_UNZONED")
    wanted=set(str(item["code"]) for item in top)
    shards=manifest.get("shards",[])
    found={}
    for item in shards:
        shard=root.parent / str(item.get("path",""))
        if not shard.is_file() or root.parent not in shard.parents:
            raise ValueError("MISSING_OR_UNSAFE_MONTHLY_REVENUE_SHARD")
        raw=shard.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item.get("sha256"):
            raise ValueError("MONTHLY_REVENUE_SHARD_SHA_MISMATCH")
        rows=json.loads(raw)
        if len(rows)!=item.get("records"):
            raise ValueError("MONTHLY_REVENUE_SHARD_SIZE_MISMATCH")
        for data in rows:
            code=str(data.get("code",""))
            if code not in wanted:
                continue
            if (code in found or data.get("report_month")!=f"{year-1911:03d}{next_month:02d}"
                    or data.get("market") not in ("TWSE","TPEX")):
                raise ValueError("MONTHLY_REVENUE_ISSUER_DUPLICATE_OR_PERIOD_MISMATCH")
            found[code]=data
    if wanted-set(found):
        result["status"]="ISSUER_MONTHLY_REVENUE_MISSING"
        result["missing_codes"]=sorted(wanted-set(found))
        return result
    for row in top:
        code=str(row["code"]);market=row["market"]
        new=now_income[(market,code)]
        prior=prior_income[(market,code)]
        data=found[code]
        if data["market"]!=market:
            raise ValueError("MONTHLY_REVENUE_MARKET_MISMATCH")
        newer=int(str(data["ytd_revenue_k"]).replace(",",""))
        older=int(str(data["last_year_ytd_revenue_k"]).replace(",",""))
        current_base=numeric(new["revenue_ytd_k"],"current_baseline")
        prior_base=numeric(prior["revenue_ytd_k"],"prior_baseline")
        quarter_now=newer-current_base
        quarter_then=older-prior_base
        if quarter_now<=0 or quarter_then<=0:
            raise ValueError("NEXT_QUARTER_YTD_SUBTRACTION_INVALID")
        half_yoy=pct(current_base-prior_base,prior_base)
        q_yoy=pct(quarter_now-quarter_then,quarter_then)
        slowdown=round(q_yoy-half_yoy,2)
        result["issuer_checks"].append({
            "code":code,"name":row.get("name"),"market":market,
            "latest_monthly_report":expected,"three_month_revenue_k":round(quarter_now),
            "prior_three_month_revenue_k":round(quarter_then),
            "current_financial_H1_yoy_pct":half_yoy,
            "next_quarter_revenue_yoy_pct":q_yoy,
            "yoy_deceleration_pp":slowdown,
            "growth_decelerated_over_20pp":slowdown<=-20.0,
            "monthly_revenue_individual_PIT_verified":False,
            "gross_margin_for_next_quarter_verified":False
        })
    result["status"]="NEXT_QUARTER_REVENUE_RECONCILED_BUT_MARGIN_UNVERIFIED"
    result["official_monthly_capture_utc"]=manifest["capture_utc"]
    result["monthly_archive_period"]=expected
    result["monthly_manifest_original_receipts"]=manifest.get("original_receipts",[])
    return result



def equity_issuance_audit(root, research, top, today=None):
    """Curated dated equity offer facts. Do not write forecast changes or A+."""
    path = root / "evidence/v880/issuer_reviews/top3_20261020.json"
    if not path.exists():
        return dict(status="SOURCE_REVIEW_NOT_PRESENT",scenarios=[],formal_grade_updated=False)
    note=load(path)
    if note.get("document_type")!="V8.8.7_TOP3_ORIGINAL_PUBLICATION_AUDIT_RESEARCH_ONLY":
        raise ValueError("UNEXPECTED_REVIEW_DOC_TYPE")
    match=next((v for v in note.get("issuer_reviews",[]) if v.get("code")=="8390"),None)
    if match is None or "equity_issuance" not in match:
        return dict(status="REVIEW_WITHOUT_EQUITY_EVENT",scenarios=[],formal_grade_updated=False)
    details=match["equity_issuance"]
    old_shares=int(details["capital_master_shares_asof_2026_10_06"])
    filed=int(details["filed_new_shares_from_nominal"])
    board_max=int(details["board_max_new_shares"])
    if (old_shares<=0 or filed<=0 or board_max<filed or
        int(details["filed_nominal_twd"])!=filed*int(details["nominal_value_per_share_twd"])):
        raise ValueError("INVALID_EQUITY_ISSUANCE_UNITS")
    if details.get("issuance_completed") is not False or details.get("regulator_effectiveness_confirmed") is not False:
        raise ValueError("EVENT_CHANGED_REQUIRES_FRESH_MANUAL_EVIDENCE")
    now=today or dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    if not isinstance(now,dt.date):
        raise ValueError("INVALID_CURRENT_DATE_FOR_EVENT_STATUS")
    scheduled=dt.date.fromisoformat(details["originally_scheduled_effective_date"])
    if now>scheduled:
        return dict(status="SCHEDULED_EFFECTIVE_DATE_ELAPSED_RECHECK_OFFICIAL_ISSUANCE",
                    scheduled_effective_date=scheduled.isoformat(),
                    review_date=note.get("review_date"),
                    issuance_execution_verified=False,scenarios=[],formal_grade_updated=False,
                    next_action="Check regulator effectiveness, actual issued share count, offering price and company master before any fresh EPS adjustment.")
    row=next((v for v in top if v.get("code")=="8390"),None)
    if row is None:
        return dict(status="ISSUER_NOT_IN_CURRENT_TOP10",scenarios=[],formal_grade_updated=False)
    price_date=research.get("asof_price_date")
    reference_date=note.get("price_reference_date")
    if price_date!=reference_date:
        return dict(status="REFERENCE_DATE_CHANGED_RECHECK_SHARE_MASTER_AND_CORPORATE_ACTION",
                    source_note_date=note.get("review_date"),reference_price_date=reference_date,
                    current_model_price_date=price_date,scenarios=[],formal_grade_updated=False)
    ref=int(details["capital_master_shares_asof_2026_10_06"])
    eps=numeric(row["base"]["eps"],"8390_EPS")
    target=numeric(row["base"]["target_price"],"8390_target")
    px=numeric(row["reference_close"],"8390_ref_px")
    if not (eps>0 and px>0 and target>0):
        raise ValueError("INVALID_EQUITY_BASE")
    if abs(px-float(details["scenario_asof_reference_price"]))>0.01:
        raise ValueError("MODEL_PRICE_AND_EVENT_PRICE_NOT_SAME_REFERENCE")
    scenarios=[]
    for label,new in (("NO_NEW_SHARES",0),("FILED_8M_NOT_EFFECTIVE",filed),("BOARD_MAX_10M_NOT_APPROVED_FINAL",board_max)):
        factor=ref/(ref+new)
        scenarios.append(dict(label=label,new_shares=new,
                              assumed_pre_event_shares=ref,
                              shares_post_hypothetical_event=ref+new,
                              dilution_pct=round(100*(1-factor),2),
                              eps_2027_fixed_profit=round(eps*factor,2),
                              target_2027_fixed_profit=round(target*factor,2),
                              upside_fixed_profit_pct=round(100*(target*factor/px-1),2),
                              annual_incremental_profit_ntd_to_preserve_EPS=round(eps*new)))
    available=research.get("top30_provisional",[])
    for sc in scenarios:
        up=sc["upside_fixed_profit_pct"]
        if len(available)>=20 and all(isinstance(z.get("base",{}).get("price_upside_pct"),(int,float)) for z in available):
            other=[z for z in available if z.get("code")!="8390"]
            sc["conditional_research_rank_within_top30"]=1+sum(z["base"]["price_upside_pct"]>up for z in other)
            sc["rank_is_full_universe_certified"]=False
    return dict(status="SCENARIO_ONLY_ISSUANCE_NOT_CONFIRMED",
                board_announcement_date=details["board_resolution_date"],
                regulator_filing_date=details["filing_received_date"],
                filing_expected_effectiveness_date=details["originally_scheduled_effective_date"],
                primary_source_urls=[details["filed_amount_source"],details["board_source"],details["capital_master_source"]],
                forecast_share_denominator_legally_verified=False,
                shares_already_in_model_issuer_specific_confirmed=False,
                incremental_proceeds_earnings_included=False,
                new_issue_execution_verified=False,
                audit_or_Aplus_changed=False,
                formal_grade_updated=False,scenarios=scenarios,
                caveat="This ratio holds total profit and PE constant. It assumes the pre-issuance share count is not already adjusted for the new equity raise and adds no earnings from proceeds. Do not add again after any new company master update.")


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
    quarterly_lookup = {
        "now":{(m,c):r for (period,m,k),rows in mirrors.items() if period==quarter and k=="income" for c,r in rows.items()},
        "prior":{(m,c):r for (period,m,k),rows in mirrors.items() if period==previous and k=="income" for c,r in rows.items()},
    }
    next_quarter_revenue=check_post_financial_quarter_revenue(root,research,quarterly_lookup["now"],quarterly_lookup["prior"],top)
    checks={r["code"]:r for r in next_quarter_revenue.get("issuer_checks",[])}
    for record in out:
        if record["code"] in checks:
            record["next_quarter_revenue"]=checks[record["code"]]
            if checks[record["code"]]["growth_decelerated_over_20pp"]:
                record["flags"].append("NEXT_QUARTER_REVENUE_YOY_DECELERATED_OVER_20PP")
    share_event=equity_issuance_audit(root,research,top)
    for record in out:
        if record["code"]=="8390":
            if share_event["status"]=="SCENARIO_ONLY_ISSUANCE_NOT_CONFIRMED":
                record["flags"].append("PENDING_CASH_EQUITY_RAISE_8M_FILED_UP_TO_10M_BOARD_LIMIT")
            elif share_event["status"]=="SCHEDULED_EFFECTIVE_DATE_ELAPSED_RECHECK_OFFICIAL_ISSUANCE":
                record["flags"].append("CASH_EQUITY_ISSUANCE_EFFECTIVE_DATE_PASSED_RECHECK")
    result={
        "model":research.get("model"),"estimate_vintage":research.get("estimate_vintage"),
        "asof_price_date":research.get("asof_price_date"),
        "financial_period":quarter,"prior_comparable":previous,
        "financial_sources":receipts,
        "next_quarter_monthly_revenue_check":next_quarter_revenue,
        "equity_raise_watch":share_event,
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
    lines+=["","## 2026Q3 月營收對照（僅營收，非已驗證EPS）","",
            "這是本輪研究估值之後已公開的最新月份資料；公司逐筆公告PIT與下季毛利率仍未驗證。",
            "狀態："+next_quarter_revenue["status"],""]
    if next_quarter_revenue.get("issuer_checks"):
        lines+=["|公司|上半年營收YoY|第三季營收YoY|年增加速度(百分點)|需覆核|",
                "|---|---:|---:|---:|---|"]
        for record in next_quarter_revenue["issuer_checks"]:
            lines.append(f"|{record['code']} {record.get('name') or ''}|{record['current_financial_H1_yoy_pct']:+.2f}%|{record['next_quarter_revenue_yoy_pct']:+.2f}%|{record['yoy_deceleration_pp']:+.2f}|{'**年增大幅減速**' if record['growth_decelerated_over_20pp'] else '季報毛利與訂單待核'}|")
    lines+=["","## 8390 現金增資潛在稀釋（未生效、未完成，不是新 Base）","",
            "狀態："+share_event["status"],""]
    if share_event.get("scenarios"):
        lines+=["|股數情境|假設新增股數|固定獲利 EPS|固定獲利合理價|對參考價漲幅|維持原 EPS 所需新增年淨利(億元)|情境順位|",
                "|---|---:|---:|---:|---:|---:|---:|"]
        for sc in share_event["scenarios"]:
            lines.append(f"|{sc['label']}|{sc['new_shares']:,}|{sc['eps_2027_fixed_profit']:.2f}|{sc['target_2027_fixed_profit']:.2f}|{sc['upside_fixed_profit_pct']:+.2f}%|{sc['annual_incremental_profit_ntd_to_preserve_EPS']/100000000:.2f}|{sc.get('conditional_research_rank_within_top30','待核')}|")
        lines+=["",share_event["caveat"],"",
                "原始決議及申報來源："+", ".join(share_event["primary_source_urls"])]
    else:
        lines+=["預期股數／股價日期需要重新核對，未顯示過期稀釋試算。"]
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
