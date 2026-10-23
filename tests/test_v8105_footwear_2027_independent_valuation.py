"""Guard nonconsensus independent scenario math, 2027 date, PE loss gate."""
import copy
import json
import unittest

from scripts.v8105_footwear_2027_independent_valuation import ASSUMPTIONS, JOINED, evaluate


def inputs():
    return json.loads(ASSUMPTIONS.read_bytes()),json.loads(JOINED.read_bytes())


class FootwearIndependent2027ValuationTests(unittest.TestCase):
    def test_base_and_bull_require_real_operating_recovery(self):
        out=evaluate(*inputs())
        self.assertEqual(out["formal_Aplus_new_issuers"],0)
        self.assertIsNone(out["actual_2027_0050_excess_returns"])
        fs=out["models"]
        v9802=fs["9802"]["2027_cases"]
        self.assertEqual([s["case"] for s in v9802],["Bear","Base","Bull"])
        self.assertAlmostEqual(v9802[0]["attributable_eps"],2.0646,places=2)
        self.assertAlmostEqual(v9802[1]["attributable_eps"],4.9232,places=2)
        self.assertAlmostEqual(v9802[1]["scenario_fair_price"],68.93,delta=.25)
        self.assertAlmostEqual(v9802[2]["attributable_eps"],8.0332,places=2)
        self.assertGreater(v9802[1]["earnings_sensitivity_eps_per_1_gm_pp"],.75)
        self.assertLess(v9802[1]["earnings_sensitivity_eps_per_1_gm_pp"],.80)
        v6965=fs["6965"]["2027_cases"]
        self.assertLess(v6965[0]["attributable_eps"],0)
        self.assertIsNone(v6965[0]["scenario_fair_price"])
        self.assertAlmostEqual(v6965[1]["attributable_eps"],3.531,places=2)
        self.assertAlmostEqual(v6965[1]["scenario_fair_price"],52.96,delta=.25)
        self.assertAlmostEqual(v6965[2]["attributable_eps"],8.499,places=2)
        self.assertIsNone(fs["6965"].get("scenario_expected_price"))
        self.assertTrue(fs["6965"]["no_probability_weighted_fair_value_for_negative_eps_bear"])

    def test_reverse_margin_required_to_justify_price(self):
        r=evaluate(*inputs())["models"]
        self.assertGreater(r["9802"]["base_gm_required_to_justify_current_price_pct"],15.1)
        self.assertLess(r["9802"]["base_gm_required_to_justify_current_price_pct"],15.4)
        self.assertGreater(r["6965"]["base_gm_required_to_justify_current_price_pct"],14.3)
        self.assertLess(r["6965"]["base_gm_required_to_justify_current_price_pct"],14.7)
        self.assertEqual(r["9802"]["reference_close_twd"],62.6)
        self.assertEqual(r["6965"]["reference_close_twd"],64.3)

    def test_dilution_does_not_raise_eps(self):
        r=evaluate(*inputs())["models"]
        for company in r.values():
            for c in company["2027_cases"]:
                self.assertAlmostEqual(c["hypothetical_10pct_diluted_eps"],c["attributable_eps"]/1.1,places=3)
                if c["scenario_fair_price"] is not None:
                    self.assertLess(c["hypothetical_diluted_fair_price"],c["scenario_fair_price"])

    def test_denominators_dont_confuse_shares_and_lots(self):
        a,b=inputs()
        a["companies"]["9802"]["shares_asof_current"]=200991673
        with self.assertRaisesRegex(ValueError,"SHARE_COUNT_NOT_CROSSCHECKED"):
            evaluate(a,b)

    def test_no_unverified_original_document_hashes_are_invented(self):
        a,b=inputs()
        a["sources"]["9802_2026_q3"]["raw_original_sha256"]="a"*64
        with self.assertRaisesRegex(ValueError,"MISREPRESENTED_DOCUMENT_ARCHIVE_OR_PIT"):
            evaluate(a,b)

    def test_no_consensus_inputs_or_probabilities_claimed_backtested(self):
        a,b=inputs()
        a["policy"]["weights_type"]="VALIDATED_2025_BACKTEST_PROBABILITIES"
        with self.assertRaisesRegex(ValueError,"WEIGHTS_MISLABELED"):
            evaluate(a,b)
        a,b=inputs()
        a["policy"]["pe_independence"]="CONSENSUS_PRICE_TARGET"
        with self.assertRaisesRegex(ValueError,"ESTIMATE_NOT_INDEPENDENT"):
            evaluate(a,b)

    def test_scenarios_cannot_omit_bear_or_sum_above_one(self):
        a,b=inputs()
        a["companies"]["9802"]["cases"][0]["weight"]=.40
        with self.assertRaisesRegex(ValueError,"SCENARIO_PROBABILITIES_DONT_SUM"):
            evaluate(a,b)
        a,b=inputs()
        a["companies"]["6965"]["cases"].pop(0)
        with self.assertRaisesRegex(ValueError,"SCENARIO_ORDER_OR_COMPLETENESS"):
            evaluate(a,b)

    def test_prechecks_not_a_trade_eligible_issuer(self):
        a,b=inputs()
        b["company_rows"][1]["strategy_A_publicly_executable_signal"]=True
        with self.assertRaisesRegex(ValueError,"PRECHECK_NOT_ELIGIBLE_OR_ALREADY_PROMOTED"):
            evaluate(a,b)

    def test_gm_or_revenue_unit_tampering_rejected(self):
        a,b=inputs()
        a["companies"]["6965"]["cases"][1]["gross_margin_pct"]=105
        with self.assertRaisesRegex(ValueError,"INVALID_REVENUE_OR_MARGIN_BRIDGE"):
            evaluate(a,b)
        a,b=inputs()
        a["companies"]["6965"]["cases"][0]["reasonable_pe"]=14
        with self.assertRaisesRegex(ValueError,"LOSS_MAKING_PE_MUST_BE_NULL"):
            evaluate(a,b)

    def test_2025_financials_check_share_units(self):
        a,b=inputs()
        a["companies"]["9802"]["FY2025"]["annual_parent_net_m"]=1213482
        with self.assertRaisesRegex(ValueError,"ANNUAL_EPS_SHARE_UNIT_MISMATCH"):
            evaluate(a,b)


if __name__=="__main__":
    unittest.main()
