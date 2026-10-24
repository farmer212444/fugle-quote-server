"""2027 justified PB conservative scenario; never confuse with actual returns."""
import copy
import json
import unittest
from scripts.v8107_footwear_2027_roe_justified_pb import FILE, calculate


def specs():
    return json.loads(FILE.read_bytes())


class Test2027PB(unittest.TestCase):
    def test_math_and_reverse_roe_requirements(self):
        result=calculate(specs())
        issuers=result["issuer_2027_PB_research"]
        self.assertEqual(set(issuers),{"9904","6768","6965","9802","9910"})
        self.assertAlmostEqual(issuers["9802"]["2027_EPS_over_2026Q2_BVPS_proxy_roe_pct"],7.27,places=2)
        self.assertAlmostEqual(issuers["6965"]["2027_EPS_over_2026Q2_BVPS_proxy_roe_pct"],4.84,places=2)
        self.assertAlmostEqual(issuers["9904"]["current_PB_implied_permanent_roe_pct"],5.15,places=2)
        self.assertAlmostEqual(issuers["9910"]["current_PB_implied_permanent_roe_pct"],26.06,places=2)
        self.assertAlmostEqual(issuers["9904"]["justified_PB_if_2027_roe_persisted_indefinitely"],.7,places=2)
        self.assertGreater(issuers["9904"]["PB_when_equity_cost_minus_2pp"],issuers["9904"]["PB_when_equity_cost_plus_2pp"])
        self.assertTrue(result["no_formal_Aplus"])
        self.assertIsNone(result["verified_2027_total_return_against_0050"])

    def test_2027_estimates_are_not_formally_certified(self):
        data=specs()
        data["stock_input"][0]["base_eps_PIT_verified"]=True
        with self.assertRaisesRegex(ValueError,"UNVERIFIED_2027_FORECAST"):
            calculate(data)

    def test_book_value_from_2026_not_2027(self):
        data=specs()
        data["book_value_not_2027_estimate"]=False
        with self.assertRaisesRegex(ValueError,"PIT_OR_FORMAL_ROE"):
            calculate(data)

    def test_greater_growth_than_cost_equity_invalid(self):
        data=specs()
        data["stock_input"][0]["cost_of_equity"]=.03
        with self.assertRaisesRegex(ValueError,"EPS_BOOK_OR_KE_SANITY"):
            calculate(data)

    def test_official_pb_crosschecks_2026q2_bvps(self):
        data=specs()
        data["stock_input"][3]["bvps"]=120
        with self.assertRaisesRegex(ValueError,"REFERENCE_PB_NOT_CONSISTENT"):
            calculate(data)

    def test_duplicate_and_missing_issuers_fail_closed(self):
        data=specs()
        data["stock_input"][0]["code"]="9802"
        with self.assertRaisesRegex(ValueError,"DUPLICATE_OR_UNEXPECTED"):
            calculate(data)
        data=specs()
        data["stock_input"].pop()
        with self.assertRaisesRegex(ValueError,"FIVE_STOCK_UNIVERSE_INCOMPLETE"):
            calculate(data)

    def test_scenario_not_data_mutation(self):
        data=specs()
        clone=copy.deepcopy(data)
        calculate(data)
        self.assertEqual(data,clone)


if __name__=="__main__":
    unittest.main()
