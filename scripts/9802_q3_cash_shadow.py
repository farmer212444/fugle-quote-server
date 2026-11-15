#!/usr/bin/env python3
"""Q3 2026 9802 PDF-number cash shadow; no SHA/original-PIT/A+ admission."""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_research_pipeline import atomic_json
RECEIPT_PATH = ROOT / "tw-market-data/evidence/v880/working_capital_watch/9802_2026Q3_partial_pdf_numbers.json"
OLDER_REPORT_PATH = ROOT / "tw-market-data/rankings/latest_9802_cash_review.json"
OUT_JSON = ROOT / "tw-market-data/rankings/latest_9802_q3_cash_shadow.json"
OUT_MD = ROOT / "tw-market-data/rankings/latest_9802_q3_cash_shadow.md"
SCHEMA = "9802_2026Q3_PARTIAL_PDF_NUMERIC_RECEIPT_V1"
ROWS = ("2026", "2025")


def require(ok, code):
    if not ok:
        raise ValueError(code)


def _pair(mapping, key):
    values = mapping.get(key)
    require(isinstance(values, list) and len(values) == 2, "9802_Q3_PAIR_" + key)
    require(all(type(x) in (int, float) and math.isfinite(x) and float(x).is_integer() for x in values), "9802_Q3_NONINTEGER_" + key)
    return values


def build(receipt, older_report=None):
    require(receipt.get("schema") == SCHEMA and receipt.get("issuer") == "9802"
            and receipt.get("market") == "TWSE" and receipt.get("period") == "2026-Q3",
            "9802_Q3_IDENTITY_OR_PERIOD_MISMATCH")
    require(receipt.get("company_report_approved_date") == "2026-11-05"
            and receipt.get("source_report_printed_pages_checked") == [6, 10, 11, 17, 44],
            "9802_Q3_SOURCE_SCOPE_MISMATCH")
    require(receipt.get("source_url", "").startswith("https://cdn.financialreports.eu/financialreports/media/filings/52772/2026/")
            and receipt.get("pdf_raw_bytes_archived") is False
            and receipt.get("pdf_sha256_verified") is False
            and receipt.get("official_mops_issuer_exact_pit_verified") is False,
            "9802_Q3_SOURCE_HASH_OR_PIT_MISREPRESENTED")
    f = receipt.get("flags", {})
    require(f.get("research_only") is True and f.get("formal_cash_gate_pass") is False
            and f.get("formal_Aplus") is False and f.get("overwrite_base_eps_or_price") is False,
            "9802_Q3_QUALITY_GATE_MISREPRESENTED")
    cf, totals, balances = (receipt["cf_line_items_signed_k"],
                            receipt["totals_signed_k"], receipt["balances_k"])
    for i in range(2):
        generation = sum(_pair(cf, field)[i] for field in cf)
        require(generation == _pair(totals, "cash_generated")[i],
                "9802_Q3_OPERATING_BRIDGE_MISMATCH")
        cash = generation + _pair(totals, "interest_received")[i] + \
            _pair(totals, "interest_paid")[i] + _pair(totals, "income_taxes_paid")[i]
        require(cash == _pair(totals, "operating_cash_flow")[i],
                "9802_Q3_OCF_MISMATCH")
        change = sum(_pair(totals, field)[i] for field in
                     ("operating_cash_flow", "net_investing_cash_flow",
                      "net_financing_cash_flow", "exchange_effect"))
        require(change == _pair(totals, "net_cash_change")[i],
                "9802_Q3_CASH_CHANGE_MISMATCH")
        close = _pair(totals, "opening_cash")[i] + change
        require(close == _pair(totals, "closing_cash")[i] == _pair(balances, "cash")[i],
                "9802_Q3_CLOSING_CASH_MISMATCH")
        require(_pair(balances, "inventory_gross")[i] - _pair(balances, "inventory_allowance")[i]
                == _pair(balances, "inventory_net")[i], "9802_Q3_INVENTORY_RECONCILE_MISMATCH")
    current, previous = (_pair(totals, "operating_cash_flow")[j] for j in range(2))
    h1_current, h1_prior = _pair(receipt["h1_comparison_signed_k"], "operating_cash_flow")
    h1_reconciled = False
    if older_report is not None:
        older = older_report.get("original_cash_review") or {}
        require(older.get("period") == "2026-Q2"
                and older.get("current_h1", {}).get("year") == 2026
                and older.get("prior_h1", {}).get("year") == 2025,
                "9802_Q3_H1_PERIOD_MISMATCH")
        old_vals = _pair(older["cashflow_signed_k"], "ocf")
        require(old_vals == [h1_current, h1_prior], "9802_Q3_H1_OCF_RECEIPT_MISMATCH")
        h1_reconciled = True
    fcf = _pair(totals, "ppe_purchase")
    net_inventory = _pair(balances, "inventory_net")
    provision = _pair(balances, "inventory_allowance")
    report = {
        "schema": "9802_Q3_2026_CASH_SHADOW_V1", "issuer": "9802",
        "financial_period": "2026-Q3", "source_approved_date": "2026-11-05",
        "source_url": receipt["source_url"], "source_report_printed_pages_checked": [6,10,11,17,44],
        "status": "PARTIAL_PDF_NUMERICS_RECONCILED_NOT_SOURCE_HASH_OR_PIT_CERTIFIED",
        "original_pdf_sha256_verified": False, "original_pdf_binary_archived": False,
        "issuer_publication_pit_verified": False, "source_quality_gate_pass": False,
        "formal_Aplus": False, "changes_eps_or_target_price": False,
        "ocf_ytd_2026_k": current, "ocf_ytd_2025_k": previous,
        "ocf_yoy_pct": 100 * (current / previous - 1),
        "ocf_q3_2026_k": current - h1_current if h1_reconciled else None,
        "ocf_q3_2025_k": previous - h1_prior if h1_reconciled else None,
        "h1_cash_review_reconciled": h1_reconciled,
        "ppe_purchase_ytd_2026_signed_k": fcf[0], "ppe_purchase_ytd_2025_signed_k": fcf[1],
        "simple_fcf_2026_k": current + fcf[0],
        "simple_fcf_2025_k": previous + fcf[1],
        "cash_2026_09_30_k": _pair(balances, "cash")[0],
        "inventory_2026_09_30_k": net_inventory[0],
        "inventory_2025_09_30_k": net_inventory[1],
        "inventory_yoy_pct": 100 * (net_inventory[0] / net_inventory[1] - 1),
        "inventory_allowance_2026_09_30_k": provision[0],
        "inventory_allowance_2025_09_30_k": provision[1],
        "inventory_allowance_yoy_pct": 100 * (provision[0] / provision[1] - 1),
        "undrawn_bank_facility_2026_09_30_k": balances["undrawn_bank_facilities_2026_09_30"],
        "undrawn_facility_is_cash": False,
        "cb_face_2026_09_30_k": balances["cb_face_maturity_band_2026_09_30"],
        "actual_cb_put_requests_or_settlement_verified": False,
        "financing_liquidity_and_inventory_saleability_pending": True,
        "note": "2026Q3 PDF page values hand-transcribed and checked arithmetically; source PDF binary SHA, full notes, MOPS issuer publication PIT, CB put exercise and formal 13 gates remain unverified.",
    }
    return report


def markdown(report):
    e8 = lambda v: f"{v / 100000:+.3f}"
    rows = [
        "# 鈺齊 2026Q3 現金流與存貨：原始報表數值核對（研究）",
        "", f"原始報表日期：{report['source_approved_date']}；核對狀態：{report['status']}。",
        "", "**這是 Q3 PDF 數值的獨立補充，不覆寫既有 Q2 現金流原件核對，不改 EPS、合理價或 A+。**",
        "", "| 項目（億元） | 2026 前三季 | 2025 前三季 |",
        "|---|---:|---:|",
        f"| 營業現金流 | {e8(report['ocf_ytd_2026_k'])} | {e8(report['ocf_ytd_2025_k'])} |",
        f"| 購置廠房設備 | {e8(report['ppe_purchase_ytd_2026_signed_k'])} | {e8(report['ppe_purchase_ytd_2025_signed_k'])} |",
        f"| 簡化自由現金流 | {e8(report['simple_fcf_2026_k'])} | {e8(report['simple_fcf_2025_k'])} |",
        f"| 存貨帳面淨額 | {e8(report['inventory_2026_09_30_k'])} | {e8(report['inventory_2025_09_30_k'])} |",
        f"| 存貨跌價及呆滯備抵 | {e8(report['inventory_allowance_2026_09_30_k'])} | {e8(report['inventory_allowance_2025_09_30_k'])} |",
        "",
        f"存貨年增 {report['inventory_yoy_pct']:+.1f}%；備抵年增 {report['inventory_allowance_yoy_pct']:+.1f}%。",
        f"9月底現金 {e8(report['cash_2026_09_30_k'])} 億；未動用銀行額度 {e8(report['undrawn_bank_facility_2026_09_30_k'])} 億，**不等同現金**。",
        "",
        f"Q3 單季 OCF：{e8(report['ocf_q3_2026_k']) if report['h1_cash_review_reconciled'] else '待H1原件對帳'} 億（與 Q2 累計原件銜接狀態：{report['h1_cash_review_reconciled']}）。",
        "CB 9月底未折現到期分析面額不等於已行使賣回數量；實際申請及償付尚未驗證。",
        "",
        "原始 PDF 逐頁數值可讀，但目前沒有 PDF 位元組原件 SHA256、完整 8 季及個別 MOPS 申報 PIT 認證；不得授予正式品質 PASS。",
        f"PDF：{report['source_url']}",
        "",
    ]
    return "\n".join(rows)


def main():
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    older = json.loads(OLDER_REPORT_PATH.read_text(encoding="utf-8")) if OLDER_REPORT_PATH.exists() else None
    report = build(receipt, older)
    atomic_json(OUT_JSON, report)
    OUT_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "h1_crosscheck": report["h1_cash_review_reconciled"],
                      "formal_Aplus_created": 0, "valuation_changed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
