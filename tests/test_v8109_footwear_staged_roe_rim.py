"""V8.10.9 issuer-filing independent book/EPS bridge and staged-ROE guard."""
import copy
import json
import unittest

from scripts.v8109_footwear_staged_roe_rim import INPUT,HISTORY,compute,value_path,inverse_roe


def fixtures():
    return json.loads(INPUT.read_bytes()),json.loads(HISTORY.read_bytes())


class Footwear2027PersistentROETests(unittest.TestCase):
    def test_balance_sheet_2026_h1_and_pb_are_source_crosschecked(self):
        j=compute(*fixtures())["companies"]
        bao=j["9904"]["source_reconciled_reported_financials"]
        ful=j["9802"]["source_reconciled_reported_financials"]
        self.assertAlmostEqual(bao["fraction_of_h1_pretax_profit_from_nonoperating_net_pct"],69.79,delta=.05)
        self.assertAlmostEqual(bao["reported_h1_nonoperating_net_billion_TWD"],6.564,places=3)
        self.assertGreater(bao["group_noncontrolling_equity_k"],83000000)
        self.assertAlmostEqual(ful["reported_h1_nonoperating_net_billion_TWD"],.009,delta=.001)
        self.assertAlmostEqual(ful["reported_h1_EPS"],1.78,places=2)
        self.assertAlmostEqual(bao["reported_h1_EPS"],2.37,places=2)

    def test_9802_third_quarter_gross_profit_is_depressed(self):
        j=compute(*fixtures())["companies"]
        q=j["9802"]["source_reconciled_reported_financials"]["q3_preliminary_not_full_statement"]
        self.assertAlmostEqual(q["gross_margin_pct"],13.233,delta=.01)
        self.assertAlmostEqual(q["q3_nonoperating_net_million"],-47.41,places=2)
        self.assertFalse(j["9802"]["revenue_to_operating_cash_flow_profit_bridge_certified"])

    def test_preliminary_eps_and_bull_bear_base_valuations_have_cashbook_path(self):
        j=compute(*fixtures())["companies"]
        for code in ("9802","9904"):
            cases=j[code]["2027_2031_staged_scenarios"]
            self.assertEqual([r["case"] for r in cases],["Bear","Base","Bull"])
            self.assertEqual(len(cases[0]["2027_to_2031_accounting_projection"]),5)
            self.assertTrue(all(r["formally_certified_Aplus"] is False for r in cases))
            self.assertLess(cases[0]["RIM_price_if_assumptions_hold"],cases[1]["RIM_price_if_assumptions_hold"])
            self.assertLess(cases[1]["RIM_price_if_assumptions_hold"],cases[2]["RIM_price_if_assumptions_hold"])
        self.assertAlmostEqual(j["9802"]["2027_2031_staged_scenarios"][1]["RIM_price_if_assumptions_hold"],35.70,delta=.05)
        self.assertAlmostEqual(j["9904"]["2027_2031_staged_scenarios"][1]["RIM_price_if_assumptions_hold"],34.35,delta=.05)

    def test_longrun_roe_needed_to_justify_price_is_different_from_one_year_eps(self):
        j=compute(*fixtures())["companies"]
        ful=j["9802"]
        bao=j["9904"]
        self.assertGreater(ful["required_terminal_ROE_to_justify_current_price_pct"],11)
        self.assertLess(ful["required_terminal_ROE_to_justify_current_price_pct"],12.5)
        self.assertGreater(ful["required_terminal_ROE_for_30pct_hypothetical_upside_pct"],13)
        self.assertLess(ful["required_terminal_ROE_for_30pct_hypothetical_upside_pct"],15)
        self.assertGreater(bao["required_terminal_ROE_to_justify_current_price_pct"],4)
        self.assertLess(bao["required_terminal_ROE_to_justify_current_price_pct"],6)
        self.assertGreater(bao["required_terminal_ROE_for_30pct_hypothetical_upside_pct"],5)
        self.assertLess(bao["required_terminal_ROE_for_30pct_hypothetical_upside_pct"],7)

    def test_equity_cost_increase_lowers_staged_value(self):
        j=compute(*fixtures())["companies"]
        for v in j.values():
            r=v["base_cost_of_equity_sensitivity"]
            self.assertLess(r["Ke_plus_2pp"]["RIM_price"],r["Ke_minus_2pp"]["RIM_price"])

    def test_never_claim_realized_returns_or_Aplus(self):
        r=compute(*fixtures())
        self.assertEqual(r["formal_Aplus_added"],0)
        self.assertEqual(r["orders_placed"],0)
        self.assertIsNone(r["realized_one_year_stock_total_return_vs_0050"])
        self.assertIsNone(r["probability_of_2027_excess_return_backtested"])
        self.assertFalse(r["full_original_MOPS_files_and_first_tradable_timestamp_verified"])

    def test_issuer_equity_per_share_must_reconcile(self):
        a,b=fixtures()
        a["stocks"]["9904"]["h1_2026_reported"]["parent_equity_k"] *=1.2
        with self.assertRaisesRegex(ValueError,"SHARE_UNITS_PARENT_EPS_VS_EQUITY_MISMATCH"):
            compute(a,b)

    def test_issuer_2026_public_prices_cannot_drift(self):
        a,b=fixtures()
        a["stocks"]["9802"]["parent_BVPS_2026q2"]=90.
        with self.assertRaisesRegex(ValueError,"OFFICIAL_TWSE_REFERENCE_PB_NOT_MATCH_PRICE_BOOK"):
            compute(a,b)

    def test_no_fake_company_pdf_archive(self):
        a,b=fixtures()
        a["sources"]["9904_h1_mops_reprint"]["original_MOPS_pdf_sha256"]="a"*64
        with self.assertRaisesRegex(ValueError,"UNARCHIVED_SOURCE_MISLABELED_VERIFIED"):
            compute(a,b)

    def test_company_q3_preliminary_must_not_be_audited_or_optimistic_margin(self):
        a,b=fixtures()
        a["stocks"]["9802"]["q3_2026_preliminary"]["preliminary_not_full_audited_report"]=False
        with self.assertRaisesRegex(ValueError,"FALSE_Q3_AUDIT_STATUS"):
            compute(a,b)
        a,b=fixtures()
        a["stocks"]["9802"]["q3_2026_preliminary"]["quarter_gross_profit_k"]*=1.5
        with self.assertRaisesRegex(ValueError,"Q3_PUBLIC_GROSS_MARGIN_ARITHMETIC_MISMATCH"):
            compute(a,b)

    def test_greater_discount_rate_lowers_value(self):
        a,b=fixtures()
        s=a["stocks"]["9802"]
        cap=value_path(s["parent_BVPS_2026q2"],4.92,.075,.115,.02,.35)["value_per_share"]
        stress=value_path(s["parent_BVPS_2026q2"],4.92,.075,.135,.02,.35)["value_per_share"]
        self.assertGreater(cap,stress)

    def test_no_perpetual_ROE_from_one_year_and_no_book_growth_arbitrage(self):
        a,b=fixtures()
        a["method"]["finite_horizon_not_perpetual_2027_ROE"]=False
        with self.assertRaisesRegex(ValueError,"FAKE_PIT_OR_FORMAL_MODEL_PROMOTION"):
            compute(a,b)
        with self.assertRaisesRegex(ValueError,"INVALID_RIM_FINANCIAL_ASSUMPTIONS"):
            value_path(67.72,4.92,.07,.03,.02,.35)

    def test_input_is_not_mutated(self):
        a,b=fixtures()
        cloned=copy.deepcopy(a)
        compute(a,b)
        self.assertEqual(a,cloned)


if __name__=="__main__":
    unittest.main()
