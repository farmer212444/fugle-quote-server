"""6206 original IR stock build source: file hash, MOPS tieout and fail-closed gate."""
import copy
import json
from pathlib import Path
import unittest

from tw_model_v880.inventory_original import check_6206_inventory_original,load_6206_inventory_watch
from tw_model_v880.credibility import build_research_priority
from test_credibility_priority import issuer

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'
SOURCE=ROOT/'evidence/v880/inventory_original_watch/6206.json'


def normalized_income_rows():
    out={}
    for p in ('2025-Q1','2025-Q2','2026-Q1','2026-Q2'):
        path=ROOT/'fundamentals'/p/'TWSE_income.json'
        j=json.loads(path.read_text(encoding='utf-8'))
        out[p]=next(x for x in j['rows'] if x['code']=='6206')
    return out


class FlytechIRInventoryTests(unittest.TestCase):
    def source(self):
        return json.loads(SOURCE.read_text(encoding='utf-8'))

    def test_original_6206_sha_and_mops_quarterly_sales_reconcile(self):
        r=check_6206_inventory_original(self.source(),ROOT,'2026-10-24',normalized_income_rows())
        self.assertAlmostEqual(r['inventory_yoy_pct'],100*(1510/767-1))
        self.assertGreater(r['inventory_yoy_minus_revenue_yoy_pp'],50)
        self.assertEqual(r['inventory_days_yoy_delta'],34)
        self.assertEqual(r['inventory_days_qoq_delta'],-3)
        self.assertEqual(r['receivable_days_yoy_delta'],-11)
        self.assertTrue(r['inventory_growth_exceeds_revenue_by_30pp'])
        self.assertFalse(r['cash_quality_gate_pass'])
        self.assertFalse(r['inventory_impairment_or_obsolescence_inferred'])
        self.assertFalse(r['MOPS_PIT_original_presentation_verified'])

    def test_wrong_original_sha_and_premature_asof_rejected(self):
        j=self.source()
        with self.assertRaisesRegex(ValueError,'6206_IR_OBSERVATION_IS_FROM_FUTURE'):
            check_6206_inventory_original(j,ROOT,'2026-10-23',normalized_income_rows())
        j['original_issuer_pdf_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'6206_INVENTORY_IR_SOURCE_OR_CERTIFICATION_MISMATCH'):
            check_6206_inventory_original(j,ROOT,'2026-10-24',normalized_income_rows())

    def test_forged_gate_and_mops_revenue_mismatch_rejected(self):
        j=self.source()
        j['formal_cash_working_capital_gate_pass']=True
        with self.assertRaisesRegex(ValueError,'6206_INVENTORY_IR_SOURCE_OR_CERTIFICATION_MISMATCH'):
            check_6206_inventory_original(j,ROOT,'2026-10-24',normalized_income_rows())
        j=self.source()
        altered=copy.deepcopy(normalized_income_rows())
        altered['2026-Q2']['revenue_ytd_k']+=5000
        with self.assertRaisesRegex(ValueError,'6206_IR_PUBLISHED_REVENUE_AND_MOPS_MIRROR_CONFLICT'):
            check_6206_inventory_original(j,ROOT,'2026-10-24',altered)

    def test_loader_skips_future_receipts_and_succeeds_now(self):
        h={('TWSE','6206'):normalized_income_rows()}
        early,errors=load_6206_inventory_watch(ROOT,'2026-10-23',h)
        self.assertEqual(early,{})
        self.assertEqual(errors,[])
        now,errors=load_6206_inventory_watch(ROOT,'2026-10-24',h)
        self.assertEqual(errors,[])
        self.assertIn('6206',now)

    def test_research_carries_observation_without_changing_rank_or_price(self):
        original=check_6206_inventory_original(self.source(),ROOT,'2026-10-24',normalized_income_rows())
        a=issuer('6206',True,40.9,ocf=-97618)
        a['inventory_original_subcheck']=original
        b=issuer('8383',True,66.7,ocf=109120)
        copied=copy.deepcopy([a,b])
        out=build_research_priority([a,b])
        v={x['code']:x for x in out['top10_evidence_first']}
        self.assertTrue(v['6206']['original_ir_inventory_turnover_partial_review'])
        self.assertTrue(v['6206']['inventory_source_does_not_certify_working_capital'])
        self.assertIn('6206_INVENTORY_YOY_GROWTH_EXCEEDS_QUARTERLY_REVENUE_YOY_BY_GE30PP',
                      v['6206']['warning_flags'])
        self.assertEqual(v['6206']['base_upside_pct'],40.9)
        self.assertFalse(v['6206']['formal_Aplus'])
        self.assertEqual([a,b],copied)


if __name__=='__main__':
    unittest.main()
