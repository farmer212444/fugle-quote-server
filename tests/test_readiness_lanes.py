"""Evidence-preserving research lanes: no inferred formal A+ or performance."""
import math
import unittest

from tw_model_v880.evidence import GATES
from tw_model_v880.readiness_lanes import (
    classify_issuer, summarize_lanes, render_readiness_report)


def issuer(code="2330", upside=58.1, status="PENDING", formal=False):
    return dict(
        code=code, name=code, market="TWSE",
        financial_period="2026-Q3", reviewed_financial_period="2026-Q2",
        research_upside_pct=upside, formal_Aplus=formal,
        gate_stage={g: dict(decision=status, formal_pass=status=="PASS") for g in GATES})


class IndependentAplusLaneTests(unittest.TestCase):
    def test_tsmc_candidate_never_means_certified(self):
        row=classify_issuer(issuer())
        self.assertEqual(row["price_lane"],"A_PLUS_PRICE_CANDIDATE_UNVERIFIED")
        self.assertEqual(row["company_quality_lane"],"QUALITY_REVIEW_PENDING")
        self.assertEqual(row["company_gates_pending"],12)
        self.assertEqual(row["strategy_validation_lane"],"STRATEGY_PIT_OOS_PENDING")
        self.assertAlmostEqual(row["dual_20pct_eps_pe_stress_upside_pct"],1.18,places=2)
        self.assertFalse(row["formal_Aplus"])
        self.assertTrue(row["no_trade_signal"])

    def test_12_company_pass_and_oos_pending_remain_separate(self):
        row=issuer()
        for gate in GATES:
            if gate!="out_of_sample_validation":
                row["gate_stage"][gate].update(decision="PASS",formal_pass=True)
        decision=classify_issuer(row)
        self.assertEqual(decision["company_quality_lane"],
                         "COMPANY_QUALITY_12_OF_12_FORMAL_PASS")
        self.assertEqual(decision["company_gates_passed"],12)
        self.assertEqual(decision["strategy_validation_lane"],
                         "STRATEGY_PIT_OOS_PENDING")
        self.assertFalse(decision["formal_Aplus"])

    def test_actual_thirteen_pass_can_reflect_original_formal_rating(self):
        row=issuer(status="PASS",formal=True)
        decision=classify_issuer(row)
        self.assertTrue(decision["formal_Aplus"])
        self.assertEqual(decision["company_gates_passed"],12)
        self.assertEqual(decision["strategy_validation_lane"],
                         "STRATEGY_PIT_OOS_FORMAL_PASS")
        self.assertTrue(decision["no_trade_signal"])

    def test_no_false_certification_and_no_infinity_price(self):
        with self.assertRaisesRegex(ValueError,"FALSE_FORMAL_APLUS"):
            classify_issuer(issuer(formal=True))
        for number in (float("nan"), float("inf"), -float("inf"), True, None):
            with self.subTest(number=number):
                decision=classify_issuer(issuer(upside=number))
                self.assertEqual(decision["price_lane"],"RESEARCH_PRICE_UNAVAILABLE")
                self.assertIsNone(decision["dual_20pct_eps_pe_stress_upside_pct"])
                self.assertFalse(decision["formal_Aplus"])

    def test_known_fail_differs_from_unreviewed_and_discovery(self):
        row=issuer(code="6206",upside=25.4)
        row["gate_stage"]["cash_and_working_capital"].update(
            decision="FAIL",formal_pass=False)
        got=classify_issuer(row)
        self.assertEqual(got["price_lane"],"A_DISCOVERY_PRICE_CANDIDATE_UNVERIFIED")
        self.assertEqual(got["company_quality_lane"],"DOCUMENTED_QUALITY_FAIL")
        self.assertEqual(got["company_gates_failed"],1)
        incomplete=issuer(code="9802",upside=-16.4)
        incomplete["gate_stage"]["original_eight_quarter_statements"].update(
            decision="NOT_EVALUATED",formal_pass=False)
        other=classify_issuer(incomplete)
        self.assertEqual(other["company_quality_lane"],"QUALITY_INPUT_INCOMPLETE")
        self.assertEqual(other["price_lane"],"PRICE_HURDLE_NOT_MET")

    def test_missing_or_inconsistent_gate_fails_closed(self):
        row=issuer()
        row["gate_stage"].pop("out_of_sample_validation")
        with self.assertRaisesRegex(ValueError,"INCOMPLETE_13_GATE"):
            classify_issuer(row)
        row=issuer()
        row["gate_stage"]["tradability"]["formal_pass"]=True
        with self.assertRaisesRegex(ValueError,"INVALID_FORMAL_GATE"):
            classify_issuer(row)

    def test_market_summary_and_tsmc_report_have_no_fake_pass(self):
        lanes=[classify_issuer(issuer()),classify_issuer(issuer("6206",57.6)),
               classify_issuer(issuer("9802",-16.4))]
        counts=summarize_lanes(lanes)
        self.assertEqual(counts["total_diagnosed_issuers"],3)
        self.assertEqual(counts["price_research_candidates"],2)
        self.assertEqual(counts["company_quality_12_gate_passed"],0)
        self.assertEqual(counts["strategy_pit_oos_formal_passed"],0)
        self.assertEqual(counts["formal_aplus_count"],0)
        report=dict(model="TEST",estimate_vintage="2026-11-07T22:00:00+08:00",
                    asof_price_date="2026-11-06",counts=counts,issuers=lanes)
        out=render_readiness_report(report)
        self.assertIn("台積電驗收樣本",out)
        self.assertIn("+58.1%",out)
        self.assertIn("正式PASS 0/12",out)
        self.assertIn("未完成認證",out)
        self.assertNotIn("核發新證書",out)


if __name__=="__main__":
    unittest.main()
