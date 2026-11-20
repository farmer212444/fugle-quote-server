"""Fail-closed tests for 9802 Q3 cash shadow; only arithmetic, not PDF SHA certification."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("q3_cash_shadow", ROOT / "scripts/9802_q3_cash_shadow.py")
cash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cash)


class Q3CashShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads(cash.RECEIPT_PATH.read_text(encoding="utf-8"))
        cls.h1 = json.loads(cash.OLDER_REPORT_PATH.read_text(encoding="utf-8"))

    def test_q3_math_and_formal_gate_remain_pending(self):
        out = cash.build(copy.deepcopy(self.receipt), copy.deepcopy(self.h1))
        self.assertEqual(out["ocf_q3_2026_k"], 383997)
        self.assertEqual(out["ocf_q3_2025_k"], 1901358)
        self.assertEqual(out["simple_fcf_2026_k"], -937579)
        self.assertEqual(out["simple_fcf_2025_k"], -434175)
        self.assertEqual(out["cash_2026_09_30_k"], 1635294)
        self.assertEqual(out["inventory_2026_09_30_k"], 3432388)
        self.assertAlmostEqual(out["inventory_yoy_pct"], 29.6363, places=2)
        self.assertFalse(out["formal_Aplus"])
        self.assertFalse(out["source_quality_gate_pass"])
        self.assertFalse(out["changes_eps_or_target_price"])
        self.assertFalse(out["original_pdf_sha256_verified"])
        self.assertFalse(out["actual_cb_put_requests_or_settlement_verified"])
        self.assertFalse(out["undrawn_facility_is_cash"])

    def test_no_h1_evidence_means_no_sole_quarter_claim(self):
        out = cash.build(copy.deepcopy(self.receipt))
        self.assertIsNone(out["ocf_q3_2026_k"])
        self.assertFalse(out["h1_cash_review_reconciled"])

    def test_changed_q3_ocf_must_fail(self):
        r = copy.deepcopy(self.receipt)
        r["totals_signed_k"]["operating_cash_flow"][0] += 1
        with self.assertRaisesRegex(ValueError, "9802_Q3_OCF_MISMATCH"):
            cash.build(r, self.h1)

    def test_changed_inventory_must_fail(self):
        r = copy.deepcopy(self.receipt)
        r["balances_k"]["inventory_net"][0] += 1
        with self.assertRaisesRegex(ValueError, "9802_Q3_INVENTORY_RECONCILE_MISMATCH"):
            cash.build(r, self.h1)

    def test_changed_h1_period_or_ocf_must_fail(self):
        h = copy.deepcopy(self.h1)
        h["original_cash_review"]["cashflow_signed_k"]["ocf"][0] += 1
        with self.assertRaisesRegex(ValueError, "9802_Q3_H1_OCF_RECEIPT_MISMATCH"):
            cash.build(copy.deepcopy(self.receipt), h)

    def test_attempt_to_self_certify_must_fail(self):
        r = copy.deepcopy(self.receipt)
        r["flags"]["formal_Aplus"] = True
        with self.assertRaisesRegex(ValueError, "9802_Q3_QUALITY_GATE_MISREPRESENTED"):
            cash.build(r, self.h1)

    def test_attempt_to_fake_pdf_hash_must_fail(self):
        r = copy.deepcopy(self.receipt)
        r["pdf_sha256_verified"] = True
        with self.assertRaisesRegex(ValueError, "9802_Q3_SOURCE_HASH_OR_PIT_MISREPRESENTED"):
            cash.build(r, self.h1)

    def test_markdown_not_certificate(self):
        text = cash.markdown(cash.build(self.receipt, self.h1))
        self.assertIn("不覆寫", text)
        self.assertIn("不得授予", text)


if __name__ == "__main__":
    unittest.main()
