"""Synthetic source-gate tests; never validate investment performance."""
from __future__ import annotations

import copy
import unittest

from alphamax.benchmark_0050_action_audit import (
    CASH_DISTRIBUTION_REFERENCES, SPLIT_NOTICE_URL,
    audit_0050_corporate_action_gaps,
)


def packet(days=("2025-06-10", "2025-06-18", "2025-07-21")):
    return {
        "issuer": "0050", "market": "TWSE",
        "price_reference_asof": "2026-11-13",
        "sessions": [
            {"date": day, "code": "0050", "market": "TWSE", "close": 50.0}
            for day in days
        ],
    }


class Action0050Tests(unittest.TestCase):
    def test_known_split_crossing_is_blocked_not_falsely_scored(self):
        out = audit_0050_corporate_action_gaps(packet())
        self.assertEqual(out["status"], "BLOCKED_0050_SPLIT_AND_CASH_DISTRIBUTION_TOTAL_RETURN_LEDGER")
        self.assertTrue(out["raw_prices_span_split_date"])
        self.assertTrue(out["split_event"]["raw_quote_at_last_pre_split_session"])
        self.assertTrue(out["split_event"]["raw_quote_at_first_post_split_session"])
        self.assertEqual(out["split_event"]["post_split_units_per_pre_split_unit"], 4)
        self.assertEqual(out["split_event"]["announcement_reference_url"], SPLIT_NOTICE_URL)
        self.assertFalse(out["split_event"]["original_announcement_bytes_archived_and_verified"])
        self.assertFalse(out["daily_adjusted_investor_total_returns_verified"])
        self.assertEqual(out["oos_12m_after_cost_cohorts_verified"], 0)
        self.assertIsNone(out["official_model_winner"])
        self.assertFalse(out["formal_Aplus"])
        self.assertFalse(out["live_buy_authorized"])

    def test_pre_split_dividend_is_not_post_split_denominated(self):
        self.assertEqual(CASH_DISTRIBUTION_REFERENCES[0][0], "2025-01-17")
        self.assertEqual(CASH_DISTRIBUTION_REFERENCES[0][2], 2.7)
        self.assertEqual(CASH_DISTRIBUTION_REFERENCES[0][3], "PRE_2025_SPLIT_UNIT")
        out = audit_0050_corporate_action_gaps(packet())
        self.assertTrue(all(not x["reconciled_to_adjusted_total_return"]
                            for x in out["cash_distribution_reference_candidates"]))
        self.assertTrue(all(not x["original_fund_notice_bytes_and_payment_verified"]
                            for x in out["cash_distribution_reference_candidates"]))

    def test_exchange_suspension_must_not_contain_price(self):
        for suspended in ("2025-06-11", "2025-06-13", "2025-06-17"):
            with self.subTest(day=suspended), self.assertRaisesRegex(
                    ValueError, "PRICE_ON_OFFICIAL_SPLIT_SUSPENSION"):
                audit_0050_corporate_action_gaps(packet(("2025-06-10", suspended, "2025-06-18")))

    def test_wrong_security_duplicate_and_future_prices_rejected(self):
        q = packet()
        q["issuer"] = "2330"
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"):
            audit_0050_corporate_action_gaps(q)
        q = packet(("2025-06-10", "2025-06-10"))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SESSION"):
            audit_0050_corporate_action_gaps(q)
        q = packet(("2025-06-18", "2026-11-14"))
        with self.assertRaisesRegex(ValueError, "FUTURE_SESSION"):
            audit_0050_corporate_action_gaps(q)

    def test_missing_and_nonfinite_prices_rejected(self):
        q = packet(())
        with self.assertRaisesRegex(ValueError, "SESSIONS_MISSING"):
            audit_0050_corporate_action_gaps(q)
        for price in (None, -1, 0, True, float("nan"), float("inf")):
            q = packet()
            q["sessions"][0]["close"] = price
            with self.subTest(price=str(price)), self.assertRaisesRegex(
                    ValueError, "INVALID_RAW_CLOSE"):
                audit_0050_corporate_action_gaps(q)

    def test_no_crossing_if_benchmark_starts_after_split(self):
        out = audit_0050_corporate_action_gaps(packet(("2026-01-22", "2026-07-21")))
        self.assertFalse(out["raw_prices_span_split_date"])
        self.assertFalse(out["cash_dividend_and_split_ledger_complete"])
        self.assertEqual(out["oos_12m_after_cost_cohorts_verified"], 0)


if __name__ == "__main__":
    unittest.main()
