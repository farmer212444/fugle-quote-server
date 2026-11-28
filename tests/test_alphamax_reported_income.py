"""Synthetic-only preserved-summary intake tests; no live EPS forecasts."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from alphamax.core import ContractError
from alphamax.reported_income import FIELDS, UNITS, reconcile_income, reported_income_snapshot


def row_fixture():
    amounts = {
        "revenue_twd": 1000, "cost_of_revenue_twd": 600,
        "gross_profit_twd": 400, "net_gross_profit_twd": 400,
        "operating_expenses_twd": 100, "operating_profit_twd": 320,
        "net_nonoperating_income_twd": 10, "pretax_profit_twd": 330,
        "tax_expense_twd": 66, "net_profit_twd": 264,
        "parent_profit_twd": 260, "noncontrolling_profit_twd": 4,
    }
    row = {FIELDS[k]: str(v) for k, v in amounts.items()}
    row.update({"公司代號": "0001", "公司名稱": "SYNTHETIC", "年度": "115", "季別": "3",
                "出表日期": "1151116", "其他收益及費損淨額": "20", "停業單位損益": "", "基本每股盈餘（元）": "2.60"})
    return row


class ReportedIncomeTests(unittest.TestCase):
    def test_other_operating_line_parent_profit_and_units_reconcile(self):
        result = reconcile_income(row_fixture(), units=UNITS)
        self.assertEqual(result["status"], "RECONCILED_REPORTED_FACTS_ONLY")
        self.assertEqual(result["reported_amounts_twd"]["parent_profit_twd"], 260_000)
        self.assertEqual(result["operating_inputs_for_same_reported_period_only"]["other_operating_income_twd"], 20_000)
        self.assertEqual(result["reported_basic_eps_twd"], 2.6)

    def test_basic_eps_never_infers_diluted_shares(self):
        result = reconcile_income(row_fixture(), units=UNITS)
        self.assertIsNone(result["calculated_diluted_eps_twd"])
        self.assertIsNone(result["operating_inputs_for_same_reported_period_only"]["diluted_shares"])
        self.assertFalse(result["bridge_ready_for_forecast"])

    def test_quarter_three_ytd_is_nine_months_not_a_quarter_or_annual_forecast(self):
        result = reconcile_income(row_fixture(), units=UNITS)
        self.assertEqual(result["covered_months"], 9)
        self.assertEqual(result["period_basis"], "year_to_date")
        self.assertFalse(result["buy_signal"])

    def test_missing_required_profit_is_not_treated_as_zero(self):
        row = row_fixture()
        row["營業外收入及支出"] = ""
        with self.assertRaises(ContractError):
            reconcile_income(row, units=UNITS)

    def test_optional_operating_residual_is_labeled_as_derived(self):
        row = row_fixture()
        row["其他收益及費損淨額"] = ""
        result = reconcile_income(row, units=UNITS)
        self.assertEqual(result["other_operating_income_basis"], "ALGEBRAIC_RESIDUAL_NOT_SEPARATELY_REPORTED")
        self.assertFalse(result["independent_operating_line_check"])

    def test_inconsistent_report_is_retained_for_review_not_silently_fixed(self):
        row = row_fixture()
        row["淨利（淨損）歸屬於母公司業主"] = "300"
        result = reconcile_income(row, units=UNITS)
        self.assertEqual(result["status"], "REVIEW_STATEMENT_RESIDUALS")
        self.assertFalse(result["checks"]["parent_plus_noncontrolling_to_net"])

    def test_unsupported_units_rejected(self):
        wrong = dict(UNITS, money="TWD")
        with self.assertRaises(ContractError):
            reconcile_income(row_fixture(), units=wrong)

    def snapshot(self, folder, rows=None):
        folder = Path(folder)
        source_path = "tw-market-data/financial/2026Q3/TWSE_income.json"
        path = folder / source_path
        path.parent.mkdir(parents=True)
        raw = json.dumps([row_fixture()] if rows is None else rows, ensure_ascii=False).encode()
        path.write_bytes(raw)
        manifest = {"captured_utc": "2026-11-17T01:00:00Z", "sources": [{"kind": "TWSE_income", "period": "2026Q3", "path": source_path, "normalized_sha256": sha256(raw).hexdigest(), "issuer_rows": len(json.loads(raw)), "url": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"}]}
        mp = folder / "tw-market-data/financial/latest_manifest.json"
        mp.write_text(json.dumps(manifest))
        return manifest, mp, path

    def run_snapshot(self, folder, codes=None, asof="2026-11-17T02:00:00Z"):
        return reported_income_snapshot(folder, codes=["0001"] if codes is None else codes,
                                        source_commit="a" * 40, units=UNITS, asof=asof)

    def test_valid_bytes_produce_research_facts_without_issuer_timestamp_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            self.snapshot(folder)
            result = self.run_snapshot(folder)
        self.assertEqual(result["reconciled_count"], 1)
        self.assertFalse(result["issuer_publication_timestamps_verified"])
        self.assertFalse(result["investment_certified"])
        self.assertIsNone(result["expected_net_return_12m"])

    def test_tampered_normalized_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            _, _, path = self.snapshot(folder)
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ContractError, "HASH_MISMATCH"):
                self.run_snapshot(folder)

    def test_missing_issuer_does_not_erase_valid_issuer(self):
        with tempfile.TemporaryDirectory() as folder:
            self.snapshot(folder)
            result = self.run_snapshot(folder, ["0001", "0002"])
        self.assertEqual(result["reconciled_count"], 1)
        self.assertEqual(result["issuers"][1]["status"], "ISSUER_NOT_IN_SNAPSHOT")

    def test_duplicate_issuer_rows_are_not_arbitrarily_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            self.snapshot(folder, [row_fixture(), row_fixture()])
            result = self.run_snapshot(folder)
        self.assertEqual(result["issuers"][0]["status"], "DUPLICATE_ISSUER_ROWS")

    def test_future_capture_cannot_enter_an_earlier_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            self.snapshot(folder)
            with self.assertRaisesRegex(ContractError, "NOT_CAPTURED_AT_ASOF"):
                self.run_snapshot(folder, asof="2026-11-16T00:00:00Z")

    def test_mixed_fiscal_period_is_not_merged_into_latest_quarter(self):
        with tempfile.TemporaryDirectory() as folder:
            row = row_fixture()
            row["季別"] = "2"
            self.snapshot(folder, [row])
            result = self.run_snapshot(folder)
        self.assertEqual(result["issuers"][0]["status"], "INVALID_REPORTED_FACTS")

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest, mp, _ = self.snapshot(folder)
            manifest["sources"][0]["path"] = "tw-market-data/financial/../../outside.json"
            mp.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ContractError, "UNSAFE"):
                self.run_snapshot(folder)


if __name__ == "__main__":
    unittest.main()
