"""Regression checks: A+ evidence triage must advance without inventing PASS."""
import copy
import unittest

from scripts.research_work_queue import build_queue, render
from tw_model_v880.evidence import GATES


class AplusQueueRepairTests(unittest.TestCase):
    def make_inputs(self):
        research=dict(model='TEST',estimate_vintage='2026-11-07T21:00:00+08:00',
                      asof_price_date='2026-11-06',model_code_sha256='a'*64,
                      target_date='2027-12-31')
        def issuer(code,upside,source_gate=None):
            stages={}
            for name in GATES:
                stage=('SOURCE_CAPTURED' if name==source_gate else
                       'REVIEW_PENDING' if name=='out_of_sample_validation' else
                       'MIRROR_CAPTURED')
                stages[name]=dict(stage=stage,decision='PENDING',formal_pass=False,
                    scope='TEST',required_evidence='TEST',invalidates_on='TEST',
                    reason='NOT YET REVIEWED')
            return dict(code=code,market='TWSE',financial_period='2026-Q2',
                        name=code,formal_Aplus=False,research_upside_pct=upside,
                        gate_stage=stages)
        progress={k:research[k] for k in ('model','estimate_vintage','asof_price_date')}
        progress['issuer_diagnostics']=[
            issuer('6206',57.6,'original_eight_quarter_statements'),
            issuer('9802',-16.4,'original_eight_quarter_statements'),
            issuer('2330',58.1),
        ]
        return progress,research

    def test_captured_originals_are_reviewed_instead_of_recollected(self):
        progress,research=self.make_inputs()
        original=copy.deepcopy(progress)
        report=build_queue(progress,research)
        issuer=next(x for x in report['issuer_jobs'] if x['code']=='6206')
        self.assertEqual(issuer['next_issuer_gate'],'original_eight_quarter_statements')
        self.assertEqual(issuer['next_issuer_action'],
                         'REVIEW_ARCHIVED_SOURCE_AND_COMPLETE_SIGNOFF')
        self.assertEqual(issuer['review_ready_original_gate_count'],1)
        self.assertEqual(report['aplus_repair']['price_qualified_research_issuers'],2)
        self.assertEqual(report['aplus_repair']['original_captured_review_pending_issuers'],1)
        self.assertEqual(report['aplus_repair']['review_ready_gate_issues'],1)
        self.assertNotIn('9802',[x['code'] for x in report['aplus_repair']['verification_priority']])
        self.assertEqual(report['certificates_issued'],0)
        self.assertEqual(progress,original)
        markdown=render(report)
        self.assertIn('核閱已封存原件',markdown)
        self.assertIn('共同策略阻礙',markdown)
        self.assertNotIn('PASS已自動核發',markdown)

    def test_share_and_turnover_summaries_do_not_count_as_reviewed_originals(self):
        progress,research=self.make_inputs()
        row=next(x for x in progress['issuer_diagnostics'] if x['code']=='2330')
        for name in ('fully_diluted_shares','tradability'):
            row['gate_stage'][name]['stage']='SOURCE_CAPTURED'
        report=build_queue(progress,research)
        job=next(x for x in report['issuer_jobs'] if x['code']=='2330')
        self.assertEqual(job['source_advanced_gate_count'],2)
        self.assertEqual(job['review_ready_original_gate_count'],0)
        self.assertEqual(job['next_issuer_action'],'VERIFY_CAPITAL_DILUTION_TERMS')
        self.assertEqual(report['aplus_repair']['source_advanced_gate_issues'],3)
        self.assertIn('補可轉債',render(report))
        self.assertEqual(report['formal_gate_decisions_changed'],0)

    def test_oos_is_shared_and_cannot_be_mistaken_for_captured_original(self):
        progress,research=self.make_inputs()
        row=progress['issuer_diagnostics'][0]
        for name in GATES:
            if name!='out_of_sample_validation':
                row['gate_stage'][name].update(
                    decision='PASS',formal_pass=True,stage='FORMAL_PASS')
        report=build_queue(progress,research)
        job=next(x for x in report['issuer_jobs'] if x['code']=='6206')
        self.assertIsNone(job['next_issuer_gate'])
        self.assertEqual(job['passed_gate_count'],12)
        self.assertEqual(job['unresolved_gate_count'],1)
        self.assertEqual(report['aplus_repair']['high_upside_gate_pending_counts']['out_of_sample_validation'],2)
        self.assertFalse(job['formal_Aplus'])
        self.assertEqual(report['formal_gate_decisions_changed'],0)


if __name__=='__main__':
    unittest.main()
