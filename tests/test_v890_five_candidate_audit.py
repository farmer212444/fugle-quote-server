import datetime as dt
import math
import unittest

from scripts.v890_five_candidate_audit import (
    FOCUS, scenario_stress, equity_watch, flags_and_next,
    validate_vintage, markdown
)

class FiveCandidateAuditTests(unittest.TestCase):
    def test_explicit_dual_stress_and_CB_reset_is_incremental(self):
        share=dict(base_shares=100,conversion_price_down_10pct_full_conversion_shares=105)
        result=scenario_stress(10,16,100,share,False)
        self.assertAlmostEqual(result["base"]["target_price"],160)
        self.assertAlmostEqual(result["double10"]["target_price"],129.6)
        self.assertAlmostEqual(result["double20"]["target_price"],102.4)
        self.assertAlmostEqual(result["double30"]["target_price"],78.4)
        self.assertAlmostEqual(result["double10_plus_CB_reset_sensitivity"]["target_price"],123.43,places=2)
        self.assertEqual(result["double10_plus_CB_reset_sensitivity"]["additional_shares_over_baseline"],5)
    def test_no_double_count_when_CB_full_dilution_already_in_share_base(self):
        shares=dict(base_shares=140,conversion_price_down_10pct_full_conversion_shares=142)
        out=scenario_stress(8.52,20.45,84.60,shares,False)
        self.assertLess(out["double10_plus_CB_reset_sensitivity"]["target_price"],out["double10"]["target_price"])
        self.assertGreater(out["double10_plus_CB_reset_sensitivity"]["target_price"],out["double20"]["target_price"])
        with self.assertRaisesRegex(ValueError,"LESS_THAN_BASE"):
            scenario_stress(10,15,70,dict(base_shares=100,
                conversion_price_down_10pct_full_conversion_shares=90),False)
    def test_cash_raise_hypothetical_never_promotes_formal(self):
        old=96_116_128
        doc=dict(issuer_reviews=[dict(code="8390",equity_issuance=dict(
            originally_scheduled_effective_date="2026-10-21",
            issuance_completed=False,regulator_effectiveness_confirmed=False,
            capital_master_shares_asof_2026_10_06=old,
            filed_new_shares_from_nominal=8_000_000,
            board_max_new_shares=10_000_000,
            filed_amount_source="https://example.com/filing",
            board_source="https://example.com/board"))])
        r=equity_watch(doc,dict(base_shares=old),13.83,182.88,89.7,dt.date(2026,10,20))
        self.assertEqual(r["status"],"SCENARIO_ONLY_NOT_EFFECTIVE_OR_COMPLETED")
        self.assertLess(r["scenarios"]["filed_8m_unconfirmed"]["proforma_price_fixed_profit"],182.88)
        self.assertFalse(r["formal_certified"])
        future=equity_watch(doc,dict(base_shares=old),13.83,182.88,89.7,dt.date(2026,10,22))
        self.assertEqual(future["status"],"SCHEDULED_EFFECTIVE_DATE_ELAPSED_REFRESH_OFFICIAL_STATUS")
        self.assertNotIn("scenarios",future)
    def test_negative_ocf_is_risk_not_auto_sell(self):
        r=flags_and_next("5388",dict(flags=[]),
          dict(share_bridge=dict(bonds=[dict(code="53887",put_date="20261206",
               maturity="20281206",current_terms_verified=False)])),
          dict(cash=dict(ocf_k=-3461479)),
          dict(growth_decelerated_over_20pp=True))
        self.assertTrue(any(x.startswith("NEGATIVE_OCF_IS_CYCLE") for x in r))
        self.assertIn("CB_PUT_REDEMPTION_WINDOW_WITHIN_2026",r)
        self.assertIn("Q3_REVENUE_YOY_GROWTH_DECELERATED_OVER_20PP",r)
        self.assertIn("GROSS_MARGIN_RECOVERY_CAUSAL_DRIVER_UNVERIFIED",r)
    def test_mixed_research_vintages_rejected(self):
        research=dict(estimate_vintage="2026-10-20T05:40:30+08:00",asof_price_date="2026-10-16",
          financial_last_quarter="2026-Q2",revenue_month="2026-09",formal_Aplus_count=0)
        financial=dict(estimate_vintage="2026-10-19T05:40:30+08:00",asof_price_date="2026-10-16",
          financial_last_quarter="2026-Q2",formal_Aplus_count=0)
        with self.assertRaisesRegex(ValueError,"VINTAGE_MISMATCH"):
            validate_vintage(research,{"cash":financial})
    def test_total_focus_unique(self):
        self.assertEqual(len(FOCUS),5)
        self.assertEqual(len(set(FOCUS)),5)
if __name__=="__main__":unittest.main()
