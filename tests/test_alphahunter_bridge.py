"""Research-only synthetic earnings bridge tests: no investment outcome claims."""
from datetime import date, timedelta
import copy
import unittest
from alphahunter.core import EvidenceError
from alphahunter.earnings_bridge import build_eps_scenarios


def inputs():
    facts = {
        "trailing_period_end": "2025-12-31",
        "financials_available_at": "2026-03-31",
        "share_count_available_at": "2026-03-31",
        "trailing_revenue_twd": 100_000_000_000,
        "diluted_shares": 1_000_000_000,
        "source_receipts": ["artificial-unit-test-only"],
    }
    base = {
        "assumption_available_at": "2026-04-30",
        "revenue_growth": 0.1,
        "gross_margin": 0.20,
        "opex_ratio": 0.10,
        "net_nonoperating_twd": 0,
        "tax_rate": 0.2,
        "pe": 12,
        "dividend": 2,
    }
    scenarios = {}
    for name, growth, margin, pe in [
        ("bear", -0.1, 0.12, 10),
        ("base", 0.1, 0.20, 12),
        ("bull", 0.3, 0.25, 15),
    ]:
        scenarios[name] = dict(base, revenue_growth=growth, gross_margin=margin, pe=pe)
    return facts, scenarios


class IndependentEarningsBridgeTests(unittest.TestCase):
    def test_eps_arithmetic_and_valutation_compatible(self):
        facts, scenarios = inputs()
        out = build_eps_scenarios(facts, scenarios, "2026-05-01")
        self.assertAlmostEqual(out["scenarios"]["base"]["eps"], 8.8)
        self.assertAlmostEqual(out["income_bridge"]["base"]["operating_profit_twd"], 11e9)
        self.assertFalse(out["probabilities_calibrated"])
        self.assertFalse(out["source_references_proven"])

    def test_receipt_and_timestamp_pit(self):
        facts, assumptions = inputs()
        facts["financials_available_at"] = "2026-06-01"
        with self.assertRaisesRegex(EvidenceError, "UNAVAILABLE_ASOF"):
            build_eps_scenarios(facts, assumptions, "2026-05-01")
        facts, assumptions = inputs()
        assumptions["bear"]["assumption_available_at"] = "2026-06-01"
        with self.assertRaisesRegex(EvidenceError, "FUTURE_BRIDGE"):
            build_eps_scenarios(facts, assumptions, "2026-05-01")

    def test_future_shares_rejected(self):
        facts, assumptions = inputs()
        facts["share_count_available_at"] = "2026-05-02"
        with self.assertRaisesRegex(EvidenceError, "UNAVAILABLE_ASOF"):
            build_eps_scenarios(facts, assumptions, "2026-05-01")

    def test_revenue_units_and_diluted_shares(self):
        facts, assumptions = inputs()
        facts["diluted_shares"] = 2_000_000_000
        out = build_eps_scenarios(facts, assumptions, "2026-05-01")
        self.assertAlmostEqual(out["scenarios"]["base"]["eps"], 4.4)

    def test_negative_eps_is_not_valued_with_pe(self):
        facts, assumptions = inputs()
        assumptions["bear"]["opex_ratio"] = 0.4
        out = build_eps_scenarios(facts, assumptions, "2026-05-01")
        self.assertTrue(out["loss_making_scenario_not_pe_valued"])
        self.assertLess(out["income_bridge"]["bear"]["raw_eps"], 0)
        self.assertEqual(out["scenarios"]["bear"]["eps"], 0)

    def test_negative_growth_below_minus_100_rejected(self):
        facts, assumptions = inputs()
        assumptions["bear"]["revenue_growth"] = -1.1
        with self.assertRaisesRegex(EvidenceError, "OUT_OF_DOMAIN"):
            build_eps_scenarios(facts, assumptions, "2026-05-01")

    def test_missing_receipts_rejected(self):
        facts, assumptions = inputs()
        facts["source_receipts"] = []
        with self.assertRaisesRegex(EvidenceError, "SOURCE_REFERENCES_REQUIRED"):
            build_eps_scenarios(facts, assumptions, "2026-05-01")

    def test_misordered_scenario_values_rejected(self):
        facts, assumptions = inputs()
        assumptions["bear"]["dividend"] = 500
        with self.assertRaisesRegex(EvidenceError, "NOT_ORDERED"):
            build_eps_scenarios(facts, assumptions, "2026-05-01")

    def test_nonfinite_accounting_input_rejected(self):
        facts, assumptions = inputs()
        facts["diluted_shares"] = float("inf")
        with self.assertRaisesRegex(EvidenceError, "NONFINITE"):
            build_eps_scenarios(facts, assumptions, "2026-05-01")

    def test_future_asof_rejected(self):
        facts, assumptions = inputs()
        future = (date.today() + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(EvidenceError, "ASOF_IN_FUTURE"):
            build_eps_scenarios(facts, assumptions, future)


if __name__ == "__main__":
    unittest.main()
