"""Synthetic offline tests for 0050 non-reinvested gross rights reference only."""
from __future__ import annotations

from decimal import Decimal
import json
import tempfile
import unittest

from alphamax.benchmark_0050_cash_reference import build_cash_reference
from tests.test_alphamax_0050_milestones import create_sources
from scripts.tw_history_backfill import combine


class GrossCashReferenceTests(unittest.TestCase):
    def test_split_does_not_create_75pct_fake_crash_and_dividends_accrue_once(self):
        with tempfile.TemporaryDirectory() as temp:
            prices, notices, _ = create_sources(temp)
            report = build_cash_reference(prices, notices)
            self.assertEqual(
                report["status"],
                "RETROSPECTIVE_GROSS_CASH_RIGHTS_REFERENCE_NOT_PIT_OR_TOTAL_RETURN",
            )
            self.assertEqual(report["source_verified_ex_date_events"], 4)
            self.assertEqual(report["notice_originals_reverified"], 6)
            rows = {r["date"]: r for r in report["rows"]}
            before = rows["2025-06-10"]
            after = rows["2025-06-18"]
            self.assertEqual(before["mechanical_units_per_original_pre_split_unit"], 1)
            self.assertEqual(after["mechanical_units_per_original_pre_split_unit"], 4)
            self.assertEqual(before["mechanical_raw_quote_market_value_reference_ntd"], "200.0")
            self.assertEqual(after["mechanical_raw_quote_market_value_reference_ntd"], "200.0")
            self.assertEqual(
                before["mechanical_market_value_plus_gross_rights_reference_ntd"],
                after["mechanical_market_value_plus_gross_rights_reference_ntd"])
            self.assertEqual(rows["2025-01-17"]["cumulative_gross_dividend_rights_reference_ntd"], "2.7")
            self.assertEqual(rows["2025-07-21"]["cumulative_gross_dividend_rights_reference_ntd"], "4.14")
            self.assertEqual(rows["2026-01-22"]["cumulative_gross_dividend_rights_reference_ntd"], "8.14")
            self.assertEqual(rows["2026-07-21"]["cumulative_gross_dividend_rights_reference_ntd"], "10.54")
            self.assertEqual(len([r for r in report["rows"]
                                  if r["dividend_event_source_sha256"]]), 4)
            self.assertEqual(report["after_cost_12m_cohorts_verified"], 0)
            self.assertFalse(report["eligible_for_pit_or_oos_training"])
            self.assertFalse(report["investor_total_return_certified"])
            self.assertFalse(report["independent_total_return_benchmark_certified"])
            self.assertIsNone(report["official_model_winner"])
            self.assertFalse(report["formal_a_plus"])

    def test_entitlement_date_is_not_cash_received_or_scheduled_payment_date(self):
        with tempfile.TemporaryDirectory() as temp:
            prices, notices, _ = create_sources(temp)
            rows = {r["date"]: r for r in build_cash_reference(prices, notices)["rows"]}
            first = rows["2025-01-17"]
            self.assertEqual(first["cumulative_gross_dividend_rights_reference_ntd"], "2.7")
            self.assertEqual(first["of_which_scheduled_payment_date_passed_reference_ntd"], "0")
            self.assertFalse(first["actual_payment_received_verified"])
            self.assertEqual(rows["2025-06-10"]["of_which_scheduled_payment_date_passed_reference_ntd"], "2.7")
            second = rows["2025-07-21"]
            self.assertEqual(second["of_which_scheduled_payment_date_passed_reference_ntd"], "2.7")
            self.assertEqual(second["remaining_notional_payment_scheduled_reference_ntd"], "1.44")
            self.assertTrue(all(row["historical_pit_available_verified"] is False
                                for row in rows.values()))

    def test_missing_exact_ex_date_blocks_all_output(self):
        with tempfile.TemporaryDirectory() as temp:
            prices, notices, _ = create_sources(temp, remove_event="2025-07-21")
            r = build_cash_reference(prices, notices)
            self.assertEqual(r["status"], "BLOCKED_0050_REFERENCE_SOURCE_OR_EVENT_GAPS")
            self.assertEqual(r["rows"], [])
            self.assertIn("EX_DIVIDEND_2:2025-07-21", r["missing_events"])
            self.assertFalse(r["eligible_for_pit_or_oos_training"])

    def test_pinned_reference_price_date_requires_exact_latest_quote(self):
        with tempfile.TemporaryDirectory() as temp:
            prices, notices, packet_file = create_sources(temp)
            doc = json.loads(packet_file.read_text())
            doc["by_month"].pop("2026-11")
            doc["sessions"] = combine(
                {m: item["rows"] for m, item in doc["by_month"].items()},
                "2026-11-20", "0050")
            packet_file.write_text(json.dumps(doc))
            result = build_cash_reference(prices, notices)
            self.assertEqual(result["status"], "BLOCKED_0050_REFERENCE_LAST_RAW_QUOTE_STALE")
            self.assertEqual(result["latest_raw_quote_day"], "2026-07-21")
            self.assertEqual(result["rows"], [])
            self.assertFalse(result["eligible_for_pit_or_oos_training"])

    def test_tampered_normalized_quote_does_not_emit_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            prices, notices, packet_file = create_sources(temp)
            doc = json.loads(packet_file.read_text())
            doc["sessions"][0]["close"] = 99999
            packet_file.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, "CACHED_DERIVED_SESSIONS_MISMATCH"):
                build_cash_reference(prices, notices)

    def test_wrong_notice_bytes_blocks_all_output(self):
        with tempfile.TemporaryDirectory() as temp:
            prices, notices, _ = create_sources(temp)
            f = next((notices / "originals").glob("dividend_20250717-*.html"))
            f.write_bytes(f.read_bytes() + b"TAMPER")
            r = build_cash_reference(prices, notices)
            self.assertEqual(r["status"], "BLOCKED_0050_REFERENCE_SOURCE_OR_EVENT_GAPS")
            self.assertEqual(r["rows"], [])
            self.assertEqual(r["after_cost_12m_cohorts_verified"], 0)


if __name__ == "__main__":
    unittest.main()
