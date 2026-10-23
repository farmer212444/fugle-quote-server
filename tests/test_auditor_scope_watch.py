"""Issuer-original qualified reviewer scope: no inferred formal PASS."""
import copy
import json
from pathlib import Path
import unittest

from tw_model_v880.auditor_watch import check_scope_receipt,load_scope_watches
from tw_model_v880.credibility import build_research_priority
from test_credibility_priority import issuer

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'
RECEIPT=ROOT/'evidence/v880/auditor_scope_watch/8383.json'
INCOME=dict(code='8383',market='TPEX',period='2026-Q2',
            revenue_ytd_k=2414227,gross_profit_ytd_k=580037,
            operating_profit_ytd_k=361315)
CASH=dict(code='8383',market='TPEX',period='2026-Q2',
          operating_cashflow_ytd_k=109120)


class AuditorWatchTests(unittest.TestCase):
    def source(self):
        return json.loads(RECEIPT.read_text(encoding='utf-8'))

    def test_original_8383_mirrors_facts_but_not_certification(self):
        o=check_scope_receipt(self.source(),INCOME,CASH,'2026-10-23T22:30:00+08:00')
        self.assertEqual(o['code'],'8383')
        self.assertEqual(o['qualified_scope_pct']['quarterly_consolidated_comprehensive_income'],22.13)
        self.assertEqual(o['qualified_scope_pct']['half_year_consolidated_comprehensive_income'],16.15)
        self.assertFalse(o['formal_auditor_scope_pass'])
        self.assertFalse(o['issuer_original_pdf_bytes_hashed'])
        self.assertFalse(o['MOPS_PIT_verified'])
        self.assertEqual(o['preceding_q1_review']['period'],'2026-Q1')
        self.assertAlmostEqual(o['preceding_q1_review']['subsidiaries_unreviewed_share_of_total_comprehensive_income_pct'],7.87)

    def test_filing_period_mismatch_and_future_access_quarantined(self):
        entry=self.source()
        with self.assertRaisesRegex(ValueError,'SCOPE_WATCH_FUTURE_DATA'):
            check_scope_receipt(entry,INCOME,CASH,'2026-10-22T23:00:00+08:00')
        with self.assertRaisesRegex(ValueError,'SCOPE_WATCH_MIRROR_DIFFERENT_ISSUER'):
            check_scope_receipt(entry,dict(INCOME,code='6829'),CASH,'2026-10-23')

    def test_tampered_numeric_and_forged_certification_fail_closed(self):
        entry=self.source()
        entry['issuer_pdf_mirror_observations_ntd_thousands']['operating_cashflow_ytd_k']=999999
        with self.assertRaisesRegex(ValueError,'SCOPE_WATCH_ORIGINAL_VS_NORMALIZED'):
            check_scope_receipt(entry,INCOME,CASH,'2026-10-23')
        entry=self.source()
        entry['formal_auditor_scope_gate_pass']=True
        with self.assertRaisesRegex(ValueError,'SCOPE_WATCH_FALSE_ORIGIN_OR_CERTIFICATION'):
            check_scope_receipt(entry,INCOME,CASH,'2026-10-23')
        entry=self.source()
        entry['source_pdf_url']='https://untrusted.example/8383.pdf'
        with self.assertRaisesRegex(ValueError,'SCOPE_WATCH_UNVERIFIED_PUBLISHER_HOST'):
            check_scope_receipt(entry,INCOME,CASH,'2026-10-23')

    def test_prior_q1_original_source_identity_cannot_be_spoofed(self):
        entry=self.source()
        entry['prior_interim_review_observation']['issuer_original_source_url']='https://untrusted.example/2026Q1.pdf'
        with self.assertRaisesRegex(ValueError,'SCOPE_WATCH_PRIOR_Q1_ORIGINAL_SOURCE_INVALID'):
            check_scope_receipt(entry,INCOME,CASH,'2026-10-23')
        entry=self.source()
        entry['prior_interim_review_observation']['MOPS_PIT_verified']=True
        with self.assertRaisesRegex(ValueError,'SCOPE_WATCH_PRIOR_Q1_ORIGINAL_SOURCE_INVALID'):
            check_scope_receipt(entry,INCOME,CASH,'2026-10-23')

    def test_research_queue_shows_auditor_conclusion_not_buy_or_alpha(self):
        source=check_scope_receipt(self.source(),INCOME,CASH,'2026-10-23')
        row=issuer('8383',True,66.7)
        row['auditor_scope_watch']=source
        before=copy.deepcopy(row)
        result=build_research_priority([row])['top10_evidence_first'][0]
        self.assertTrue(result['qualified_auditor_review_needs_subsidiary_scope_reconciliation'])
        self.assertIn('ISSUER_ORIGINAL_QUALIFIED_AUDITOR_CONCLUSION_SUBSIDIARIES_UNREVIEWED',
                      result['warning_flags'])
        self.assertFalse(result['formal_Aplus'])
        self.assertEqual(result['research_decision'],'REVIEW_ONLY_NOT_BUY')
        self.assertEqual(row,before)


if __name__=='__main__':unittest.main()
