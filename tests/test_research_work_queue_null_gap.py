"""UI rendering must not turn unknown prices into A+ valuation signals."""
import math
import unittest

from scripts.research_work_queue import pct_or_pending,render

def report(gap=None,lane="A_PLUS_PRICE_ONLY"):
    return dict(model="V8.10.8",estimate_vintage="2026-11-12T15:20:00+08:00",
        aplus_repair=dict(price_qualified_research_issuers=0,
            original_captured_review_pending_issuers=0,review_ready_gate_issues=0,
            source_advanced_issuers=0,source_advanced_gate_issues=0,
            verification_priority=[dict(code="6206",name="飛捷",
                upside_pct=None,review_ready_original_gates=[],
                next_issuer_gate="original_eight_quarter_statements",
                next_issuer_action="COMPLETE_EVIDENCE_BRIDGE_AND_REVIEW")]),
        issuer_jobs=[],
        tsmc_aplus_research_status=dict(
            price_lane=lane,research_upside_pct=gap,
            original_quarter_coverage=None,company_gates_passed=0,
            company_gates_total=12,company_gates_pending=12,
            company_gates_failed=0,strategy_oos_gate_decision="PENDING",
            formal_Aplus=False,sec_6k_corroboration=None,
            valuation_financial_period="2026-Q2",reviewed_financial_period="2026-Q2",
            next_issuer_action="CAPTURE_AND_VERIFY_ORIGINAL_SOURCE"))

class ReportUnknownPrice(unittest.TestCase):
    def test_missing_and_nonfinite_are_explicitly_pending_not_zero_or_buy(self):
        for value in (None,float("nan"),float("inf"),True):
            self.assertEqual(pct_or_pending(value),"待核（缺少可比較估值）")
            text=render(report(value))
            self.assertIn("價格門檻待重新核對",text)
            self.assertIn("研究價差待核（缺少可比較估值）",text)
            self.assertIn("正式A+|否",text)
            self.assertNotIn("研究價差+0.0%",text)

    def test_actual_research_gap_uses_original_numeric_value(self):
        out=render(report(57.56))
        self.assertIn("A+價格候選（研究限定）",out)
        self.assertIn("研究價差+57.6%",out)
        self.assertIn("6206 飛捷|待核（缺少可比較估值）",out)

    def test_inconsistent_price_lane_never_admits_below_30_as_candidate(self):
        out=render(report(12.0))
        self.assertNotIn("A+價格候選（研究限定）",out)
        self.assertIn("研究價差+12.0%",out)

if __name__=="__main__":
    unittest.main()
