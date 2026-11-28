"""Synthetic-only AlphaMax concentration contract and allocation regressions."""
import copy
import unittest
from math import isnan

from alphamax.concentration import (
    ConcentrationPolicy, EVIDENCE_GATES, allocate_concentration, forecast_digest,
)
from alphamax.core import ContractError


def fixtures():
    candidates = [
        {"code": "AAA", "sector": "TECH", "asof": "2026-11-09", "horizon_months": 12,
         "expected_net_return_12m": .35, "lower_bound_net_return_12m": .25,
         "probability_loss_30pct": .12, "confidence": .95,
         "daily_turnover_ntd": 90_000_000, "executable": True},
        {"code": "BBB", "sector": "TECH", "asof": "2026-11-09", "horizon_months": 12,
         "expected_net_return_12m": .32, "lower_bound_net_return_12m": .22,
         "probability_loss_30pct": .15, "confidence": .93,
         "daily_turnover_ntd": 80_000_000, "executable": True},
        {"code": "CCC", "sector": "FIN", "asof": "2026-11-09", "horizon_months": 12,
         "expected_net_return_12m": .28, "lower_bound_net_return_12m": .18,
         "probability_loss_30pct": .13, "confidence": .90,
         "daily_turnover_ntd": 75_000_000, "executable": True},
    ]
    scenarios = {
        "macro-crash": {"AAA": .60, "BBB": .50, "CCC": .35},
        "sector-slump": {"AAA": .20, "BBB": .25, "CCC": .15},
    }
    evidence = {key: True for key in EVIDENCE_GATES}
    evidence.update({
        "asof": "2026-11-09",
        "receipt_ids": ["synthetic-only-test-not-real-receipt"],
        "forecast_sha256": forecast_digest(candidates, scenarios),
    })
    return candidates, scenarios, evidence


class ConcentrationTests(unittest.TestCase):
    def run_model(self, changes=None, scenario_changes=None, evidence_changes=None,
                  policy=None, cash=.025):
        rows, scenarios, evidence = fixtures()
        if changes:
            changes(rows)
        if scenario_changes:
            scenario_changes(scenarios)
        evidence["forecast_sha256"] = forecast_digest(rows, scenarios)
        if evidence_changes:
            evidence_changes(evidence)
        return allocate_concentration(
            rows, scenarios, evidence, cash_net_return_12m=cash, policy=policy
        )

    def test_no_live_trading_signal_even_with_all_contract_gates(self):
        out = self.run_model()
        self.assertEqual(out["status"], "RESEARCH_ALLOCATION_ONLY_NOT_LIVE")
        self.assertIs(out["buy_signal"], False)
        self.assertGreater(out["cash_weight"], 0)

    def test_weights_and_cash_sum_to_one(self):
        out = self.run_model()
        self.assertAlmostEqual(sum(x["weight"] for x in out["weights"])
                               + out["cash_weight"], 1.0)

    def test_joint_stress_budget_is_never_breached(self):
        out = self.run_model()
        self.assertLessEqual(out["scenario_worst_loss"], .12 + 1e-9)
        for loss in out["scenario_portfolio_loss"].values():
            self.assertLessEqual(loss, .12 + 1e-9)

    def test_single_weight_cap(self):
        out = self.run_model(policy=ConcentrationPolicy(max_joint_stress_loss=1))
        self.assertTrue(out["weights"])
        self.assertLessEqual(max(w["weight"] for w in out["weights"]), .20 + 1e-9)

    def test_sector_weight_cap(self):
        out = self.run_model(policy=ConcentrationPolicy(
            max_sector_weight=.25, max_joint_stress_loss=1
        ))
        tech = sum(w["weight"] for w in out["weights"] if w["sector"] == "TECH")
        self.assertLessEqual(tech, .25 + 1e-9)

    def test_negative_excess_cash_100_percent(self):
        out = self.run_model(changes=lambda r: [
            x.update(lower_bound_net_return_12m=.02, expected_net_return_12m=.03)
            for x in r
        ])
        self.assertEqual(out["weights"], [])
        self.assertEqual(out["cash_weight"], 1.0)

    def test_insufficient_confidence_is_rejected(self):
        out = self.run_model(changes=lambda r: r[0].update(confidence=.1))
        self.assertIn("INSUFFICIENT_CONFIDENCE",
                      next(x["reasons"] for x in out["rejected"] if x["code"]=="AAA"))

    def test_not_executable_is_rejected(self):
        out = self.run_model(changes=lambda r: r[0].update(executable=False))
        self.assertNotIn("AAA", [x["code"] for x in out["weights"]])
        self.assertIn("NOT_EXECUTABLE",
                      next(x["reasons"] for x in out["rejected"] if x["code"]=="AAA"))

    def test_low_liquidity_is_rejected(self):
        out = self.run_model(changes=lambda r: r[0].update(daily_turnover_ntd=1000))
        self.assertIn("LOW_LIQUIDITY",
                      next(x["reasons"] for x in out["rejected"] if x["code"]=="AAA"))

    def test_excess_tail_probability_is_rejected(self):
        out = self.run_model(changes=lambda r: r[0].update(probability_loss_30pct=.9))
        self.assertIn("EXCESS_TAIL_PROBABILITY",
                      next(x["reasons"] for x in out["rejected"] if x["code"]=="AAA"))

    def test_zero_stress_evidence_never_yields_weight(self):
        out = self.run_model(scenario_changes=lambda sc: [
            m.update(AAA=0.0) for m in sc.values()
        ])
        self.assertNotIn("AAA", [x["code"] for x in out["weights"]])
        self.assertIn("NO_EVIDENCED_JOINT_STRESS_LOSS",
                      next(x["reasons"] for x in out["rejected"] if x["code"]=="AAA"))

    def test_missing_gate_blocks_without_weights(self):
        def edit(e): e["probabilities_calibrated"] = False
        out = self.run_model(evidence_changes=edit)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["weights"], [])
        self.assertEqual(out["cash_weight"], 1.0)

    def test_missing_receipts_blocks(self):
        out = self.run_model(evidence_changes=lambda e: e.update(receipt_ids=[]))
        self.assertEqual(out["status"], "BLOCKED")

    def test_tampered_digest_blocks(self):
        out = self.run_model(evidence_changes=lambda e: e.update(forecast_sha256="0"*64))
        self.assertIn("HASH_MISMATCH", out["reason"])

    def test_missing_scenario_security_blocks(self):
        out = self.run_model(scenario_changes=lambda s: s["macro-crash"].pop("AAA"))
        self.assertEqual(out["status"], "BLOCKED")
        self.assertIn("MISSING_SECURITIES", out["reason"])

    def test_duplicate_code_blocks(self):
        out = self.run_model(changes=lambda r: r[1].update(code="AAA"))
        self.assertEqual(out["status"], "BLOCKED")
        self.assertIn("DUPLICATE", out["reason"])

    def test_future_dated_forecast_mismatch_blocks(self):
        out = self.run_model(changes=lambda r: r[0].update(asof="2027-01-01"))
        self.assertEqual(out["status"], "BLOCKED")

    def test_nonfinite_forecast_blocks(self):
        # Digest cannot encode NaN: create valid snapshot, then tamper row without
        # recomputing. Contract must fail rather than publish a recommendation.
        candidates, scenarios, evidence = fixtures()
        candidates[0]["expected_net_return_12m"] = float("nan")
        out = allocate_concentration(candidates, scenarios, evidence)
        self.assertEqual(out["status"], "BLOCKED")

    def test_shuffled_inputs_have_same_weights(self):
        candidates, scenarios, evidence = fixtures()
        a = allocate_concentration(candidates, scenarios, evidence)
        candidates.reverse()
        evidence["forecast_sha256"] = forecast_digest(candidates, scenarios)
        b = allocate_concentration(candidates, scenarios, evidence)
        self.assertEqual(a["weights"], b["weights"])
        self.assertEqual(a["scenario_portfolio_loss"], b["scenario_portfolio_loss"])

    def test_invalid_policy_does_not_silently_pass(self):
        with self.assertRaises(ContractError):
            ConcentrationPolicy(max_single_weight=.8, max_sector_weight=.3)

    def test_missing_evidence_blocks(self):
        rows, scenarios, _ = fixtures()
        out = allocate_concentration(rows, scenarios, None)
        self.assertEqual(out["status"], "BLOCKED")

    def test_bad_return_distribution_blocks(self):
        out = self.run_model(changes=lambda r: r[0].update(
            lower_bound_net_return_12m=.8
        ))
        self.assertEqual(out["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
