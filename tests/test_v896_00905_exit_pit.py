"""Synthetic regression plus the public 00905 July-2025 removal timeline.

These are chronology/logic tests, not a PIT portfolio backtest or proof the
index selection was driven by any one specific factor.
"""
import copy
import json
from pathlib import Path
import unittest

from scripts.v896_00905_exit_pit import (
    FACTOR_WEIGHTS, build, evaluate, issuer_warning, render, validate_case,
)

CASE = Path(__file__).resolve().parents[1] / "tw-market-data/etf/index_reviews/2025-07-16_00905.json"

def fixture():
    return json.loads(CASE.read_text(encoding="utf-8"))

class IndexExitPITTests(unittest.TestCase):
    def test_2025_official_notice_contains_entire_cohort_not_single_winner(self):
        c = fixture()
        validate_case(c)
        self.assertEqual((len(c["added"]), len(c["removed"])), (44, 26))
        self.assertIn("9802", c["removed"])
        self.assertIn("1476", c["added"])
        self.assertIn("9904", c["added"])

    def test_index_rules_weight_40_quality_30_value_30_momentum(self):
        self.assertEqual(FACTOR_WEIGHTS, {"quality": .4, "value": .3, "momentum": .3})
        self.assertEqual(sum(FACTOR_WEIGHTS.values()), 1.0)

    def test_2025_june_cannot_know_july_delisting_event(self):
        data = evaluate(fixture(), "2025-06-30T23:59:59+08:00")
        self.assertTrue(data["issuer_observation_available_at_asof"])
        self.assertFalse(data["membership_decision_known_at_asof"])
        self.assertIsNone(data["index_notice_announced_at"])
        self.assertIsNone(data["effective_date"])
        self.assertIn("REVENUE_UP_EPS_YOY_DOWN", data["flags"])
        self.assertNotIn("ETF_INDEX_EXIT_NOTICE_PUBLICLY_KNOWN", data["flags"])
        self.assertFalse(data["formal_Aplus_changed"])

    def test_july16_index_announcement_at_1700_not_intraday(self):
        before = evaluate(fixture(), "2025-07-16T16:59:59+08:00")
        at = evaluate(fixture(), "2025-07-16T17:00:00+08:00")
        self.assertFalse(before["membership_decision_known_at_asof"])
        self.assertTrue(at["membership_decision_known_at_asof"])
        self.assertFalse(at["membership_exit_effective_at_asof"])
        self.assertEqual(at["event_status"], "PUBLIC_INDEX_EXIT_ANNOUNCED_NOT_YET_EFFECTIVE")

    def test_effective_at_taipei_midnight_not_utc_midnight(self):
        a = evaluate(fixture(), "2025-07-16T23:59:59+08:00")
        b = evaluate(fixture(), "2025-07-17T00:00:01+08:00")
        self.assertFalse(a["membership_exit_effective_at_asof"])
        self.assertTrue(b["membership_exit_effective_at_asof"])

    def test_publication_precision_is_conservative_end_of_day(self):
        at = evaluate(fixture(), "2025-04-22T23:59:58+08:00")
        after = evaluate(fixture(), "2025-04-22T23:59:59+08:00")
        self.assertFalse(at["issuer_observation_available_at_asof"])
        self.assertTrue(after["issuer_observation_available_at_asof"])

    def test_pre_issuer_publication_has_no_2025Q1_earnings_signal(self):
        result = evaluate(fixture(), "2025-04-21T16:00:00+08:00")
        self.assertEqual(result["flags"], [])
        self.assertFalse(result["issuer_observation_available_at_asof"])
        self.assertIsNone(result["issuer_evidence"])

    def test_q1_revenue_vs_eps_divergence_but_operating_profit_positive(self):
        x = issuer_warning(fixture()["issuer_observation"])
        self.assertEqual(x["code"], "9802")
        self.assertAlmostEqual(x["eps_yoy_pct"], -14.86, delta=.02)
        self.assertAlmostEqual(x["eps_qoq_pct"], -58.96, delta=.02)
        self.assertAlmostEqual(x["gross_margin_change_pp"], .98)
        self.assertEqual(x["operating_profit_yoy_pct"], 86.36)
        self.assertEqual(x["parent_net_income_yoy_pct"], -10.69)
        self.assertIn("OPERATING_PROFIT_UP_BUT_PARENT_PROFIT_DOWN", x["flags"])
        self.assertIn("GROSS_MARGIN_NOT_YET_DETERIORATING", x["flags"])
        self.assertIsNone(x["official_index_factor_score"])
        self.assertFalse(x["reason_for_00905_removal_confirmed"])

    def test_historical_rule_vintage_missing_blocks_exact_index_attribution(self):
        result = evaluate(fixture(), "2025-07-17T09:00:00+08:00")
        self.assertFalse(result["historical_2025_index_rule_vintage_verified"])
        self.assertFalse(result["full_universe_factor_zscores_verified"])
        self.assertFalse(result["index_eligibility_rank_replicated"])
        self.assertFalse(result["factor_causing_removal_determined"])
        self.assertIsNone(result["return_backtest_performance"])
        self.assertIsNone(result["trading_action"])

    def test_unverified_notice_cannot_be_promoted(self):
        item = fixture()
        item["source_document_verified"] = False
        with self.assertRaisesRegex(ValueError, "INDEX_NOTICE_NOT_CHECKED"):
            evaluate(item, "2026-10-21T12:00:00+08:00")

    def test_forbid_2025q2_after_index_cutoff_backfill(self):
        item = fixture()
        item["issuer_observation"]["period"] = "2025-Q2"
        with self.assertRaisesRegex(ValueError, "SOURCE_ID_OR_PERIOD"):
            evaluate(item, "2026-10-21T12:00:00+08:00")
        item = fixture()
        item["issuer_observation"]["available_at"] = "2025-07-21T17:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "ISSUER_FINANCIAL_POSTCUTOFF"):
            evaluate(item, "2026-10-21T12:00:00+08:00")

    def test_no_naive_timestamps_or_wrong_index(self):
        item = fixture()
        item["announced_at"] = "2025-07-16T17:00:00"
        with self.assertRaisesRegex(ValueError, "TIMEZONE"):
            validate_case(item)
        item = fixture()
        item["index_id"] = "IX0193"
        with self.assertRaisesRegex(ValueError, "ID_MISMATCH"):
            validate_case(item)

    def test_duplicate_or_overlap_cohort_is_rejected(self):
        item = fixture()
        item["removed"][0] = item["removed"][1]
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            validate_case(item)
        item = fixture()
        item["added"][0] = "9802"
        with self.assertRaisesRegex(ValueError, "OVERLAP"):
            validate_case(item)

    def test_future_dated_notice_cannot_be_backdated_to_data_cutoff(self):
        item = fixture()
        item["announced_at"] = "2025-06-30T16:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "EVENT_DATE"):
            validate_case(item)

    def test_undocumented_original_pdf_hash_is_not_fake_authentication(self):
        result = build(fixture())
        self.assertTrue(result["notice_source_verified"])
        self.assertFalse(result["raw_pdf_archived"])
        self.assertFalse(result["backtest_alpha_verified"])

    def test_report_reproduces_all_checkpoints_and_never_updates_a_plus(self):
        result = build(fixture())
        text = render(result)
        self.assertEqual(len(result["input_checkpoints"]), 5)
        self.assertIn("2025-06-30T23:59:59+08:00", text)
        self.assertIn("2025-07-16T17:00:00+08:00", text)
        self.assertIn("86.36", text)
        self.assertEqual(result["added_count"], 44)
        self.assertEqual(result["removed_count"], 26)
        self.assertFalse(result["formal_Aplus_changed"])
        self.assertFalse(result["base_target_price_changed"])
        self.assertTrue(result["no_auto_exit"])

if __name__ == "__main__":
    unittest.main()
