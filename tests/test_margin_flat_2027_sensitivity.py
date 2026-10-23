"""2027 quarter-GM sensitivity is mechanical and never changes Base valuation."""
import copy
import unittest

from tw_model_v880.math import operating_scenario
from tw_model_v880.credibility import (
    flat_recent_quarter_gm_sensitivity, build_research_priority)
from test_credibility_priority import issuer


class LatestGMFlatCounterfactualTests(unittest.TestCase):
    def financial_case(self):
        return operating_scenario(
            20_000_000,.25,.20,250_000,.20,.9,100_000_000,15)

    def test_matches_independent_operating_scenario_when_only_gm_changes(self):
        base=self.financial_case()
        expected=operating_scenario(
            20_000_000,.22,.20,250_000,.20,.9,100_000_000,15)
        unchanged=copy.deepcopy(base)
        o=flat_recent_quarter_gm_sensitivity(base,22.,100.)
        self.assertEqual(o['status'],'MECHANICAL_2027_LAST_STANDALONE_GM_FLAT_ONLY')
        self.assertAlmostEqual(o['difference_from_base_gm_pp'],-3.)
        self.assertAlmostEqual(o['eps_change_from_base'],expected['eps']-base['eps'])
        self.assertAlmostEqual(o['scenario_eps'],expected['eps'])
        self.assertAlmostEqual(o['scenario_target_price'],expected['target_price'])
        self.assertAlmostEqual(o['scenario_price_upside_pct'],100*(expected['target_price']/100-1))
        self.assertFalse(o['not_a_2027_earnings_revision'] if 'not_a_2027_earnings_revision' in o else False)
        self.assertTrue(o['not_a_margin_2027_forecast'])
        self.assertEqual(base,unchanged)

    def test_non_pe_nav_not_sensitized(self):
        base=self.financial_case()
        base['valuation_method']='NAV'
        self.assertEqual(flat_recent_quarter_gm_sensitivity(base,20.,100.)['status'],
                         'NOT_COMPARABLE_INCOMPLETE_OR_NON_PE_BASE')

    def test_missing_margin_or_base_fields_fail_closed(self):
        base=self.financial_case()
        self.assertEqual(flat_recent_quarter_gm_sensitivity(base,None,100.)['status'],
                         'NOT_COMPARABLE_INCOMPLETE_OR_NON_PE_BASE')
        del base['parent_fraction']
        self.assertEqual(flat_recent_quarter_gm_sensitivity(base,20.,100.)['status'],
                         'NOT_COMPARABLE_INCOMPLETE_OR_NON_PE_BASE')

    def test_negative_eps_never_returns_negative_pe_price(self):
        base=self.financial_case()
        o=flat_recent_quarter_gm_sensitivity(base,0.,100.)
        self.assertEqual(o['status'],'SCENARIO_NONPOSITIVE_EPS_PE_VALUE_UNAVAILABLE')
        self.assertLessEqual(o['scenario_eps'],0)
        self.assertIsNone(o['scenario_target_price'])

    def test_rank_order_and_base_return_unchanged(self):
        a=issuer('8383',True,66.7)
        b=issuer('6206',True,40.9)
        base=self.financial_case()
        a['base']=base
        a['margin_bridge']=dict(quarter_margin_velocity=dict(
            current_standalone_gm_pct=20.,
            previous_standalone_gm_pct=26.,
            recent_standalone_vs_previous_gm_delta_pp=-6.))
        b['base']=copy.deepcopy(base)
        b['base']['price_upside_pct']=40.9
        b['base']['eps']=base['eps']*1.409/(base['target_price']/100)
        b['base']['target_price']=b['base']['eps']*b['base']['pe']
        b['margin_bridge']=dict(quarter_margin_velocity=dict(current_standalone_gm_pct=25.))
        before=copy.deepcopy([a,b])
        report=build_research_priority([a,b])
        self.assertEqual([x['code'] for x in report['top10_evidence_first']],['8383','6206'])
        o=report['top10_evidence_first'][0]
        self.assertTrue(o['mechanical_margin_sensitivity_changes_base_or_rank'] is False)
        self.assertIn('2027_BASE_GM_GE3PP_ABOVE_LATEST_STANDALONE_QUARTER',o['warning_flags'])
        self.assertFalse(o['formal_Aplus'])
        self.assertEqual([a,b],before)


if __name__ == '__main__':
    unittest.main()
