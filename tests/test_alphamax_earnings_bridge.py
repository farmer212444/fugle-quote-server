"""Financial arithmetic and PIT boundary tests; all inputs below are synthetic."""
import copy
from datetime import datetime, timezone
import unittest

from alphamax.core import ContractError
from alphamax.earnings_bridge import earnings_bridge


def fixture():
    scenario = {
        "revenue_twd": 1_000_000_000, "gross_margin": .40,
        "operating_expenses_twd": 100_000_000,
        "net_nonoperating_income_twd": 10_000_000,
        "effective_tax_rate": .20, "noncontrolling_profit_twd": 8_000_000,
        "diluted_shares": 100_000_000, "exit_pe": 15,
        "net_dividends_per_share_twd": 1,
        "assumption_note": "Synthetic operating assumptions, not a stock forecast.",
        "source_receipt_ids": ["synthetic-report"],
    }
    spec = {
        "schema": "alphamax-earnings-bridge-v1", "code": "SYNTHETIC",
        "currency": "TWD", "shares_unit": "shares", "asof": "2026-11-17T02:00:00+00:00",
        "valuation_date": "2027-12-31", "required_net_return": .30,
        "quote": {"close_twd": 30, "available_at": "2026-11-16T06:00:00Z",
                  "source_receipt_id": "synthetic-report"},
        "source_receipts": [{"id": "synthetic-report", "source_url": "https://example.org/synthetic-only",
                             "sha256": "a" * 64, "published_at": "2026-11-13T06:00:00Z",
                             "observed_at": "2026-11-16T07:00:00Z"}],
        "costs": {"buy_fee_rate": .001, "buy_slippage_rate": .001,
                  "sell_fee_rate": .001, "sell_tax_rate": .003, "sell_slippage_rate": .001},
        "scenarios": {name: copy.deepcopy(scenario) for name in ("bear", "base", "bull")},
    }
    spec["scenarios"]["bear"]["gross_margin"] = .30
    spec["scenarios"]["bull"]["gross_margin"] = .50
    return spec


NOW = datetime(2026, 11, 17, 3, tzinfo=timezone.utc)


class EarningsBridgeTests(unittest.TestCase):
    def calculate(self, spec=None):
        return earnings_bridge(fixture() if spec is None else spec, now=NOW)

    def test_operating_inputs_reconcile_to_parent_eps(self):
        base = self.calculate()["scenarios"][1]
        self.assertEqual(base["gross_profit_twd"], 400_000_000)
        self.assertEqual(base["operating_profit_twd"], 300_000_000)
        self.assertEqual(base["pretax_profit_twd"], 310_000_000)
        self.assertEqual(base["parent_profit_twd"], 240_000_000)
        self.assertAlmostEqual(base["eps_twd"], 2.4)
        self.assertAlmostEqual(base["scenario_price_twd"], 36)

    def test_dilution_halves_eps_with_same_profit(self):
        spec = fixture()
        spec["scenarios"]["base"]["diluted_shares"] *= 2
        row = self.calculate(spec)["scenarios"][1]
        self.assertAlmostEqual(row["eps_twd"], 1.2)

    def test_net_dividends_are_not_charged_stock_sale_tax(self):
        row = self.calculate()["scenarios"][1]
        expected = (36 * .995 + 1) / (30 * 1.002) - 1
        self.assertAlmostEqual(row["scenario_net_return_to_valuation_date"], expected)

    def test_entry_ceiling_actually_delivers_required_return_after_costs(self):
        result = self.calculate()
        for row in result["scenarios"]:
            entry = row["max_entry_price_for_required_net_return_twd"]
            spec = fixture()
            spec["quote"]["close_twd"] = entry
            check = self.calculate(spec)["scenarios"]
            actual = next(r for r in check if r["scenario"] == row["scenario"])
            self.assertAlmostEqual(actual["scenario_net_return_to_valuation_date"], .30)

    def test_loss_company_has_no_fake_positive_pe_value_or_tax_credit(self):
        spec = fixture()
        spec["scenarios"]["bear"]["operating_expenses_twd"] = 600_000_000
        row = self.calculate(spec)["scenarios"][0]
        self.assertLess(row["eps_twd"], 0)
        self.assertEqual(row["tax_expense_twd"], 0)
        self.assertIsNone(row["scenario_price_twd"])
        self.assertIsNone(row["max_entry_price_for_required_net_return_twd"])

    def test_scenarios_never_become_calibrated_forecasts_or_buy_signals(self):
        result = self.calculate()
        self.assertIsNone(result["calibrated_probabilities"])
        self.assertIsNone(result["expected_net_return_12m"])
        self.assertIsNone(result["portfolio_weights"])
        self.assertFalse(result["buy_signal"])
        self.assertFalse(result["investment_certified"])

    def test_later_discovered_source_cannot_be_used_in_earlier_asof(self):
        spec = fixture()
        spec["source_receipts"][0]["observed_at"] = "2026-11-18T00:00:00Z"
        with self.assertRaisesRegex(ContractError, "SOURCE_NOT_OBSERVED"):
            self.calculate(spec)

    def test_future_quote_and_future_asof_rejected(self):
        for location in ("quote", "asof"):
            with self.subTest(location=location):
                spec = fixture()
                if location == "quote":
                    spec["quote"]["available_at"] = "2026-11-18T00:00:00Z"
                else:
                    spec["asof"] = "2026-11-18T00:00:00Z"
                with self.assertRaises(ContractError):
                    self.calculate(spec)

    def test_scenario_sources_must_resolve_to_declared_observations(self):
        spec = fixture()
        spec["scenarios"]["base"]["source_receipt_ids"] = ["not-declared"]
        with self.assertRaisesRegex(ContractError, "UNKNOWN_OR_MISSING_SCENARIO_SOURCE"):
            self.calculate(spec)

    def test_assumption_edits_change_digest_and_leave_input_unchanged(self):
        spec = fixture()
        before = copy.deepcopy(spec)
        first = self.calculate(spec)
        self.assertEqual(spec, before)
        spec["scenarios"]["base"]["gross_margin"] = .41
        second = self.calculate(spec)
        self.assertNotEqual(first["input_sha256"], second["input_sha256"])

    def test_invalid_units_shares_margins_costs_and_nan_rejected(self):
        mutations = [
            lambda s: s.update(currency="USD"),
            lambda s: s.update(shares_unit="thousands"),
            lambda s: s["scenarios"]["base"].update(diluted_shares=0),
            lambda s: s["scenarios"]["base"].update(gross_margin=40),
            lambda s: s["scenarios"]["base"].update(revenue_twd=float("nan")),
            lambda s: s["costs"].update(sell_tax_rate=1),
            lambda s: s["scenarios"]["base"].update(diluted_shares=True),
        ]
        for edit in mutations:
            with self.subTest(edit=edit):
                spec = fixture()
                edit(spec)
                with self.assertRaises(ContractError):
                    self.calculate(spec)

    def test_user_supplied_probabilities_cannot_silently_become_expected_returns(self):
        for top_level in (True, False):
            spec = fixture()
            if top_level:
                spec["probabilities"] = [.2, .6, .2]
            else:
                spec["scenarios"]["base"]["probability"] = .6
            with self.assertRaises(ContractError):
                self.calculate(spec)

    def test_name_bear_does_not_guarantee_lowest_price(self):
        spec = fixture()
        spec["scenarios"]["bear"]["exit_pe"] = 100
        result = self.calculate(spec)
        self.assertFalse(result["scenario_labels_price_ordered"])
        self.assertTrue(result["warnings"])

    def test_horizon_is_explicit_and_not_mislabeled_as_12_months(self):
        result = self.calculate()
        self.assertEqual(result["horizon_days"], 409)
        self.assertIn("to_valuation_date", next(k for k in result["scenarios"][0] if k.startswith("scenario_net_return")))


if __name__ == "__main__":
    unittest.main()
