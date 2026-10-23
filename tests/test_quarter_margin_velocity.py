"""Quarterly gross-margin compression must be descriptive and source-bound."""
import copy
import unittest
from tw_model_v880.margin_velocity import recent_quarter_gm_velocity,standalone_gm
from tw_model_v880.credibility import build_research_priority
from test_credibility_priority import issuer


class QuarterMarginVelocityTests(unittest.TestCase):
    def test_8383_reported_h1_q1_to_q2_margin_deceleration(self):
        h={'2026-Q1':dict(revenue_ytd_k=1_005_026,gross_profit_ytd_k=263_048),
           '2026-Q2':dict(revenue_ytd_k=2_414_227,gross_profit_ytd_k=580_037)}
        v=recent_quarter_gm_velocity(h,'2026-Q2')
        expected_q1=100*263_048/1_005_026
        expected_q2=100*(580_037-263_048)/(2_414_227-1_005_026)
        self.assertAlmostEqual(v['previous_standalone_gm_pct'],expected_q1)
        self.assertAlmostEqual(v['current_standalone_gm_pct'],expected_q2)
        self.assertLess(v['recent_standalone_vs_previous_gm_delta_pp'],-3.0)
        self.assertFalse(v['original_issuer_notes_full_reviewed'])
        self.assertTrue(v['not_a_2027_earnings_revision'])

    def test_missing_or_inconsistent_quarter_does_not_fabricate(self):
        h={'2026-Q2':dict(revenue_ytd_k=1000,gross_profit_ytd_k=200)}
        self.assertEqual(recent_quarter_gm_velocity(h,'2026-Q2')['status'],
                         'MISSING_OR_INCONSISTENT_CONSECUTIVE_QUARTER_YTD_INPUTS')
        self.assertEqual(recent_quarter_gm_velocity(h,'2026-Q1')['status'],
                         'IN_YEAR_PREVIOUS_STANDALONE_QUARTER_UNAVAILABLE')
        h['2026-Q1']=dict(revenue_ytd_k=1200,gross_profit_ytd_k=100)
        self.assertIsNone(standalone_gm(h,2026,2))

    def test_triage_warning_only_no_revaluation(self):
        a=issuer('8383',True,66.7)
        a['margin_bridge']=dict(quarter_margin_velocity={
            'current_standalone_gm_pct':22.49,
            'previous_standalone_gm_pct':26.17,
            'recent_standalone_vs_previous_gm_delta_pp':-3.68})
        before=copy.deepcopy(a)
        r=build_research_priority([a])['top10_evidence_first'][0]
        self.assertTrue(r['latest_standalone_quarter_margin_compression_warning'])
        self.assertAlmostEqual(r['latest_quarter_gm_qoq_change_pp'],-3.68)
        self.assertFalse(r['quarterly_margin_warning_changes_base_or_rank'])
        self.assertFalse(r['formal_Aplus'])
        self.assertAlmostEqual(r['base_upside_pct'],66.7)
        self.assertEqual(a,before)

    def test_decline_below_threshold_is_not_flag(self):
        a=issuer('6206',True,41)
        a['margin_bridge']=dict(quarter_margin_velocity={
            'current_standalone_gm_pct':45.4,
            'previous_standalone_gm_pct':45.5,
            'recent_standalone_vs_previous_gm_delta_pp':-.1})
        r=build_research_priority([a])['top10_evidence_first'][0]
        self.assertFalse(r['latest_standalone_quarter_margin_compression_warning'])


if __name__=='__main__':unittest.main()
