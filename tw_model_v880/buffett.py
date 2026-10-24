"""Buffett owner-economics research: proof before a dollar-valued estimate.

Read-only output. Neither generic FCF nor EPS*PE is treated as owner earnings
or proof of a moat. Financial values in the 9802 source are TWD thousands.
"""
from __future__ import annotations

import math


def number(value, field, *, nonnegative=False, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("BUFFETT_INVALID_" + field.upper())
    n = float(value)
    if positive and n <= 0 or nonnegative and n < 0:
        raise ValueError("BUFFETT_INVALID_" + field.upper())
    return n


def owner_earnings_from_reviewed_inputs(*, parent_net_profit, depreciation,
                                       amortization, maintenance_capex,
                                       incremental_sustaining_working_capital):
    """Accounting approximation only for independently established components.

    Do not pass OCF as parent_net_profit: OCF already reflects actual working
    capital and would double-count it. Growth capex must be separated from
    maintenance capex using issuer evidence, not a generic percentage.
    """
    profit = number(parent_net_profit, "parent_net_profit")
    dep = number(depreciation, "depreciation", nonnegative=True)
    amort = number(amortization, "amortization", nonnegative=True)
    maintenance = number(maintenance_capex, "maintenance_capex", nonnegative=True)
    sustaining_wc = number(incremental_sustaining_working_capital,
                           "incremental_sustaining_working_capital")
    return profit + dep + amort - maintenance - sustaining_wc


def incremental_roic_from_reviewed_annual_inputs(*, prior_annual_nopat,
                                                 current_annual_nopat,
                                                 prior_invested_capital,
                                                 current_invested_capital):
    """Comparable *annual*, normalized, after-tax operating profit observations.

    This is a diagnostic ratio, not automatically the economic return from
    new capex; acquisitions, inflation, extraordinary items and timing need
    a separate documented bridge.
    """
    before = number(prior_annual_nopat, "prior_annual_nopat")
    after = number(current_annual_nopat, "current_annual_nopat")
    capital_before = number(prior_invested_capital, "prior_invested_capital", positive=True)
    capital_after = number(current_invested_capital, "current_invested_capital", positive=True)
    increment = capital_after - capital_before
    if increment <= 0:
        raise ValueError("BUFFETT_NONPOSITIVE_INCREMENTAL_CAPITAL")
    return (after - before) / increment


def owner_earnings_discounted_scenario(*, annual_owner_earnings, required_return,
                                       terminal_growth, diluted_shares):
    """Explicit 3–5-year equity-value sensitivity, not a certified target price.

    Input must be shareholder-attributable earnings after maintenance needs.
    No enterprise cash/debt adjustment is applied a second time. Future
    forecasts, discount rate and terminal growth require separately reviewed
    issuer-specific evidence before use in published investment decisions.
    """
    if not isinstance(annual_owner_earnings, (tuple, list)) or not 3 <= len(annual_owner_earnings) <= 5:
        raise ValueError("BUFFETT_THREE_TO_FIVE_YEAR_FORECAST_REQUIRED")
    cash = [number(n, "annual_owner_earnings") for n in annual_owner_earnings]
    r = number(required_return, "required_return", positive=True)
    g = number(terminal_growth, "terminal_growth")
    shares = number(diluted_shares, "diluted_shares", positive=True)
    if g <= -1 or g >= r:
        raise ValueError("BUFFETT_UNSUPPORTED_TERMINAL_GROWTH")
    if cash[-1] <= 0:
        raise ValueError("BUFFETT_NONPOSITIVE_TERMINAL_OWNER_EARNINGS")
    terminal = cash[-1] * (1 + g) / (r - g)
    pv = sum(c / (1+r)**(i+1) for i, c in enumerate(cash))
    pv += terminal / (1+r)**len(cash)
    return dict(pv_equity_value=pv, per_share_value=pv/shares,
                forecast_years=len(cash),
                terminal_value_share_of_pv=terminal/(1+r)**len(cash)/pv if pv > 0 else None,
                model="EXPLICIT_ASSUMPTION_SENSITIVITY_NOT_CERTIFIED_FAIR_VALUE")


def _issuer_id(row):
    code, market = row.get("code"), row.get("market")
    if not isinstance(code, str) or not code or not isinstance(market, str) or not market:
        raise ValueError("BUFFETT_ISSUER_IDENTITY_REQUIRED")
    return market, code


def _signed_halfyear(source, key, idx):
    signed = source.get("cashflow_signed_k")
    raw = signed.get(key) if isinstance(signed, dict) else None
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError("BUFFETT_MISSING_COMPARABLE_CASHFLOW_" + key.upper())
    return number(raw[idx], key)


def historical_free_cash_flow_proxy(original_cash_review):
    """Diagnostic actual OCF+signed PPE cashflow, never owner earnings."""
    if original_cash_review.get("status") != "ORIGINAL_9802_H1_CASH_AND_WC_ARITHMETIC_RECONCILED_NOT_FULL_CASH_GATE":
        raise ValueError("BUFFETT_CASH_REVIEW_NOT_ORIGINAL_RECONCILED")
    cur=original_cash_review.get("current_h1") or {}
    prior=original_cash_review.get("prior_h1") or {}
    if cur.get("year") != 2026 or prior.get("year") != 2025 or cur.get("days_in_h1") != prior.get("days_in_h1"):
        raise ValueError("BUFFETT_CASH_COMPARABLE_PERIOD_REQUIRED")
    records=[]
    for idx,year in enumerate((2026,2025)):
        ocf=_signed_halfyear(original_cash_review,"ocf",idx)
        ppe=_signed_halfyear(original_cash_review,"ppe",idx)
        dividend=_signed_halfyear(original_cash_review,"dividends_paid",idx)
        if ppe > 0 or dividend > 0:
            raise ValueError("BUFFETT_CAPEX_OR_DIVIDEND_SIGN_WRONG")
        records.append(dict(period=f"{year}H1", ocf_k=ocf, total_ppe_cash_outflow_k=-ppe,
                            fcf_after_all_ppe_k=ocf+ppe,
                            cash_dividends_paid_k=-dividend,
                            owner_earnings_k=None,
                            owner_earnings_status="NOT_CALCULABLE_MAINTENANCE_CAPEX_AND_SUSTAINING_WC_UNVERIFIED"))
    return dict(status="H1_ORIGINAL_RECONCILED_FCF_PROXY_NOT_OWNER_EARNINGS",
                currency="TWD", unit="thousands", years=records,
                historical_periods_do_not_predict_future_fcf=True,
                negative_fcf_not_automatically_value_destruction=True)


def build(institutional, cash_review=None):
    if institutional.get("schema") != "V810_INSTITUTIONAL_RESEARCH_CONTROLS":
        raise ValueError("BUFFETT_INVALID_INSTITUTIONAL_SCHEMA")
    model,vintage,price=(institutional.get(k) for k in ("model","estimate_vintage","asof_price_date"))
    if not all(isinstance(v,str) and v for v in (model,vintage,price)):
        raise ValueError("BUFFETT_MISSING_SOURCE_VINTAGE")
    focus=institutional.get("issuer_reviews")
    if not isinstance(focus,list) or not focus:
        raise ValueError("BUFFETT_INSTITUTIONAL_COVERAGE_MISSING")
    rows=[];seen=set()
    for issuer in focus:
        key=_issuer_id(issuer)
        if key in seen:raise ValueError("BUFFETT_DUPLICATE_ISSUER")
        seen.add(key)
        review=issuer.get("review_work")
        if not isinstance(review,list) or len(review)!=13:
            raise ValueError("BUFFETT_FORMAL_GATE_REVIEW_MISSING")
        if any(x.get("decision") not in ("PASS","FAIL","PENDING") for x in review):
            raise ValueError("BUFFETT_INVALID_GATE_STATE")
        if issuer.get("formal_Aplus") and any(x["decision"]!="PASS" for x in review):
            raise ValueError("BUFFETT_UNSUPPORTED_FORMAL_A_PLUS")
        diag=issuer.get("valuation_diagnostics") or {}
        row=dict(code=key[1],market=key[0],name=issuer.get("name"),
                 financial_period=issuer.get("financial_period"),
                 cashflow_period=issuer.get("cashflow_financial_period"),
                 price_scenario_upside_pct=issuer.get("base_upside_pct"),
                 formal_Aplus_original=bool(issuer.get("formal_Aplus")),
                 recommendation_blocked_original=bool(issuer.get("recommendation_blocked")),
                 owner_earnings=dict(status="PENDING_MAINTENANCE_CAPEX_AND_SUSTAINING_WC_SPLIT",amount_k=None),
                 incremental_roic=dict(status="PENDING_TWO_COMPARABLE_ANNUAL_NOPAT_AND_INVESTED_CAPITAL",value=None),
                 moat_durability=dict(status="PENDING_MULTIPLE_YEARS_OF_COMPETITIVE_EVIDENCE",
                                      cannot_infer_from_single_margin_or_brand=True),
                 three_to_five_year_owner_value=dict(status="PENDING_REVIEWED_OWNER_EARNINGS_FORECAST_AND_DISCOUNT_ASSUMPTIONS",per_share_value=None),
                 capital_allocation=dict(status="PENDING_CASH_USES_BY_PERIOD_AND_INCREMENTAL_RETURNS"),
                 forward_operating_bridge_certified=diag.get("forward_annual_profit_bridge_verified") is True,
                 existing_valuation_and_formal_gates_unchanged=True,
                 investment_recommendation_generated=False)
        rows.append(row)
    applied=0
    if cash_review is not None:
        if (cash_review.get("model")!=model or cash_review.get("estimate_vintage")!=vintage
            or cash_review.get("price_date")!=price or cash_review.get("code")!="9802"
            or cash_review.get("research_only") is not True
            or cash_review.get("changes_eps_or_target_price") is not False
            or cash_review.get("grants_quality_certification") is not False):
            raise ValueError("BUFFETT_CASH_VINTAGE_OR_RESEARCH_CONTRACT_MISMATCH")
        matched=[r for r in rows if r["code"]=="9802"]
        if len(matched)!=1 or matched[0]["financial_period"]!=cash_review.get("income_period") or matched[0]["cashflow_period"]!=cash_review.get("cashflow_period"):
            raise ValueError("BUFFETT_9802_PERIOD_IDENTITY_MISMATCH")
        original=cash_review.get("original_cash_review") or {}
        if original.get("formal_cash_and_working_capital_gate_pass") is not False:
            raise ValueError("BUFFETT_CASH_SOURCE_STATUS_MISMATCH")
        historical=historical_free_cash_flow_proxy(original)
        matched[0]["owner_earnings"]["historical_fcf_proxy"]=historical
        matched[0]["capital_allocation"]=dict(
            status="PARTIAL_H1_PPE_SPENDING_AND_CASH_DIVIDENDS_ONLY",
            cash_uses_by_period=[dict(period=p["period"],
                                      ppe_cash_outflow_k=p["total_ppe_cash_outflow_k"],
                                      cash_dividends_paid_k=p["cash_dividends_paid_k"]) for p in historical["years"]],
            maintenance_vs_growth_capex_unverified=True,
            historical_h1_data_not_2027_forecast=True)
        applied=1
    return dict(schema="V811_BUFFETT_OWNER_ECONOMICS_RESEARCH_ONLY_V1",
                model=model,estimate_vintage=vintage,asof_price_date=price,
                institutional_issuer_count=len(rows),
                original_certified_Aplus_count=institutional.get("formal_Aplus_count"),
                verified_owner_earnings_count=0,
                verified_incremental_roic_count=0,
                issuer_cash_original_case_count=applied,
                issuer_reviews=rows,
                source_valuation_unchanged=True,
                original_13_gates_unchanged=True,
                new_certifications_issued=0,trade_orders_created=0,
                outperformance_not_proven=True)


def render(report):
    lines=["# 巴菲特股東盈餘與資本配置｜原件優先研究","",
           f"主模型：{report['model']}；估值時點：{report['estimate_vintage']}；股價基準：{report['asof_price_date']}。","",
           f"覆核範圍：既有機構深度觀察 {report['institutional_issuer_count']} 檔；實際股東盈餘認證 {report['verified_owner_earnings_count']} 檔；已完成新增ROIC驗證 {report['verified_incremental_roic_count']} 檔。","",
           "**研究附表，非正式A+、非估值修訂、非投資推薦。**","",
           "|股票|股東盈餘|增量ROIC|護城河|3–5年價值|資本配置|",
           "|---|---|---|---|---|---|"]
    def tidy(v):
        return str(v).replace("|","/").replace("\n"," ").replace("\r"," ")
    for r in report["issuer_reviews"]:
        lines.append("|{code} {name}|{owner}|{roic}|{moat}|{long}|{allocation}|".format(
            code=tidy(r["code"]),name=tidy(r["name"]),
            owner="待原始維持CAPEX與必要營運資金" if r["owner_earnings"]["amount_k"] is None else "資料已驗",
            roic="待年度NOPAT與投入資本",
            moat="待多年競爭證據",
            long="待已驗現金流及折現假設",
            allocation="H1部分現金用途" if r["capital_allocation"]["status"].startswith("PARTIAL") else "待原始資本用途"))
    if report.get("source_rejections"):
        lines+=["", "## 原始檔案被隔離（其他公司照常評估）", "",
                "以下公司未採用不完整或驗證失敗的現金流資料；不將缺值填零或推定安全。"]
        for error in report["source_rejections"]:
            lines.append("- "+tidy(error["code"])+": "+tidy(error["status"])+
                         "；原因："+tidy(error["reason"]))
    for row in report["issuer_reviews"]:
        proxy=row["owner_earnings"].get("historical_fcf_proxy")
        if proxy:
            lines+=["",f"## {tidy(row['code'])} {tidy(row['name'])}：原始報表現金流初步核對","",
                    "現金流金額為新台幣億元。FCF=OCF−全部PPE現金支出，含成長投資；**不是**Owner Earnings，亦非長期常態值。","",
                    "|比較半年|營業現金流|設備支出|FCF（扣全部設備）|實付股利|",
                    "|---|---:|---:|---:|---:|"]
            for p in proxy["years"]:
                lines.append("|{period}|{ocf:+.2f}|{capex:.2f}|{fcf:+.2f}|{dividend:.2f}|".format(
                    period=p["period"],ocf=p["ocf_k"]/100000,capex=p["total_ppe_cash_outflow_k"]/100000,
                    fcf=p["fcf_after_all_ppe_k"]/100000,dividend=p["cash_dividends_paid_k"]/100000))
            lines+=["","因尚未拆分維持性及成長性資本支出、必要新增營運資金、下一年度現金流，不得轉成2027股東盈餘或合理價。"]
    lines+=["","## 未通過前不能作出的結論","",
            "- 把單一高毛利率、品牌或高ROE直接等同經濟護城河。",
            "- 把擴廠負FCF直接等同長期競爭力惡化，或把預估EPS當成股東現金。",
            "- 未經原件支持就自動年化半年現金流、估計維持性CAPEX或長期股東盈餘。",
            "- 未有完整歷史PIT／成本／成交資料就宣稱巴菲特模組擊敗0050。",
            "- 用研究附表給任何公司發A+、配置部位或下單。",""]
    return "\n".join(lines)
