"""Synthetic tests only: do not infer actual market performance from fixtures."""
import copy
import unittest

from scripts.contrarian_reversal_watch import build_report, markdown, scenario_row


class ContrarianWatchTests(unittest.TestCase):
    def setUp(self):
        self.footwear = {
            "schema": "V8106_FOOTWEAR_REVIEW_V1",
            "estimate_vintage": "2026-11-11T06:50:20+08:00",
            "asof_price_date": "2026-11-10",
            "target_date": "2027-12-31",
            "companies": [{
                "code": "9802", "name": "鈺齊-KY",
                "price_date": "2026-11-10", "reference_close": 62.5,
                "research_cases": {
                    "Bear": {"target_price": 19.5, "eps": 2.2},
                    "Base": {"target_price": 58.3, "eps": 4.86, "input_assumptions": {"pe": 12}},
                    "Bull": {"target_price": 115.4, "eps": 7.69},
                },
            }]
        }
        self.flytech = {
            "issuer": "6206",
            "official_reference_price": {"close": 114, "date": "2026-11-10"},
            "scenarios": {
                "bear": {"target_price": 101.7, "eps": 8.48, "pe": 12},
                "base": {"target_price": 185.9, "eps": 11.62, "pe": 16},
                "bull": {"target_price": 253.3, "eps": 14.07, "pe": 18},
            },
        }

    def build(self, **kwargs):
        return build_report(self.footwear, self.flytech, asof="2026-11-12", **kwargs)

    def test_provisional_order_and_never_buy_label(self):
        result = self.build()
        self.assertEqual([r["code"] for r in result["rows"]], ["6206", "9802"])
        self.assertEqual(result["rows"][0]["research_lane"],
                         "BASE_DISCOUNT_WITH_LIMITED_SCENARIO_DOWNSIDE")
        self.assertEqual(result["rows"][1]["research_lane"], "UNCONFIRMED_RECOVERY_OPTION")
        self.assertTrue(result["price_snapshot_stale"])
        self.assertFalse(result["complete_market_scan"])
        self.assertFalse(result["expected_returns_calibrated"])
        self.assertFalse(result["rows"][1]["formal_Aplus"])
        for row in result["rows"]:
            self.assertIsNone(row["expected_return_pct"])
            self.assertIsNone(row["recommendation"])
            self.assertFalse(row["earnings_expectation_gap_confirmed"])
        self.assertIn("並非全市場 TOP10", markdown(result))

    def test_does_not_call_price_implied_eps_market_consensus(self):
        result = self.build()
        self.assertAlmostEqual(result["rows"][0]["price_divided_by_base_pe_eps_proxy"], 7.125)
        self.assertTrue(result["rows"][0]["proxy_is_not_market_consensus"])
        self.assertIsNone(result["rows"][0]["market_consensus_eps"])

    def test_no_future_price_or_research_vintage(self):
        self.flytech["official_reference_price"]["date"] = "2026-11-13"
        with self.assertRaisesRegex(ValueError, "MIXED_PRICE_DATES"):
            self.build()
        self.flytech["official_reference_price"]["date"] = "2026-11-10"
        self.footwear["estimate_vintage"] = "2026-11-13T00:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "FUTURE_RESEARCH_VINTAGE"):
            self.build()

    def test_no_future_overhang(self):
        with self.assertRaisesRegex(ValueError, "FUTURE_OVERHANG"):
            self.build(overhang={"9802": {"published_on": "2026-11-13"}})

    def test_unknown_overhang_not_silently_attached(self):
        with self.assertRaisesRegex(ValueError, "UNMATCHED_OVERHANG"):
            self.build(overhang={"0000": {"published_on": "2026-11-09"}})

    def test_no_misordered_or_missing_valuation(self):
        self.footwear["companies"][0]["research_cases"]["Bear"]["target_price"] = 80
        with self.assertRaisesRegex(ValueError, "SCENARIO_ORDER"):
            self.build()
        self.footwear["companies"][0]["research_cases"]["Bear"]["target_price"] = None
        with self.assertRaisesRegex(ValueError, "MISSING_SCENARIO"):
            self.build()

    def test_duplicate_or_unexpected_issuer(self):
        self.footwear["companies"].append(copy.deepcopy(self.footwear["companies"][0]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_ISSUER"):
            self.build()

    def test_invalid_entry_not_ranked(self):
        with self.assertRaisesRegex(ValueError, "BAD_PRICE"):
            scenario_row("9802", "x", 0, "2026-11-10",
                         {"bear": {"target_price": 10}, "base": {"target_price": 20},
                          "bull": {"target_price": 30}},
                         asof="2026-11-12", origin="fixture")


if __name__ == "__main__":
    unittest.main()
