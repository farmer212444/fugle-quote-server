"""Immutable 8383 original-note working-capital subchecks; never A+ certification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tw_model_v880.working_capital_original import (
    check_working_capital_receipt,load_working_capital_watch)
from tw_model_v880.credibility import build_research_priority
from test_credibility_priority import issuer

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'
RECEIPT=ROOT/'evidence/v880/working_capital_watch/8383.json'
INCOME=dict(code='8383',market='TPEX',period='2026-Q2',revenue_ytd_k=2414227)
CASH=dict(code='8383',market='TPEX',period='2026-Q2',operating_cashflow_ytd_k=109120)


class IssuerOriginalWorkingCapitalTests(unittest.TestCase):
    def source(self):return json.loads(RECEIPT.read_text(encoding='utf-8'))

    def test_rehash_and_reconcile_cashflow_contract_assets_ar_ecl_payables(self):
        evidence=check_working_capital_receipt(self.source(),ROOT,'2026-10-24',INCOME,CASH)
        self.assertEqual(evidence['contract_assets_increase_k'],370707)
        self.assertEqual(evidence['receivables_net_increase_k'],182461)
        self.assertEqual(evidence['ar_ecl_addback_k'],5490)
        self.assertEqual(evidence['accounts_payable_increase_k'],224369)
        self.assertEqual(evidence['net_contract_assets_plus_ar_less_contract_liabilities_change_k'],545107)
        self.assertEqual(evidence['engineering_revenue_h1_k'],1011138)
        self.assertEqual(evidence['cashflow_operating_h1_k'],109120)
        self.assertTrue(evidence['three_working_capital_account_movements_reconciled'])
        self.assertFalse(evidence['formal_cash_and_working_capital_gate_pass'])
        self.assertFalse(evidence['formal_auditor_scope_gate_pass'])
        self.assertFalse(evidence['MOPS_historical_publication_PIT_verified'])

    def test_forged_certificate_and_mirror_mismatch_fail_closed(self):
        record=self.source()
        record['formal_cash_and_working_capital_gate_pass']=True
        with self.assertRaisesRegex(ValueError,'8383_WC_RECEIPT_FALSE_SCOPE_OR_CERTIFICATION'):
            check_working_capital_receipt(record,ROOT,'2026-10-24',INCOME,CASH)
        record=self.source()
        with self.assertRaisesRegex(ValueError,'8383_WC_ORIGINAL_VS_OFFICIAL_MIRROR_CONFLICT'):
            check_working_capital_receipt(record,ROOT,'2026-10-24',dict(INCOME,revenue_ytd_k=1),CASH)

    def test_ar_ecl_and_contract_and_ap_arithmetic_are_checked(self):
        modifications=[
            ('contract_assets_construction','operating_cashflow_movement_signed_k',-370706,
             '8383_WC_CONTRACT_ASSET_MISMATCH'),
            ('accounts_receivable_contract_note','operating_cashflow_movement_signed_k',-187950,
             '8383_WC_AR_MOVEMENT_NOT_RECONCILED_WITH_ECL'),
            ('accounts_payable_balance_sheet','operating_cashflow_movement_signed_k',224368,
             '8383_WC_ACCOUNTS_PAYABLE_MISMATCH')]
        for field,key,value,expected in modifications:
            with self.subTest(field=field):
                record=self.source()
                record[field][key]=value
                with self.assertRaisesRegex(ValueError,expected):
                    check_working_capital_receipt(record,ROOT,'2026-10-24',INCOME,CASH)

    def test_missing_source_and_future_receipt_do_not_claim_pass(self):
        with self.assertRaisesRegex(ValueError,'8383_WC_READ_DATE_NOT_VISIBLE'):
            check_working_capital_receipt(self.source(),ROOT,'2026-10-23',INCOME,CASH)
        record=self.source()
        record['original_issuer_pdf_sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'8383_WC_ORIGINAL_PATH_CONFLICT'):
            check_working_capital_receipt(record,ROOT,'2026-10-24',INCOME,CASH)
        earlier,errors=load_working_capital_watch(ROOT,'2026-10-23',
            {('TPEX','8383'):{'2026-Q2':INCOME}},
            {('TPEX','8383'):{'2026-Q2':CASH}})
        self.assertEqual(earlier,{})
        self.assertEqual(errors,[])

    def test_ranking_unchanged_and_no_promotion_to_formal_approval(self):
        entry=check_working_capital_receipt(self.source(),ROOT,'2026-10-24',INCOME,CASH)
        row=issuer('8383',True,66.7)
        row['working_capital_original_subcheck']=entry
        before=copy.deepcopy(row)
        r=build_research_priority([row])['top10_evidence_first'][0]
        self.assertTrue(r['original_working_capital_three_line_tieout_completed'])
        self.assertTrue(r['original_working_capital_subcheck_is_not_formal_gate'])
        self.assertEqual(r['base_upside_pct'],66.7)
        self.assertFalse(r['formal_Aplus'])
        self.assertEqual(row,before)


if __name__=='__main__':unittest.main()
