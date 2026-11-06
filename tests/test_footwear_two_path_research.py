"""Synthetic two-path contract tests and static repository-data audit guards."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.v8105_footwear_two_path_audit import build
from tests.test_footwear_insider_holdout import DECISION, snapshot
from tw_model_v880.footwear_insider_holdout import evaluate_signal


def fixtures():
    insider = json.loads(Path("tw-market-data/evidence/v880/insider_reviews/shoe_makers_202609_secondary_shadow.json").read_text(encoding="utf-8"))
    etf = json.loads(Path("tw-market-data/benchmarks/0050/latest_source_status.json").read_text(encoding="utf-8"))
    return insider, etf


class TwoPathResearchTests(unittest.TestCase):
    def setUp(self):
        self.shadow = patch("tw_model_v880.insider_accumulation.evaluate_insider_accumulation",
                            return_value={"status": "RESEARCH_WATCH_REQUIRES_INDEPENDENT_AUDIT",
                                          "three_month_net_lots": 411})
        self.shadow.start()

    def tearDown(self):
        self.shadow.stop()

    def test_early_path_can_research_without_gm_gate(self):
        s = snapshot()
        s["gross_margin_quarters"][-1]["gross_profit"] = 8
        a = evaluate_signal(s, decision_at=DECISION, require_margin=False)
        b = evaluate_signal(s, decision_at=DECISION, require_margin=True)
        self.assertEqual(a["status"], "EARLY_RESEARCH_SIGNAL_REQUIRES_INDEPENDENT_ORIGINAL_AUDIT")
        self.assertEqual(a["signal_variant"], "A_EARLY")
        self.assertFalse(a["forward_returns_certified"])
        self.assertEqual(b["status"], "GROSS_MARGIN_NOT_RECOVERING_BY_1PP")

    def test_missing_financial_original_does_not_block_a_but_blocks_b(self):
        s = snapshot()
        s["gross_margin_quarters"] = []
        self.assertTrue(evaluate_signal(s, decision_at=DECISION, require_margin=False)["eligible_research_signal"])
        self.assertEqual(evaluate_signal(s, decision_at=DECISION, require_margin=True)["status"],
                         "PENDING_TWO_PUBLISHED_QUARTER_MARGINS")

    def test_b_requires_recovery_and_early_also_qualifies(self):
        s = snapshot()
        self.assertEqual(evaluate_signal(s, decision_at=DECISION)["signal_variant"], "B_GM_CONFIRMED")
        self.assertEqual(evaluate_signal(s, decision_at=DECISION, require_margin=False)["signal_variant"], "A_EARLY")

    def test_both_share_low_price_and_insider_gates(self):
        s = snapshot()
        s["trailing_price_evidence"]["closes"][-1]["close"] = 180
        for margin_required in (True, False):
            self.assertEqual(evaluate_signal(s, decision_at=DECISION, require_margin=margin_required)["status"],
                             "PRICE_NOT_IN_BOTTOM_20_PERCENT")
        with patch("tw_model_v880.insider_accumulation.evaluate_insider_accumulation",
                   return_value={"status": "PENDING_OFFICIAL_MARKET_TRADE_ORIGINAL"}):
            for flag in (True, False):
                self.assertEqual(evaluate_signal(snapshot(), decision_at=DECISION,
                                                 require_margin=flag)["status"],
                                 "INSIDER_PENDING_OFFICIAL_MARKET_TRADE_ORIGINAL")

    def test_actual_secondary_issuer_rows_yield_null_performance(self):
        report = build(*fixtures())
        self.assertEqual(report["strategy_a_research_precheck_count"], 2)
        self.assertEqual(report["strategy_a_certified_signal_count"], 0)
        self.assertEqual(report["strategy_b_certified_signal_count"], 0)
        self.assertIsNone(report["strategy_a_12m_win_rate_vs_0050"])
        self.assertIsNone(report["strategy_b_12m_alpha_vs_0050"])
        rows = {x["code"]: x for x in report["issuers"]}
        self.assertEqual(rows["9802"]["jul_aug_sep_three_month_net_lots"], 1796)
        self.assertEqual(rows["6965"]["jul_aug_sep_three_month_net_lots"], 311)
        self.assertFalse(rows["9910"]["three_month_positive_secondary_observed"])
        self.assertFalse(report["any_performance_claim_from_this_report"])

    def test_cannot_mislabel_secondary_as_official(self):
        a, b = fixtures()
        a["official_mops_post_trade_originals_received"] = True
        with self.assertRaisesRegex(ValueError, "INSIDER_SECONDARY_SOURCE_MISCLASSIFIED"):
            build(a, b)

    def test_negative_and_duplicate_input_is_rejected(self):
        a, b = fixtures()
        a["records"][0]["market_buys"][-1] = -1
        with self.assertRaisesRegex(ValueError, "INVALID_MONTHLY_TRADE_LOTS"):
            build(a, b)
        a, b = fixtures()
        a["records"].append(copy.deepcopy(a["records"][0]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_ISSUER"):
            build(a, b)

    def test_cannot_supply_another_etf_unnoticed(self):
        a, b = fixtures()
        b["benchmark_id"] = "006208"
        with self.assertRaisesRegex(ValueError, "WRONG_BENCHMARK_SOURCE"):
            build(a, b)


if __name__ == "__main__":
    unittest.main()
