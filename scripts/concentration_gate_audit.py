#!/usr/bin/env python3
"""Evidence-bound audit for a fixed concentration-research watchlist.

Numerical subchecks never issue 13-gate certificates. Observed cash balances,
unissued shares, price sensitivities and idealized exit capacity retain their
distinct meanings. No trading instructions, missing-as-zero or backdated facts.
"""
import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tw_model_v880.data import MarketData
from tw_model_v880.evidence import GATES, timestamp
from tw_model_v880.math import number, quarter_key, standalone
from tw_model_v880.model import reported_trading_value
from tw_model_v880.provenance import code_fingerprint
from scripts.v884_evidence_probe import price_archive, issuer_backfill_probe

FOCUS = (("TWSE", "2330", "台積電"), ("TWSE", "6206", "飛捷"),
         ("TWSE", "2317", "鴻海"), ("TWSE", "2027", "大成鋼"),
         ("TWSE", "4771", "望隼"), ("TWSE", "4912", "聯德控股-KY"),
         ("TWSE", "6625", "必應"), ("TWSE", "8110", "華東"),
         ("TPEX", "8390", "金益鼎"), ("TWSE", "1256", "鮮活果汁-KY"))

GATE_LABELS = dict(zip(GATES, (
    '八季原始四表與附註', '現金與營運資金', '業外獲利拆分', '完全稀釋股數',
    '同業與景氣估值', '經營承諾追蹤', '會計師核閱範圍', '可交易性',
    '2027獲利推演', '內部人身分與交易', '股利與除權息', '歷史當時可知資料', '樣本外驗證')))

FINDINGS = {
    '2330': 'Q3現金流原件已核對；2027獲利與估值仍未完成認證。',
    '6206': '找到提前備料說明；H1營業現金流仍負，須追蹤存貨轉銷售及回款。',
    '2317': '已核對公司現金週轉說明；H1營業現金流負，轉債條款仍須補全。',
    '2027': '現金流數值已核；部分子公司未經核閱的範圍及重要性仍待判定。',
    '4771': '公司已公告特定專利案撤回；2027獲利及估值仍待核。',
    '4912': '數值與成交能力已核；目前EPS與本益比仍缺完整公司推演及同業覆核。',
    '6625': '移出500萬元集中持有候選：退出容量偏慢，且Q3營收年減。',
    '8110': '暫停集中持有候選：H1業外約占稅前獲利92%，新Q3公告尚未納入舊Base。',
    '8390': '已補增資價62元及募資情境；尚未發行，另有核閱範圍待判定。',
    '1256': '移出500萬元集中持有候選：退出容量偏慢，轉債條款仍不完整。',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def amount(value):
    return None if isinstance(value, bool) else number(value)


def quarter_cash(rows, period):
    year, quarter = quarter_key(period)
    current = amount(rows.get(period, {}).get("operating_cashflow_ytd_k"))
    prior = amount(rows.get(f"{year}-Q{quarter-1}", {}).get("operating_cashflow_ytd_k"))
    return standalone(current, prior, quarter)


def sensitivity(base, close, eps_factor=1., pe_factor=1., extra_shares=0.):
    eps, pe, shares = (amount(base.get(k)) for k in ("eps", "pe", "shares"))
    require(all(x is not None and x > 0 for x in (eps, pe, shares, close)),
            "VALUATION_SENSITIVITY_INPUT_MISSING")
    require(extra_shares >= 0 and 0 < eps_factor <= 1 and 0 < pe_factor <= 1,
            "VALUATION_SENSITIVITY_ASSUMPTION_INVALID")
    value = eps * eps_factor * pe * pe_factor * shares / (shares + extra_shares)
    return dict(price=value, price_upside_pct=100 * (value / close - 1),
                is_fair_value=False, is_downside_bound=False)


def issuance_sensitivity(base, close, issued, new_shares, subscription_price):
    require(type(new_shares) is int and new_shares > 0 and issued > 0,
            "OFFERING_SHARE_INPUT_INVALID")
    require(subscription_price is not None and subscription_price > 0,
            "OFFERING_PRICE_INPUT_MISSING")
    return dict(new_shares=new_shares, existing_shares=issued,
                gross_proceeds_ntd=new_shares * subscription_price,
                post_issue_common_shares_if_completed=issued + new_shares,
                fixed_profit_eps=base["parent_profit_k"] * 1000 / (base["shares"] + new_shares),
                fixed_profit_pe_price=sensitivity(base, close, extra_shares=new_shares)["price"],
                theoretical_ex_rights_price=(close * issued + subscription_price * new_shares) / (issued + new_shares),
                subscription_price=subscription_price, is_already_issued=False,
                actual_ex_rights_price_verified=False, cash_returns_fees_and_timing_unmodelled=True,
                is_fair_value=False)


def admitted_observations(document, code, asof):
    records = []
    for item in (document or {}).get("observations", []):
        if item.get("code") != code:
            continue
        require(item.get("source_url", "").startswith("https://"), "OBSERVATION_SOURCE_URL_MISSING")
        require(item.get("source_tier") in ("ISSUER_ORIGINAL_WEB_REVIEW", "ISSUER_ANNOUNCEMENT_REPUBLICATION"),
                "OBSERVATION_SOURCE_TIER_INVALID")
        seen = timestamp(item["first_observed_at"])
        publication = dt.date.fromisoformat(item["published_on"])
        require(publication <= seen.date(), "OBSERVATION_PUBLICATION_AFTER_CAPTURE")
        if seen <= timestamp(asof):
            records.append(item)
    return records


def next_quarter_revenue(data, key):
    year, quarter=quarter_key(data.period)
    month_year, month=map(int,data.revenue_month.split('-'))
    if quarter>=4 or month_year!=year or month!=(quarter+1)*3:
        return None
    code=key[1];monthly=data.revenue.get(code,{})
    current=amount(monthly.get('ytd_revenue_k'))
    prior=amount(monthly.get('last_year_ytd_revenue_k'))
    a=amount(data.history[key].get(data.period,{}).get('revenue_ytd_k'))
    b=amount(data.history[key].get(f'{year-1}-Q{quarter}',{}).get('revenue_ytd_k'))
    if None in (current,prior,a,b) or prior-b<=0 or current-a<0:
        return None
    return dict(current_quarter_revenue_k=current-a,prior_quarter_revenue_k=prior-b,
                yoy_pct=100*((current-a)/(prior-b)-1),
                revenue_growth_is_not_profit_growth=True)


def build(data, research, observations=None, position_ntd=5_000_000,
          participation=.05, max_exit_sessions=5):
    require(position_ntd > 0 and 0 < participation <= 1 and max_exit_sessions > 0,
            "EXIT_SCREEN_ASSUMPTIONS_INVALID")
    require(research["asof_price_date"] == data.price_date and research["financial_last_quarter"] == data.period,
            "RESEARCH_AND_DATA_VINTAGE_MISMATCH")
    require(research['model_code_sha256']==code_fingerprint(), 'RESEARCH_RUNTIME_CODE_MISMATCH')
    asof = research["estimate_vintage"]
    require(data.price_date <= asof[:10], "FUTURE_REFERENCE_PRICE")
    lookup = {}
    for row in research["all_model_rows"]:
        key = (row["market"], row["code"])
        require(key not in lookup, "DUPLICATE_MODEL_ISSUER")
        lookup[key] = row
    dated, receipts = price_archive(data.root, data.price_date,
                                   json.loads((data.root / "prices/latest_manifest.json").read_text()))
    result = []
    for rank, (market, code, name) in enumerate(FOCUS, 1):
        key = (market, code)
        require(key in lookup and key in data.prices, "FOCUS_ISSUER_MISSING_" + code)
        row, quote = lookup[key], data.prices[key]
        require(row.get("name") == name, "FOCUS_COMPANY_NAME_MISMATCH_" + code)
        require(row.get("price_date") == data.price_date and row.get("reference_close") == quote.get("close"),
                "FOCUS_PRICE_MISMATCH_" + code)
        require(row.get("single_day_turnover_ntd") == reported_trading_value(quote),
                "MODEL_NOT_USING_REPORTED_TRADING_VALUE_" + code)
        income, cash = data.history.get(key, {}), data.cash.get(key, {})
        inc_periods = [q for q in data.required_periods if q in income]
        for kind,series in (('income',income),('cashflow',cash)):
            for period in data.required_periods:
                source=series.get(period,{})
                require(source.get('code')==code and source.get('market')==market
                        and source.get('period')==period
                        and source.get('unit')=='NTD_thousands_except_EPS'
                        and source.get('year_to_date_values') is True,
                        'NORMALIZED_IDENTITY_PERIOD_UNIT_MISMATCH_'+kind+'_'+code+'_'+period)
        cf_periods = [q for q in data.required_periods if q in cash and quarter_cash(cash, q) is not None]
        y, q = quarter_key(data.period)
        current = amount(cash.get(data.period, {}).get("operating_cashflow_ytd_k"))
        last_quarter = quarter_cash(cash, data.period)
        ttm_periods = data.required_periods[-4:]
        ttm_values = [quarter_cash(cash, p) for p in ttm_periods]
        ttm = sum(ttm_values) if all(v is not None for v in ttm_values) else None
        history = issuer_backfill_probe(data.root, data.price_date, market, code, dated)
        sample = (history or {}).get("twenty_day")
        median = sample.get("median_turnover_ntd") if sample else None
        capacity = position_ntd / (median * participation) if median and median > 0 else None
        observed = admitted_observations(observations, code, asof)
        subsequent_revenue=next_quarter_revenue(data,key)
        blocks = []
        if current is None:
            blocks.append("OPERATING_CASH_FLOW_UNKNOWN")
        elif current < 0:
            blocks.append("NEGATIVE_YTD_OCF_WORKING_CAPITAL_FUNDING_REVIEW")
        if sample is None:
            blocks.append("TWENTY_SESSION_LIQUIDITY_NOT_RECONCILED")
        elif capacity is None or capacity > max_exit_sessions:
            blocks.append("IDEALIZED_EXIT_CAPACITY_SCREEN_EXCEEDED")
        share = row["share_bridge"]
        if share.get("unresolved_terms") or share.get("missing_legal_conversion_inputs"):
            blocks.append("CURRENT_CONVERTIBLE_BOND_TERMS_INCOMPLETE")
        nonop = row.get("nonoperating_bridge", {})
        dependency = nonop.get("reported_ytd_abs_gap_share_pretax_pct")
        if (dependency is not None and dependency >= 50 and
                nonop.get("method") == "REPORTED_GAP_COMPOSITION_UNRESOLVED"):
            blocks.append("MATERIAL_UNRESOLVED_NONOPERATING_DEPENDENCE")
        primary = data.primary(code)
        if primary and primary.get("qualified_review"):
            blocks.append("QUALIFIED_REVIEW_SCOPE_MATERIALITY_PENDING")
        if row.get("equity_offering_overlay"):
            blocks.append("ANNOUNCED_UNISSUED_EQUITY_NOT_RECONCILED")
        if subsequent_revenue is not None and subsequent_revenue['yoy_pct']<=0:
            blocks.append('POST_FINANCIAL_QUARTER_REVENUE_NOT_GROWING')
        for item in observed:
            if item.get("blocks_concentration"):
                blocks.append(item["kind"])
        # A numerical screen never upgrades the model's original 13 decisions.
        gates = []
        for gate in GATES:
            source = row.get("gates", {}).get(gate, {})
            gates.append(dict(gate=gate, formal_status=source.get("status", "PENDING"),
                              formal_reason=source.get("reason", "MISSING_FROM_SOURCE"),
                              newly_certified_by_this_audit=False))
        base = row["base"]
        require(abs(base["eps"] * base["pe"] - base["target_price"]) < .001,
                "MODEL_EPS_PE_IDENTITY_MISMATCH_" + code)
        item = dict(rank=rank, code=code, name=name, market=market,
                    financial_period=row["financial_period"], normalized_cashflow_period=data.period,
                    price_date=data.price_date, close=quote["close"],
                    actual_turnover_ntd=quote["turnover_ntd"],
                    former_close_volume_proxy_ntd=quote["close"] * quote["volume_shares"],
                    normalized_income_quarters=len(inc_periods),
                    standalone_ocf_quarters=len(cf_periods), original_full_notes_certified=False,
                    normalized_ytd_ocf_k=current, latest_standalone_ocf_k=last_quarter,
                    normalized_ttm_ocf_k=ttm, ttm_ocf_periods=ttm_periods,
                    next_quarter_revenue=subsequent_revenue,
                    model_cashflow_period=row.get("cashflow_financial_period"),
                    model_current_ocf_k=row["liquidity"].get("ocf_k"),
                    cash_conversion_risk_resolved=False,
                    source_tier=row["source_tier"], primary_current_numbers_checked=row.get("original_current_issuer_numeric_checked", False),
                    base=base, nonoperating_bridge=nonop, share_bridge=share,
                    stress_eps_pe_both_down20=sensitivity(base, quote["close"], .8, .8),
                    stress_eps_pe_both_down10=sensitivity(base, quote["close"], .9, .9),
                    pe_needed_for_30pct_at_model_eps=quote["close"] * 1.3 / base["eps"],
                    future_eps_and_peer_pe_certified=False,
                    trading_history=history, median20_turnover_ntd=median,
                    idealized_exit_sessions=capacity, idealized_10m_exit_sessions=capacity * 2 if capacity is not None else None,
                    spread_limit_queue_and_actual_fills_verified=False,
                    observations=observed, concentration_blockers=sorted(set(blocks)),
                    gates=gates, formal_Aplus=row.get("formal_Aplus", False),
                    formal_Aplusplus=row.get("formal_Aplusplus", False),
                    concentration_ready=bool(row.get('formal_Aplus') and not blocks
                        and all(g['formal_status']=='PASS' for g in gates)),
                    decision="BLOCKED_BY_SUBSTANTIVE_REVIEW" if blocks else "EVIDENCE_PENDING_NOT_CERTIFIED")
        offer = next((o for o in observed if o["kind"] == "OFFERING_PRICE_PUBLISHED"), None)
        if offer:
            item["issuance_sensitivity"] = issuance_sensitivity(base, quote["close"],
                share["issued_common_shares"], offer["facts"]["new_shares"], offer["facts"]["subscription_price_twd"])
        result.append(item)
    return dict(schema="CONCENTRATION_GATE_AUDIT_V1", model=research["model"],
                source_model_code_sha256=research["model_code_sha256"],
                estimate_vintage=asof, price_date=data.price_date,
                source_commit=(observations or {}).get("source_commit"),
                target_date=research["target_date"], financial_period=data.period,
                rows=result, focus_count=len(result), formal_gate_count=len(GATES) * len(result),
                numerical_income_coverage_8q_count=sum(r["normalized_income_quarters"] == 8 for r in result),
                numerical_standalone_ocf_coverage_8q_count=sum(r["standalone_ocf_quarters"] == 8 for r in result),
                median20_reconciled_count=sum(r["median20_turnover_ntd"] is not None for r in result),
                newly_certified_gates=0, newly_certified_Aplus=0,
                concentration_ready_count=sum(r['concentration_ready'] for r in result),
                blocker_counts=dict(collections.Counter(b for r in result for b in r["concentration_blockers"])),
                assumptions=dict(position_ntd=position_ntd, participation=participation,
                                 max_exit_sessions=max_exit_sessions, assumptions_backtested=False),
                original_thresholds_unchanged=True,
                audit_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                publication_capture_times_not_backdated=True,
                market_daily_archive_receipts=receipts)


def render(report):
    lines = ["# 重押前 TOP10 關卡實查", "", "資料截止：" + report["price_date"] + "；目標：" + report["target_date"] + "。",
             "估算時間：" + report['estimate_vintage'] + '。這10檔是指定觀察組，順序不是通過重押認證的名次。',
             "", f"本輪已核對10檔的八季損益數值、八季單季營業現金流及20個交易日成交金額。正式A+仍為0檔；13關共130個決定仍待覆核，本輪新增認證{report['newly_certified_gates']}項。",
             "", "## 已完成的修正與資料核對", "",
             "- 成交能力改用官方實際成交金額；取消收盤價乘成交股數的替代值，缺值不當成零。",
             "- 上櫃個股歷史資料會與較新的全市場逐日原件核對，修正金益鼎20日視窗缺漏。",
             "- 增資股數與後續定價各有獨立公告、發現時間；62元不回填舊回測，預計募資不當成已收款。",
             "- 望隼特定專利案件已撤回，修正仍未結案的舊說法；仍不等於所有法律風險解除。",
             "", "## 十檔處理結果", "",
             "|股票|11/4收盤|H1營業現金流(億)|20日成交額中位數(萬)|500萬元理想退出交易日|本次實查結果|",
             "|---|---:|---:|---:|---:|---|"]
    for r in report["rows"]:
        ocf = f'{r["normalized_ytd_ocf_k"]/100000:.2f}' if r["normalized_ytd_ocf_k"] is not None else "待查"
        med = f'{r["median20_turnover_ntd"]/10000:.1f}' if r["median20_turnover_ntd"] is not None else "待查"
        d = r['idealized_exit_sessions']
        days = ('<1' if d < 1 else f'{d:.2f}') if d is not None else "待查"
        lines.append(f'|{r["code"]} {r["name"]}|{r["close"]:.2f}|{ocf}|{med}|{days}|{FINDINGS[r["code"]]}|')
    lines += ["", "退出日數＝部位／(20日成交金額中位數×參與率5%)，只是容量情境；未驗證價差、跌停排隊或實際成交。",
              "所有20日視窗為2026-10-05至2026-11-04。未滿一日僅表示計算容量，不保證單日可成交。1000萬元部位所需日數為表列兩倍。參與率5%、最長5日只是本輪明示情境，尚未回測。",
              "八季數值覆蓋不等於八季四表附註審查；單季現金流為累計差額；未知PPE不當成零。表列現金流統一為2026H1；台積電另有Q3公司原始簡明報表，並不替代八季完整附註。",
              "", "## 各公司新增觀察與剩餘關卡", ""]
    for r in report["rows"]:
        lines += [f'### {r["code"]} {r["name"]}', ""]
        for o in r["observations"]:
            lines.append(f'- {o["summary"]} [來源]({o["source_url"]})')
        growth=r.get('next_quarter_revenue')
        if growth is not None:
            lines.append(f"- 由9月累計減H1推得Q3營收年增率{growth['yoy_pct']:+.2f}%；營收成長不等於EPS成長。")
        if r.get('issuance_sensitivity'):
            s=r['issuance_sensitivity']
            lines.append(f"- 預計800萬新股、每股62元，募資總額4.96億元；尚未發行。固定獲利下EPS僅為稀釋情境{s['fixed_profit_eps']:.2f}元，機械式除權參考約{s['theoretical_ex_rights_price']:.2f}元；均不是新合理價，亦未估募資效益及費用。")
        lines.append('- 正式待查：' + '、'.join(GATE_LABELS[g["gate"]] for g in r["gates"] if g["formal_status"] == "PENDING"))
        lines.append("")
    lines += ['## 13關尚缺什麼', '', '|關卡|本輪可確認|正式放行前仍缺|', '|---|---|---|']
    todo = (
        ('八季原始四表與附註', '10檔八季損益及現金流數值可用', '各季原始四表、附註及來源身分覆核；數值完整不代表附註完整'),
        ('現金與營運資金', '已拆單季與累計，查明飛捷及鴻海負現金流', '應收帳齡、存貨可回收性、期後回款及資金壓力'),
        ('業外獲利拆分', '華東金融資產評價利益及重大業外依賴已識別', '經常與非經常獲利重估，不能沿用舊Base直接重押'),
        ('完全稀釋股數', '金益鼎計畫增資及62元定價已分時點處理', '鴻海、鮮活轉債完整現行條款與金益鼎實際發行情況'),
        ('同業與景氣估值', '保留原模型估值，沒有擅自升級', '相同業務、年度及景氣位置的獲利與倍數核對'),
        ('經營承諾追蹤', '補到公司備料與現金週轉說明', '過往法說量化承諾與實際達成逐期對照'),
        ('會計師核閱範圍', '識別大成鋼及金益鼎未經核閱部分', '逐項重要性與後續補核閱證據；不將範圍限制自動當成造假'),
        ('可交易性', '10檔20日成交額已核；必應與鮮活容量偏慢', '買賣價差、深度、漲跌停排隊及可重複成交驗證'),
        ('2027獲利推演', '原EPS×PE算式核對；補Q3營收方向', '公司訂單、產能、毛利、費用及匯率推演；華東須重建'),
        ('內部人身分與交易', '未把買進觀察樣本升級成認證', '持有人法定身分、交易類型及公司月份完整性'),
        ('股利與除權息', '現金募資與除權情境沒有當成股利', '未公告股利不可當已確定報酬，須對齊持有與除息日期'),
        ('歷史當時可知資料', '新增觀察與定價保留獨立發現時間', '所有歷史選股輸入的當時版本及原始存證'),
        ('樣本外驗證', '未把營收預測誤差冒充投資績效', '凍結參數的逐期選股、費用、成交限制及相對0050總報酬'),
    )
    lines += ['|'+'|'.join(t)+'|' for t in todo]
    lines += ['', '## 完成路徑與稽核限制', '',
        '本輪先排除華東、必應與鮮活的集中持有情境；優先補台積電、望隼、聯德控股的公司獲利推演與同業估值，飛捷及鴻海先追蹤回款與存貨。大成鋼及金益鼎仍須判定核閱範圍，金益鼎另須待實際發行。這是研究處理順序，不是買進指令。',
        '正式認證保留原門檻與原始來源存證要求；AI網頁查核沒有冒充具名人工來源覆核。已核對的資料缺口可以關閉，仍存在的經營或交易風險以暫停或排除處理。',
        '本輪是10檔指定觀察組實查，並非新一輪全市場推薦。全市場重跑有2004筆模型列、832檔研究可排序、0檔個股計算失敗；另有與本組無關的8383兩筆原始來源錯誤，未掩蓋為零。',
        '', '來源基準：`'+str(report['source_commit'])+'`；模型：`'+report['model']+'`。',
        '模型碼SHA-256：`'+report['source_model_code_sha256']+'`。',
        '機器可讀報告保留來源檔案、觀察帳本及腳本雜湊；新增網頁觀察若無本機原始位元組，已明確標示，不能當正式原件存證。', '']
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="tw-market-data")
    ap.add_argument("--research", required=True)
    ap.add_argument("--observations", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    packed = Path(args.research).read_bytes()
    result = json.loads(gzip.decompress(packed) if args.research.endswith(".gz") else packed)
    data = MarketData(args.data_dir, result["estimate_vintage"])
    observations = json.loads(Path(args.observations).read_text())
    report = build(data, result, observations)
    report["source_result_sha256"] = hashlib.sha256(packed).hexdigest()
    report["observation_ledger_sha256"] = hashlib.sha256(Path(args.observations).read_bytes()).hexdigest()
    destination = Path(args.out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "concentration_gate_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (destination / "concentration_gate_audit.md").write_text(render(report))
    print(json.dumps({k: report[k] for k in ("focus_count", "formal_gate_count", "numerical_income_coverage_8q_count",
        "numerical_standalone_ocf_coverage_8q_count", "median20_reconciled_count", "newly_certified_gates", "blocker_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
