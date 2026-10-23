"""Real-archive accounting tests, deliberately NOT historical OOS proof."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v8105_insider_evidence_reconcile import audit, norm


class RealOriginalCrosscheckTests(unittest.TestCase):
    def test_encoded_legal_names_normalize(self):
        self.assertEqual(norm("&#28201;建&#21234;"), norm("温建勲"))
        self.assertEqual(norm("MEINDL  INT'L Co., Ltd."),norm("meindl int'l co., ltd."))

    def test_september_48_rows_both_official_feeds_match(self):
        report=audit(Path("."))
        self.assertEqual(report["issuer_count"],2)
        self.assertFalse(report["claims"]["identity_proof_or_historical_PIT_completed"])
        self.assertFalse(report["formal_Aplus_or_Exit_changed"])
        results=report["crosschecks"]
        self.assertEqual(results["9802"]["september_holding_rows_checked"],23)
        self.assertEqual(results["6965"]["september_holding_rows_checked"],25)
        for code in ("9802","6965"):
            r=results[code]
            self.assertTrue(r["all_cross_source_share_balances_match"])
            self.assertEqual(r["september_unmatched"],[])
            self.assertFalse(r["pass_formal_insider_quality_gate"])
            self.assertTrue(r["research_materiality_0_05pct_current_denominator_observed"])
            self.assertTrue(all(x["rollforward_mismatched_rows"]==0 for x in r["month_rollforwards"].values()))
        self.assertEqual(results["9802"]["issuer_current_shares_at_basics_report"],200991673)
        self.assertEqual(results["6965"]["issuer_current_shares_at_basics_report"],156336000)
        self.assertEqual(results["9802"]["jul_sep_market_net_lots_provisional"],1796)
        self.assertEqual(results["6965"]["jul_sep_market_net_lots_provisional"],311.052)

    def test_original_files_not_available_must_fail_not_zero(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(FileNotFoundError):
                audit(Path(t))


if __name__=="__main__":
    unittest.main()
