"""6206 observed IR working capital proxy versus *separate* MOPS Q2 OCF.

Never treat quarter-end balance-sheet deltas as cashflow statement movements.
"""
import copy
import json
from pathlib import Path
import unittest

from tw_model_v880.inventory_original import (
    check_6206_inventory_original,load_6206_inventory_watch)
from test_v8b2_flytech_inventory import normalized_income_rows, ROOT, SOURCE


def official_cash():
    result={}
    for period in ('2026-Q1','2026-Q2'):
        data=json.loads((ROOT/'fundamentals'/period/'TWSE_cashflow.json').read_text(encoding='utf-8'))
        result[period]=next(x for x in data['rows'] if x['code']=='6206')
    return result


class FlytechQuarterWorkingCapitalTests(unittest.TestCase):
    def record(self):
        return json.loads(SOURCE.read_text(encoding='utf-8'))

    def test_ir_balances_are_not_cash_flow_movements(self):
        r=check_6206_inventory_original(
            self.record(),ROOT,'2026-10-24',normalized_income_rows(),official_cash())
        self.assertEqual(r['ir_q1_inventory_receivables_minus_payables_m'],1884)
        self.assertEqual(r['ir_q2_inventory_receivables_minus_payables_m'],2468)
        self.assertEqual(r['ir_q2_quarter_balance_proxy_capital_increase_m'],584)
        self.assertAlmostEqual(
            r['ir_q2_quarter_balance_proxy_as_pct_of_quarter_sales'],
            100*584/1881.598,places=3)
        cf=r['cashflow_quarter_mops_evidence']
        self.assertEqual(cf['q1_ytd_ocf_k'],-197541)
        self.assertEqual(cf['q2_standalone_ocf_k'],99923)
        self.assertEqual(cf['h1_ytd_ocf_k'],-97618)
        self.assertTrue(cf['q2_ocf_positive'])
        self.assertTrue(cf['half_year_ocf_still_negative'])
        self.assertTrue(r['not_cash_flow_statement_reconciliation'])
        self.assertFalse(r['cash_quality_gate_pass'])
        self.assertFalse(r['inventory_impairment_or_obsolescence_inferred'])

    def test_wrong_mops_cashflow_period_code_type_rejected(self):
        original=official_cash()
        for period,field,value in (
            ('2026-Q2','period','2026-Q1'),
            ('2026-Q1','code','8383'),
            ('2026-Q2','operating_cashflow_ytd_k',float('nan')),
            ('2026-Q1','operating_cashflow_ytd_k',True),
        ):
            with self.subTest(period=period,field=field):
                rows=copy.deepcopy(original)
                rows[period][field]=value
                with self.assertRaisesRegex(ValueError,'6206_Q2_OCF_MOPS_MIRROR_UNAVAILABLE'):
                    check_6206_inventory_original(
                        self.record(),ROOT,'2026-10-24',normalized_income_rows(),rows)

    def test_no_cashflow_does_not_fake_q2_ocf(self):
        r=check_6206_inventory_original(
            self.record(),ROOT,'2026-10-24',normalized_income_rows())
        cf=r['cashflow_quarter_mops_evidence']
        self.assertFalse(cf['quarterly_ocf_reconciled'])
        self.assertIsNone(cf['q2_standalone_ocf_k'])
        self.assertEqual(cf['status'],'OFFICIAL_CASHFLOW_NOT_PROVIDED_NO_CONCLUSION')

    def test_loader_uses_official_cash_current_vintage(self):
        h={('TWSE','6206'):normalized_income_rows()}
        c={('TWSE','6206'):official_cash()}
        found,errors=load_6206_inventory_watch(ROOT,'2026-10-24',h,c)
        self.assertEqual(errors,[])
        self.assertEqual(found['6206']['cashflow_quarter_mops_evidence']['q2_standalone_ocf_k'],99923)
        prior,errors=load_6206_inventory_watch(ROOT,'2026-10-23',h,c)
        self.assertEqual(errors,[])
        self.assertEqual(prior,{})


if __name__=='__main__':
    unittest.main()
