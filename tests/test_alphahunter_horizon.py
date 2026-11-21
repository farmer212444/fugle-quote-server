"""Synthetic tests for explicit fiscal-year horizon and no-future-data gates."""
from datetime import date, timedelta
import copy
import unittest

from alphahunter.core import EvidenceError
from alphahunter.forward_projection import build_fiscal_year_scenarios


def inputs():
    financials = {
        "trailing_period_end": "2025-12-31",
        "financials_available_at": "2026-03-31",
        "share_count_available_at": "2026-03-31",
        "trailing_revenue_twd": 100_000_000_000,
        "diluted_shares": 1_000_000_000,
        "source_receipts": ["synthetic-test-receipt-only"],
    }
    template = {
        "assumption_available_at": "2026-04-15",
        "annual_revenue_growth": {"2026": 0.10, "2027": 0.20},
        "gross_margin": 0.20,
        "opex_ratio": 0.10,
        "net_nonoperating_twd": 0,
        "tax_rate": 0.20,
        "pe": 12,
        "dividend": 2,
    }
    scenarios = {
        "bear": dict(template, annual_revenue_growth={"2026": -0.10, "2027": 0.00}, gross_margin=0.12, pe=10),
        "base": dict(template),
        "bull": dict(template, annual_revenue_growth={"2026": 0.20, "2027": 0.30}, gross_margin=0.25, pe=15),
    }
    return financials, scenarios


class HorizonTests(unittest.TestCase):
    def test_2027_requires_two_growth_steps(self):
        financials, specs = inputs()
        out = build_fiscal_year_scenarios(financials, specs, "2026-05-01", 2027)
        self.assertEqual(out["target_fiscal_year"], 2027)
        self.assertEqual(out["baseline_fiscal_year"], 2025)
        self.assertEqual(out["forecast_horizon_years"], 2)
        self.assertAlmostEqual(out["annual_revenue_path_twd"]["base"]["2026"], 110e9, delta=0.01)
        self.assertAlmostEqual(out["annual_revenue_path_twd"]["base"]["2027"], 132e9, delta=0.01)
        self.assertAlmostEqual(out["scenarios"]["base"]["eps"], 10.56)
        self.assertFalse(out["probabilities_calibrated"])

    def test_missing_intermediate_year_rejected(self):
        facts, specs = inputs()
        del specs["bear"]["annual_revenue_growth"]["2026"]
        with self.assertRaisesRegex(EvidenceError, "INTERMEDIATE_REVENUE_GROWTH_MISSING"):
            build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2027)

    def test_extra_year_rejected(self):
        facts, specs = inputs()
        specs["base"]["annual_revenue_growth"]["2028"] = 0.1
        with self.assertRaisesRegex(EvidenceError, "INTERMEDIATE_REVENUE_GROWTH_MISSING"):
            build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2027)

    def test_future_assumptions_rejected(self):
        facts, specs = inputs()
        specs["bull"]["assumption_available_at"] = "2026-05-02"
        with self.assertRaisesRegex(EvidenceError, "FUTURE_FISCAL_ASSUMPTION"):
            build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2027)

    def test_backwards_year_and_far_horizon_rejected(self):
        facts, specs = inputs()
        with self.assertRaisesRegex(EvidenceError, "UNSUPPORTED_FORECAST_HORIZON"):
            build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2025)
        with self.assertRaisesRegex(EvidenceError, "UNSUPPORTED_FORECAST_HORIZON"):
            build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2029)

    def test_growth_cannot_be_below_minus_100pct(self):
        facts, specs = inputs()
        specs["bear"]["annual_revenue_growth"]["2027"] = -1.1
        with self.assertRaisesRegex(EvidenceError, "IMPOSSIBLE_ANNUAL_REVENUE_GROWTH"):
            build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2027)

    def test_dilution_affects_projected_eps(self):
        facts, specs = inputs()
        facts["diluted_shares"] = 2_000_000_000
        out = build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2027)
        self.assertAlmostEqual(out["scenarios"]["base"]["eps"], 5.28)

    def test_future_fiscal_base_cannot_be_used(self):
        facts, specs = inputs()
        facts["financials_available_at"] = "2027-03-31"
        with self.assertRaisesRegex(EvidenceError, "UNAVAILABLE_ASOF_FINANCIALS"):
            build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2027)

    def test_full_year_baseline_mandatory(self):
        facts, specs = inputs()
        facts["trailing_period_end"] = "2025-09-30"
        with self.assertRaisesRegex(EvidenceError, "FULL_YEAR_DEC31_BASELINE_REQUIRED"):
            build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2027)

    def test_not_a_calendar_future_asof(self):
        facts, specs = inputs()
        with self.assertRaisesRegex(EvidenceError, "ASOF_IN_FUTURE"):
            build_fiscal_year_scenarios(facts, specs, (date.today()+timedelta(days=1)).isoformat(), 2027)

    def test_2026_one_year_forecast_contract(self):
        facts, specs = inputs()
        for scenario in specs.values():
            del scenario["annual_revenue_growth"]["2027"]
        out = build_fiscal_year_scenarios(facts, specs, "2026-05-01", 2026)
        self.assertEqual(out["forecast_horizon_years"], 1)
        self.assertAlmostEqual(out["scenarios"]["base"]["eps"], 8.8)


if __name__ == "__main__":
    unittest.main()
