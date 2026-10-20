#!/usr/bin/env python3
"""6206 evidence reconciliation: objective coverage checks, never creates A+ certificates.

The research model's signed source-specific certification ledger remains authoritative.
This diagnostic identifies which already-collected materials can be cross-checked and
the evidence still needed for each of the 13 formal gates.
"""
import argparse
import datetime as dt
import json
import math
import statistics
from pathlib import Path

from tw_model_v880.evidence import GATES

ROOT = Path("tw-market-data")
CODE = "6206"
PLAN = {
    "original_eight_quarter_statements": ("AUTO_THEN_ORIGINAL_REVIEW", "逐季核對官方原始四表、修訂紀錄及完整附註"),
    "cash_and_working_capital": ("AUTO_RECONCILIATION", "以正式現金流量表對帳OCF、存貨、應收應付與實際PPE現金支出"),
    "nonoperating_components": ("AUTO_THEN_ORIGINAL_REVIEW", "由原始附註區分經常性及一次性業外"),
    "fully_diluted_shares": ("AUTO_THEN_LEGAL_REVIEW", "核對登記股數、員工認股、可轉債及潛在稀釋"),
    "matched_peers_and_cycle": ("COMPARABLE_ANALYSIS_REVIEW", "按產品結構比對同業Forward PE與景氣全週期"),
    "management_promises": ("ORIGINAL_GUIDANCE_REVIEW", "逐頁抽取法說承諾並與後續實績核對"),
    "auditor_scope": ("ORIGINAL_FINANCIAL_NOTE_REVIEW", "核對會計師意見、核閱範圍及重要性"),
    "tradability": ("AUTO_THEN_EXECUTION_REVIEW", "補驗價差、漲跌停及持倉退出成交可行性"),
    "forecast_bridge": ("AUTO_THEN_OPERATING_REVIEW", "用訂單、ASP、良率及軟硬體組合確認2027營益橋接"),
    "insider_claims": ("OFFICIAL_DISCLOSURE_REVIEW", "比對內部人申報、交易日、股數及持股變化"),
    "dividend_window": ("CORPORATE_ACTION_VERIFICATION", "核對除息、實際發放日期與每股股利"),
    "point_in_time": ("FILING_TIMESTAMP_REVIEW", "取得原始公告精確時點及當時可知資料版本"),
    "out_of_sample_validation": ("PIT_BACKTEST_REQUIRED", "用當時股票母體與歷史模型凍結版本做樣本外回測"),
}
assert set(PLAN) == set(GATES)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_report(probe, value, ir, history):
    require(probe.get("code") == CODE and probe.get("market") == "TWSE", "WRONG_ISSUER_PROBE")
    require(value.get("issuer") == CODE, "WRONG_ISSUER_VALUATION")
    common = value.get("original_common_model", {})
    require(common.get("model_version"), "MISSING_COMMON_MODEL")
    model_vintage = common.get("model_vintage")
    price_date = common.get("price_date")
    require(model_vintage and price_date, "MISSING_MODEL_VINTAGE")
    require(value.get("official_reference_price", {}).get("date") == price_date,
            "VALUATION_PRICE_DATE_CONFLICT")
    require(ir.get("code") == CODE, "WRONG_ISSUER_IR")
    require(history.get("issuer") == CODE and history.get("market") == "TWSE", "WRONG_ISSUER_HISTORY")

    covered = probe["financial"]
    capital = probe["capital"]
    h = probe.get("issuer_historical_market_data") or {}
    pending = probe.get("pending_gates", [])
    require(isinstance(pending, list) and len(pending) == len(set(pending))
            and set(pending) <= set(GATES), "INVALID_PENDING_GATES")

    reference = float(value["official_reference_price"]["close"])
    base = common["existing_base_2027"]
    upside = (float(base["target_price"]) / reference - 1) * 100
    require(math.isclose(upside, base["price_upside_pct"], abs_tol=0.02),
            "COMMON_MODEL_UPSIDE_INCONSISTENT")
    for name, case in value["scenarios"].items():
        require(math.isclose(case["parent_earnings_m"] / case["diluted_share_proxy_m"],
                             case["eps"], rel_tol=1e-7), "SCENARIO_EPS_MISMATCH_" + name)
        require(math.isclose(case["eps"] * case["pe"], case["target_price"], rel_tol=1e-7),
                "SCENARIO_PRICE_MISMATCH_" + name)

    # A SHA receipt and matching issuer site are useful cross-checks, but the
    # source PDF is not archived/signed here and its publication PIT is unproven.
    seen = {(x.get("source_url"), x.get("pdf_sha256")) for x in ir.get("presentations", [])
            if x.get("code") == CODE}
    source_matches = sum((x.get("source_url"), x.get("pdf_sha256")) in seen
                         for x in value.get("source_receipts", []))
    required_docs = len(value.get("source_receipts", []))
    original_pdf_match = required_docs > 0 and source_matches == required_docs

    # Recompute the 20-day median from dated snapshots to catch internal drift.
    sessions = [s for s in history.get("sessions", [])
                if isinstance(s.get("date"), str) and s["date"] <= price_date]
    sessions.sort(key=lambda s: s["date"], reverse=True)
    complete_20 = len(sessions) >= 20 and sessions[0]["date"] == price_date
    if complete_20:
        top = sessions[:20]
        amounts = [s.get("turnover_ntd") for s in top]
        complete_20 = (all(type(x) is int and x >= 0 for x in amounts)
                       and len({x["date"] for x in top}) == 20)
        if complete_20:
            reported = h.get("twenty_day")
            require(reported and reported.get("sessions") == 20
                    and reported.get("last") == top[0]["date"]
                    and reported.get("first") == top[-1]["date"]
                    and math.isclose(statistics.median(amounts), reported["median_turnover_ntd"]),
                    "TWENTY_DAY_SOURCE_RECONCILIATION_FAILED")

    coverage = {
        "original_eight_quarter_statements": covered.get("normalized_income_8q_count") == 8
            and covered.get("normalized_cashflow_8q_count") == 8,
        "cash_and_working_capital": covered.get("latest_primary_key_numbers_checked") is True,
        "nonoperating_components": False,
        "fully_diluted_shares": capital.get("issued_share_master_present") is True,
        "matched_peers_and_cycle": False,
        "management_promises": original_pdf_match,
        "auditor_scope": False,
        "tradability": complete_20,
        "forecast_bridge": original_pdf_match and bool(value.get("scenarios", {}).get("base")),
        "insider_claims": False,
        "dividend_window": bool(ir.get("presentations")),
        "point_in_time": False,
        "out_of_sample_validation": False,
    }
    gates = []
    for gate in GATES:
        route, action = PLAN[gate]
        observed = bool(coverage[gate])
        gates.append(dict(gate=gate, source_coverage="OBSERVED_PARTIAL" if observed else "MISSING_OR_UNVERIFIED",
                          formal_status="PENDING" if gate in pending else "NOT_PENDING_IN_MODEL_CHECK_CERTIFICATE",
                          next_action=action, automation_route=route,
                          reason="已有可交叉檢查的部分資料，但不構成完整認證" if observed
                                 else "尚無足夠的公司別原始證據可供簽核",
                          automatically_certified=False))

    return dict(schema="V891_6206_EVIDENCE_TRIAGE", issuer=CODE,
                valuation_model=common["model_version"], estimate_vintage=model_vintage,
                price_date=price_date, reference_close=reference,
                common_2027_base_price=base["target_price"], common_upside_pct=round(upside, 2),
                independent_2027_base_price=value["scenarios"]["base"]["target_price"],
                normalized_income_quarters=covered.get("normalized_income_8q_count"),
                normalized_cashflow_quarters=covered.get("normalized_cashflow_8q_count"),
                issuer_presentation_receipts_matched=source_matches,
                issuer_presentation_receipts_required=required_docs,
                original_company_publication_time_verified=False,
                individual_history_sessions=len(sessions), twenty_day_turnover_reconciled=complete_20,
                formal_Aplus=bool(common.get("Aplus", False)), newly_certified_gates=0,
                gates=gates, note="Evidence reconciliation only. No synthetic/original-source claims, no gate PASS, no trade orders.")


def render_md(data):
    lines = ["# 6206 飛捷｜13項A+認證障礙自動查核", "",
             "估值形成：" + data["estimate_vintage"] + "；官方參考股價日：" + data["price_date"] + "。", "",
             "共同模型2027 Base價 %.2f元、研究價差 %+.2f%%；獨立Base價 %.2f元。" %
             (data["common_2027_base_price"], data["common_upside_pct"],
              data["independent_2027_base_price"]), "",
             "已取得標準化財報：損益 %s/8季、現金流 %s/8季；官方法說SHA收據交叉匹配 %s/%s份；" %
             (data["normalized_income_quarters"], data["normalized_cashflow_quarters"],
              data["issuer_presentation_receipts_matched"], data["issuer_presentation_receipts_required"]),
             "個股歷史成交：%s日；最近20日金額驗算：%s（不等於可成交性通過）。" %
             (data["individual_history_sessions"], "一致" if data["twenty_day_turnover_reconciled"] else "待補"), "",
             "|品質門檻|目前可觀察資料|正式認證|下一步|", "|---|---|---|---|"]
    for g in data["gates"]:
        lines.append("|%s|%s|%s|%s|" %
                     (g["gate"], g["source_coverage"], g["formal_status"], g["next_action"]))
    lines += ["", "**注意：** 自動驗證了部分欄位一致性，不代表原始財報全文、PIT、稀釋或執行風險通過。",
              "沒有修改共同模型Base或正式A+名單；來源欠缺時維持PENDING。", ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="tw-market-data")
    a = p.parse_args()
    root = Path(a.root)
    def load(path):
        return json.loads((root / path).read_text(encoding="utf-8"))
    p884 = load("rankings/v884_evidence_progress.json")
    value = load("rankings/v888_6206_independent_valuation.json")
    ir = load("ir/6206/manifest.json")
    history = load("prices/issuer_history/TWSE/6206.json")
    probe = next((r for r in p884["top_priority_evidence"] if r["code"] == CODE), None)
    require(probe is not None, "6206_NOT_IN_EVIDENCE_FOCUS")
    common = value.get("original_common_model", {})
    require(common.get("model_vintage") == p884.get("estimate_vintage")
            and common.get("price_date") == p884.get("asof_price_date"),
            "STALE_6206_EVIDENCE_MIX")
    result = check_report(probe, value, ir, history)
    dst = root / "rankings"
    (dst / "v891_6206_gate_triage.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dst / "v891_6206_gate_triage.md").write_text(render_md(result), encoding="utf-8")
    print(json.dumps(dict(issuer=CODE, reference_date=result["price_date"],
                          matched_ir=result["issuer_presentation_receipts_matched"],
                          history_20_days_checked=result["twenty_day_turnover_reconciled"],
                          newly_certified_gates=0), ensure_ascii=False))


if __name__ == "__main__":
    main()
