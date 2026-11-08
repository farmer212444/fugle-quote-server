"""Regression: 2330/2317 share a prioritized research lane, not a certificate."""
import unittest
import copy
from scripts.research_work_queue import WATCHLIST, build_queue, render
from tw_model_v880.evidence import GATES

class DualLaneTests(unittest.TestCase):
    def test_both_priority_and_no_automatic_pass(self):
        self.assertTrue({'2330','2317'}.issubset(WATCHLIST))
        base=dict(model='TEST',estimate_vintage='2026-11-08T00:00:00+08:00',
                  asof_price_date='2026-11-06', model_code_sha256='a'*64, target_date='2027-12-31')
        def issuer(code):
            stages={g:dict(stage='MIRROR_CAPTURED',decision='PENDING',
                           formal_pass=False,scope='TEST',
                           required_evidence='TEST',invalidates_on='TEST',
                           reason='UNREVIEWED') for g in GATES}
            return dict(code=code,market='TWSE',name=code,
                        financial_period='2026-Q2',reviewed_financial_period='2026-Q2',research_upside_pct=40,
                        formal_Aplus=False,gate_stage=stages)
        progress=dict(base,issuer_diagnostics=[issuer('2317'),issuer('2330'),issuer('9999')])
        research=dict(base)
        report=build_queue(progress,research)
        jobs={r['code']:r for r in report['issuer_jobs']}
        for code in ('2317','2330'):
            self.assertTrue(jobs[code]['watchlist_focus'])
            self.assertEqual(jobs[code]['passed_gate_count'],0)
            self.assertEqual(jobs[code]['unresolved_gate_count'],13)
            self.assertFalse(jobs[code]['formal_Aplus'])
        self.assertEqual([r['code'] for r in report['issuer_jobs'][:2]],['2317','2330'])
        self.assertEqual(report['certificates_issued'],0)
        # The published dual summary must not silently label a missing
        # original archive manifest as 0/8 or upgrade a pending gate.
        focus={r['code']:r for r in report['dual_focus_status']}
        self.assertEqual(set(focus),{'2330','2317'})
        for code in ('2330','2317'):
            self.assertEqual(focus[code]['company_gates_passed'],0)
            self.assertEqual(focus[code]['company_gates_pending'],12)
            self.assertEqual(focus[code]['strategy_oos_gate_decision'],'PENDING')
            self.assertIsNone(focus[code]['original_quarter_coverage'])
            self.assertFalse(focus[code]['formal_Aplus'])
        markdown=render(report)
        self.assertIn('2330 台積電／2317 鴻海',markdown)
        self.assertIn('未核實封存覆蓋；不可視為0季',markdown)
        self.assertIn('共同策略回測',markdown)

    def test_2317_missing_full_originals_take_priority_over_turnover(self):
        base=dict(model='TEST',estimate_vintage='2026-11-08T21:30:00+08:00',
                  asof_price_date='2026-11-06',model_code_sha256='a'*64,
                  target_date='2027-12-31')
        stages={name:dict(stage='MIRROR_CAPTURED',decision='PENDING',
                          formal_pass=False,scope='TEST',required_evidence='TEST',
                          invalidates_on='TEST',reason='TEST') for name in GATES}
        stages['tradability']['stage']='SOURCE_CAPTURED'
        row=dict(code='2317',market='TWSE',name='鴻海',
                 financial_period='2026-Q2',reviewed_financial_period='2026-Q2',
                 research_upside_pct=95.0,formal_Aplus=False,gate_stage=stages)
        progress=dict(base,issuer_diagnostics=[row])
        before=copy.deepcopy(progress)
        report=build_queue(progress,dict(base))
        job=report['issuer_jobs'][0]
        self.assertEqual(job['next_issuer_gate'],'original_eight_quarter_statements')
        self.assertEqual(job['next_issuer_action'],'CAPTURE_AND_VERIFY_ORIGINAL_SOURCE')
        self.assertIsNone(job['original_quarter_coverage'])
        self.assertEqual(job['passed_gate_count'],0)
        self.assertEqual(job['unresolved_gate_count'],13)
        self.assertEqual(report['certificates_issued'],0)
        self.assertEqual(progress,before)
        self.assertIn('2317：original_eight_quarter_statements',render(report))

        # When source is already formally reviewed, resume liquidity work,
        # instead of needlessly recollecting the same original.
        row['gate_stage']['original_eight_quarter_statements'].update(
            decision='PASS',formal_pass=True,stage='FORMAL_PASS')
        checked=build_queue(progress,dict(base))['issuer_jobs'][0]
        self.assertEqual(checked['next_issuer_gate'],'tradability')
        self.assertEqual(checked['next_issuer_action'],'VERIFY_MARKET_SPREAD_EXIT_CAPACITY')
        self.assertEqual(checked['passed_gate_count'],1)
        self.assertFalse(checked['formal_Aplus'])

    def test_2317_partial_original_coverage_never_counts_as_completed(self):
        base=dict(model='TEST',estimate_vintage='2026-11-08T21:30:00+08:00',
                  asof_price_date='2026-11-06',model_code_sha256='a'*64,
                  target_date='2027-12-31')
        stages={name:dict(stage='MIRROR_CAPTURED',decision='PENDING',
                          formal_pass=False,scope='TEST',required_evidence='TEST',
                          invalidates_on='TEST',reason='TEST') for name in GATES}
        stages['tradability']['stage']='SOURCE_CAPTURED'
        stages['original_eight_quarter_statements']['stage']='SOURCE_CAPTURED'
        row=dict(code='2317',market='TWSE',name='鴻海',
                 financial_period='2026-Q2',reviewed_financial_period='2026-Q2',
                 research_upside_pct=95,formal_Aplus=False,gate_stage=stages,
                 durable_original_archive=dict(coverage=dict(
                     required_quarters=['2024-Q3','2024-Q4','2025-Q1'],
                     found_quarters=['2024-Q3'],missing_quarters=['2024-Q4','2025-Q1'],
                     full_original_pdf_content_reviewed=False)))
        job=build_queue(dict(base,issuer_diagnostics=[row]),dict(base))['issuer_jobs'][0]
        self.assertEqual(job['next_issuer_gate'],'original_eight_quarter_statements')
        self.assertEqual(job['next_issuer_action'],'CAPTURE_MISSING_QUARTER_ORIGINALS')
        self.assertEqual(job['original_quarter_coverage']['archived'],1)
        self.assertFalse(job['formal_Aplus'])


if __name__=='__main__':
    unittest.main()
