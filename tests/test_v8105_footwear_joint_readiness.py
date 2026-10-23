"""Real original-source join tests; prevents source promotion to A+."""
import copy
import json
import unittest
from pathlib import Path

from scripts.v8105_footwear_joint_readiness import REPORTS, combine


def archived():
    return (json.loads(REPORTS["insider"].read_bytes()),
            json.loads(REPORTS["price"].read_bytes()))


class JoinedEvidenceTests(unittest.TestCase):
    def test_two_prechecks_with_null_recommendations_and_returns(self):
        result=combine(*archived())
        self.assertEqual(result["formal_Aplus_added"],0)
        self.assertIsNone(result["real_one_year_win_rate_vs_0050"])
        self.assertEqual(len(result["company_rows"]),2)
        rows={x["code"]:x for x in result["company_rows"]}
        for code in ("9802","6965"):
            row=rows[code]
            self.assertTrue(row["three_month_size_0_05pct_precheck"])
            self.assertTrue(row["low_20pct_unadjusted_precheck"])
            self.assertTrue(row["insider_market_and_low_price_two_factor_precheck"])
            self.assertFalse(row["strategy_A_publicly_executable_signal"])
            self.assertFalse(row["strategy_B_GM_confirmed_publicly_executable_signal"])
        self.assertEqual(rows["9802"]["252_close_position_pct"],0.)
        self.assertEqual(rows["6965"]["252_close_position_pct"],11.06)

    def test_reject_missing_source_and_wrong_calendar(self):
        ins,prices=archived()
        prices["calendar_sessions"]=251
        with self.assertRaisesRegex(ValueError,"INCORRECT_252_WINDOW_DATE_OR_COUNT"):
            combine(ins,prices)
        ins,prices=archived()
        ins["claims"]["raw_original_bytes_sha_verified"]=False
        with self.assertRaisesRegex(ValueError,"OFFICIAL_ORIGINALS_AND_BALANCES_NOT_VERIFIED"):
            combine(ins,prices)

    def test_reject_unverified_stock_price_as_if_certified(self):
        ins,prices=archived()
        prices["research_price_candidates"]["9802"]["price_low_window_certified"]=True
        with self.assertRaisesRegex(ValueError,"UNVERIFIED_SOURCE_OR_IMPROPER_FORMAL_PROMOTION"):
            combine(ins,prices)

    def test_no_transformation_into_actual_alpha(self):
        ins,prices=archived()
        ins["crosschecks"]["6965"]["pass_formal_insider_quality_gate"]=True
        with self.assertRaisesRegex(ValueError,"UNVERIFIED_SOURCE_OR_IMPROPER_FORMAL_PROMOTION"):
            combine(ins,prices)


if __name__=="__main__":
    unittest.main()
