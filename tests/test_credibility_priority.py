"""Credibility triage must never be mislabeled as a probability or A+."""
import copy
import unittest

from tw_model_v880.credibility import build_research_priority


def issuer(code, source=True, upside=100., offering=False, cb=False,
           block=False, ocf=100., pending=None):
    return dict(code=code,name='TEST_'+code,market='TEST',
        rankable=True,reference_close=100.,original_current_issuer_numeric_checked=source,
        base=dict(price_upside_pct=upside,target_price=100*(1+upside/100),eps=10.,pe=20.),
        bear=dict(target_price=85.),
        equity_offering_overlay=({'status':'ANNOUNCED_UNISSUED_DILUTION_SCENARIO_ONLY'}
                                 if offering else None),
        share_bridge=dict(unresolved_terms=['CB'] if cb else [],missing_legal_conversion_inputs=[]),
        liquidity=dict(ocf_k=ocf),pe_bridge=dict(exact_matched_peer_review_complete=False),
        revenue_bridge=dict(assumed_annual_growth=.25),
        certification=dict(gates_pending=pending if pending is not None else ['forecast_bridge']),
        recommendation_blocked=block,formal_Aplus=False,company_forecast_confirmed=False)


class EvidenceFirstTests(unittest.TestCase):
    def test_original_source_not_automatically_winner_or_Aplus(self):
        rows=[issuer('BULK',False,145),issuer('ORIG',True,65)]
        old=copy.deepcopy(rows)
        p=build_research_priority(rows)
        self.assertEqual(p['top10_evidence_first'][0]['code'],'ORIG')
        self.assertFalse(p['top10_evidence_first'][0]['all_eight_quarters_and_notes_verified'])
        self.assertFalse(p['top10_evidence_first'][0]['formal_Aplus'])
        self.assertIsNone(p['benchmark_beat_rate'])
        self.assertEqual(rows,old)

    def test_open_offering_never_changes_base_or_uses_comparable_future_return(self):
        a=issuer('8390',True,110,offering=True)
        b=issuer('5439',True,90)
        p=build_research_priority([a,b])
        self.assertEqual([x['code'] for x in p['top10_evidence_first']],['5439','8390'])
        self.assertAlmostEqual(p['top10_evidence_first'][1]['base_upside_pct'],110)
        self.assertTrue(p['top10_evidence_first'][1]['pending_offering'])

    def test_cb_pending_and_negative_cash_dont_become_false_formal_failure(self):
        a=issuer('CB',True,100,cb=True,ocf=-100)
        b=issuer('NO_CB',True,30,cb=False)
        p=build_research_priority([a,b])
        self.assertEqual(p['top10_evidence_first'][0]['code'],'NO_CB')
        self.assertIn('NEGATIVE_OCF_REQUIRES_WORKING_CAPITAL_BRIDGE_NOT_AUTOMATIC_FAIL',
                      p['top10_evidence_first'][1]['warning_flags'])
        self.assertEqual(p['top10_evidence_first'][1]['research_decision'],'REVIEW_ONLY_NOT_BUY')

    def test_governance_and_insufficient_upside_not_recommended(self):
        p=build_research_priority([issuer('BLOCKED',True,300,block=True),
                                   issuer('LOW',True,20),
                                   issuer('OK',False,35)])
        self.assertEqual(p['eligible_count'],1)
        self.assertEqual(p['blocked_governance_count'],1)
        self.assertEqual(p['top10_evidence_first'][0]['code'],'OK')

    def test_20pct_eps_pe_stress_is_exact_sensitivity(self):
        p=build_research_priority([issuer('A',True,100)])
        r=p['top10_evidence_first'][0]
        self.assertAlmostEqual(r['eps_pe_each_minus20_upside_pct'],28.)

    def test_material_ytd_nonoperating_and_eps_stepup_flags_no_rank_mutation(self):
        bridge=issuer('8383',True,66.7)
        bridge['nonoperating_bridge']=dict(
            reported_ytd_abs_gap_share_pretax_pct=100*96889/458204,
            component_assumptions_certified=False)
        bridge['eps_bridge_reference']=dict(
            linear_annualized_ytd_parent_eps_at_model_denominator=5.32,
            target_eps_vs_ytd_linear_annualized_pct=100*(7.58/5.32-1),
            original_operating_bridge_certified=False)
        stable=issuer('6206',True,40.9)
        stable['nonoperating_bridge']=dict(
            reported_ytd_abs_gap_share_pretax_pct=100*31000/1037000,
            component_assumptions_certified=False)
        stable['eps_bridge_reference']=dict(
            linear_annualized_ytd_parent_eps_at_model_denominator=11.86,
            target_eps_vs_ytd_linear_annualized_pct=100*(11.57/11.86-1),
            original_operating_bridge_certified=False)
        originals=copy.deepcopy([bridge,stable])
        out=build_research_priority([bridge,stable])
        vals={x['code']:x for x in out['top10_evidence_first']}
        self.assertTrue(vals['8383']['reported_ytd_material_nonoperating_gap'])
        self.assertTrue(vals['8383']['requires_2027_eps_stepup_bridge'])
        self.assertFalse(vals['6206']['reported_ytd_material_nonoperating_gap'])
        self.assertFalse(vals['6206']['requires_2027_eps_stepup_bridge'])
        self.assertTrue(vals['8383']['earnings_quality_flags_do_not_change_base_or_priority'])
        self.assertEqual([bridge,stable],originals)
        self.assertEqual([x['code'] for x in out['top10_evidence_first']],['8383','6206'])

    def test_extreme_nonop_and_near_zero_eps_denominator_remain_descriptive(self):
        row=issuer('4746',True,37.2)
        row['nonoperating_bridge']=dict(
            reported_ytd_abs_gap_share_pretax_pct=857.8,
            component_assumptions_certified=False)
        row['eps_bridge_reference']=dict(
            linear_annualized_ytd_parent_eps_at_model_denominator=.07,
            target_eps_vs_ytd_linear_annualized_pct=100*(4.069/.07-1),
            original_operating_bridge_certified=False)
        before=copy.deepcopy(row)
        q=build_research_priority([row])
        a=q['top10_evidence_first'][0]
        self.assertTrue(a['eps_runrate_near_zero_denominator'])
        self.assertTrue(a['reported_ytd_nonoperating_gap_exceeds_pretax'])
        self.assertAlmostEqual(a['target_eps_minus_ytd_annualized_reference_ntd_per_share'],3.93)
        self.assertIn('YTD_NONOPERATING_GAP_EXCEEDS_ABSOLUTE_PRETAX_PROFIT',a['warning_flags'])
        self.assertIn('EPS_YTD_RUN_RATE_BELOW_0_5_RATIO_DENOMINATOR_FRAGILE',a['warning_flags'])
        self.assertFalse(a['formal_Aplus'])
        self.assertEqual(row,before)

    def test_normal_profit_runrate_does_not_gain_fragility_flag(self):
        row=issuer('8383',True,67)
        row['nonoperating_bridge']=dict(reported_ytd_abs_gap_share_pretax_pct=21.1)
        row['eps_bridge_reference']=dict(linear_annualized_ytd_parent_eps_at_model_denominator=5.27)
        a=build_research_priority([row])['top10_evidence_first'][0]
        self.assertTrue(a['reported_ytd_material_nonoperating_gap'])
        self.assertFalse(a['eps_runrate_near_zero_denominator'])
        self.assertFalse(a['reported_ytd_nonoperating_gap_exceeds_pretax'])

    def test_no_pretax_or_profit_runrate_does_not_fabricate_flag(self):
        base=issuer('A',True,90)
        x=build_research_priority([base])['top10_evidence_first'][0]
        self.assertIsNone(x['reported_ytd_abs_nonoperating_gap_share_pretax_pct'])
        self.assertIsNone(x['target_eps_vs_unseasonalized_ytd_run_rate_pct'])
        self.assertFalse(x['reported_ytd_material_nonoperating_gap'])
        self.assertFalse(x['requires_2027_eps_stepup_bridge'])

    def test_latest_month_revenue_reversal_is_warning_not_rank_or_exit(self):
        down=issuer('6143',True,74)
        down['revenue_bridge']['trend_inputs']=dict(
            latest_month_yoy=-.2688,monthly_ytd_yoy=.0612)
        growth=issuer('8383',True,67)
        growth['revenue_bridge']['trend_inputs']=dict(
            latest_month_yoy=.8365,monthly_ytd_yoy=.6295)
        old=[copy.deepcopy(down),copy.deepcopy(growth)]
        results=build_research_priority([down,growth])
        by_code={r['code']:r for r in results['top10_evidence_first']}
        self.assertTrue(by_code['6143']['latest_month_reversal_warning'])
        self.assertFalse(by_code['8383']['latest_month_reversal_warning'])
        self.assertIn('LATEST_MONTH_REVENUE_FELL_AT_LEAST_10PCT_YOY_WHILE_YTD_POSITIVE',
                      by_code['6143']['warning_flags'])
        self.assertFalse(by_code['6143']['reversal_warning_changes_base_eps_or_pe'])
        self.assertFalse(by_code['6143']['one_month_reversal_is_certified_trend'])
        self.assertEqual([down,growth],old)
        self.assertEqual([x['code'] for x in results['top10_evidence_first']],['6143','8383'])

    def test_missing_month_revenue_does_not_imply_positive_or_negative_trend(self):
        row=issuer('A',True,35)
        r=build_research_priority([row])['top10_evidence_first'][0]
        self.assertIsNone(r['latest_month_revenue_yoy_pct'])
        self.assertFalse(r['latest_month_reversal_warning'])

    def test_short_horizon_error_reference_does_not_rank_stock(self):
        rows=[issuer('ONE',True,80),issuer('TWO',True,100)]
        template={'holdout_error_tail':dict(p90_absolute_pct_error=22.094,
            groups={'HIGH_GROWTH_AT_LEAST_20PCT':dict(p90_absolute_pct_error=29.618)})}
        a=build_research_priority(rows,template)
        template['holdout_error_tail']['p90_absolute_pct_error']=60.
        b=build_research_priority(rows,template)
        self.assertEqual([x['code'] for x in a['top10_evidence_first']],
                         [x['code'] for x in b['top10_evidence_first']])
        self.assertFalse(a['accounting_error_reference']['used_to_modify_eps_or_pe'])
        self.assertFalse(a['realized_return_accuracy_calibrated'])


if __name__=='__main__':unittest.main()
