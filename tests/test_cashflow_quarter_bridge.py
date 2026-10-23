"""OCF quarter bridge must distinguish H1 cumulative and standalone Q2."""
import copy
import unittest
from tw_model_v880.cashflow_velocity import operating_cashflow_quarter_bridge
from tw_model_v880.credibility import build_research_priority
from test_credibility_priority import issuer


def series(q1,q2):
    return {'2026-Q1':dict(operating_cashflow_ytd_k=q1),
            '2026-Q2':dict(operating_cashflow_ytd_k=q2)}


class OperatingCashflowQuarterTests(unittest.TestCase):
    def test_6206_h1_negative_but_q2_positive(self):
        rows=series(-197541,-97618)
        before=copy.deepcopy(rows)
        out=operating_cashflow_quarter_bridge(rows,'2026-Q2',-97618)
        self.assertEqual(out['latest_standalone_ocf_k'],99923)
        self.assertTrue(out['changed_sign_after_q1'])
        self.assertTrue(out['h1_or_current_ytd_ocf_still_negative'])
        self.assertTrue(out['latest_standalone_ocf_positive'])
        self.assertFalse(out['working_capital_component_bridge_certified'])
        self.assertEqual(rows,before)

    def test_8383_h1_positive_after_q2_ocf_recovery(self):
        out=operating_cashflow_quarter_bridge(series(-28159,109120),'2026-Q2',109120)
        self.assertEqual(out['latest_standalone_ocf_k'],137279)
        self.assertTrue(out['changed_sign_after_q1'])
        self.assertFalse(out['h1_or_current_ytd_ocf_still_negative'])

    def test_source_mismatch_fails_closed(self):
        out=operating_cashflow_quarter_bridge(series(-197541,-97618),'2026-Q2',-20000)
        self.assertEqual(out['status'],'EFFECTIVE_CASHFLOW_SOURCE_MISMATCH_RECONCILIATION_REQUIRED')
        self.assertIsNone(out['latest_standalone_ocf_k'])
        self.assertFalse(out['original_cash_notes_reconciled'])

    def test_missing_prior_quarter_does_not_compute(self):
        out=operating_cashflow_quarter_bridge({'2026-Q2':dict(operating_cashflow_ytd_k=10)},'2026-Q2')
        self.assertEqual(out['status'],'MISSING_OFFICIAL_YTD_CASHFLOW')
        self.assertIsNone(out['latest_standalone_ocf_k'])

    def test_priority_preserves_ocf_negative_and_unchanged_base(self):
        a=issuer('6206',True,40.9,ocf=-97618)
        a['liquidity']['operating_cashflow_quarter_bridge']=operating_cashflow_quarter_bridge(
            series(-197541,-97618),'2026-Q2',-97618)
        b=issuer('8383',True,66.7,ocf=109120)
        b['liquidity']['operating_cashflow_quarter_bridge']=operating_cashflow_quarter_bridge(
            series(-28159,109120),'2026-Q2',109120)
        original=copy.deepcopy([a,b])
        out=build_research_priority([a,b])
        m={x['code']:x for x in out['top10_evidence_first']}
        self.assertTrue(m['6206']['latest_q2_standalone_ocf_recovered_after_q1'])
        self.assertIn('NEGATIVE_OCF_REQUIRES_WORKING_CAPITAL_BRIDGE_NOT_AUTOMATIC_FAIL',m['6206']['warning_flags'])
        self.assertTrue(m['6206']['quarterly_ocf_observation_not_certified'])
        self.assertTrue(m['8383']['latest_q2_standalone_ocf_recovered_after_q1'])
        self.assertEqual([a,b],original)
        self.assertEqual([x['code'] for x in out['top10_evidence_first']],['8383','6206'])
        self.assertFalse(m['6206']['formal_Aplus'])


if __name__=='__main__':unittest.main()
