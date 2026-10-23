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
