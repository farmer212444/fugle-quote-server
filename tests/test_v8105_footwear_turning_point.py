"""Research-only footwear turning point proof-contract tests."""
import copy
import json
import unittest

from scripts.v8105_footwear_turning_point import LEDGER, JOINT, REPORT_DATE, evaluate, quarter_bridge


def sources():
    return json.loads(LEDGER.read_bytes()), json.loads(JOINT.read_bytes())


class FootwearTurningPointTests(unittest.TestCase):
    def test_original_dated_quarter_profit_bridges(self):
        report = evaluate(*sources())
        self.assertTrue(report["all_returns_unknown"])
        self.assertEqual(report["formal_Aplus_new_count"],0)
        result=report["companies"]
        ji=result["9802"]
        cj=result["6965"]
        # 9802 official corporate Q2 -> Q3: +177434 revenue, -13540 GP,
        # +20095 Opex, -33635 operating earnings (NTD thousands).
        self.assertEqual(ji["bridge"]["incremental_revenue_ntd_thousands"],177434)
        self.assertEqual(ji["bridge"]["incremental_gross_profit_ntd_thousands"],-13540)
        self.assertEqual(ji["bridge"]["implied_increase_in_operating_expense_ntd_thousands"],20095)
        self.assertEqual(ji["bridge"]["incremental_operating_profit_ntd_thousands"],-33635)
        self.assertEqual(ji["turning_research_status"],"REVENUE_WITH_NO_OPERATING_PROFIT_CONVERSION")
        self.assertAlmostEqual(ji["bridge"]["gross_margin_qoq_change_pp"],-.7042,places=2)
        self.assertFalse(ji["earnings_recovery_1pp_provisional"])
        self.assertEqual(ji["latest_financial_quarter"],"2026Q3")
        self.assertFalse(ji["source_data_PIT_fully_independently_verified"])
        # 6965 company Q1 -> Q2 2026: +878m sales, +242m gross,
        # +232m operating profit, GM +2.7pp (rounded company source).
        self.assertEqual(cj["bridge"]["incremental_revenue_ntd_thousands"],878000)
        self.assertEqual(cj["bridge"]["incremental_gross_profit_ntd_thousands"],242000)
        self.assertEqual(cj["bridge"]["incremental_operating_profit_ntd_thousands"],232000)
        self.assertEqual(cj["turning_research_status"],"PROFIT_TURN_PRECHECK_PENDING_PIT")
        self.assertTrue(cj["earnings_recovery_1pp_provisional"])
        self.assertEqual(cj["latest_financial_quarter"],"2026Q2")

    def test_quarter_eps_margin_sensitivity_is_not_relabelled_as_forward_eps(self):
        r=evaluate(*sources())
        ji=r["companies"]["9802"]
        self.assertGreater(ji["hypothetical_plus_one_gm_pp_quarter_eps_effect_ntd"],.20)
        self.assertLess(ji["hypothetical_plus_one_gm_pp_quarter_eps_effect_ntd"],.23)
        self.assertFalse(ji["2027_Base_price_revised"])
        self.assertFalse(ji["no_auto_buy_or_recommendation"] is False)

    def test_missing_two_factor_cannot_fake_confirmation(self):
        ledger,joint=sources()
        joint["company_rows"][0]["insider_market_and_low_price_two_factor_precheck"]=False
        with self.assertRaisesRegex(ValueError,"UNVERIFIED_ISSUER_PRECHECK_OR_PROMOTED_ENTRY"):
            evaluate(ledger,joint)

    def test_future_dated_release_is_not_available_at_2026_10_23(self):
        ledger,joint=sources()
        ledger["sources"]["9802_q3"]["stated_release_date"]="2026-10-24"
        # data Q3 unavailable -> the program may evaluate Q1->Q2 but must NOT
        # incorporate any Q3 accounting on an earlier asof date.
        r=evaluate(ledger,joint)
        self.assertEqual(r["companies"]["9802"]["latest_financial_quarter"],"2026Q2")
        with self.assertRaisesRegex(ValueError,"UNAUTHORIZED_FORWARD_DATED_SNAPSHOT"):
            import datetime as dt
            evaluate(*sources(),asof=dt.date(2026,10,24))

    def test_income_statement_arithmetic_tamper_rejected(self):
        ledger,joint=sources()
        ledger["companies"]["9802"]["quarters"][-1]["operating_profit"]+=5000
        with self.assertRaisesRegex(ValueError,"OPERATING_PROFIT_BRIDGE_ARITHMETIC_MISMATCH"):
            evaluate(ledger,joint)

    def test_fabricated_margin_reported_rejected(self):
        ledger,joint=sources()
        ledger["companies"]["6965"]["quarters"][-1]["gm_reported_pct"]=21.8
        with self.assertRaisesRegex(ValueError,"GROSS_MARGIN_SOURCE_ARITHMETIC_MISMATCH"):
            evaluate(ledger,joint)

    def test_source_domain_guard(self):
        ledger,joint=sources()
        ledger["sources"]["6965_q2"]["url"]="https://unrelated.example.com/results"
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_NONISSUER_RESULTS_SOURCE"):
            evaluate(ledger,joint)

    def test_no_formal_Aplus_promotions(self):
        ledger,joint=sources()
        ledger["formal_Aplus_changed"]=True
        with self.assertRaisesRegex(ValueError,"UNAUTHORIZED_FORMAL_A_PLUS_PROMOTION"):
            evaluate(ledger,joint)


if __name__=="__main__":
    unittest.main()
