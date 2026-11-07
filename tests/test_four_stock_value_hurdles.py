import copy
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.four_stock_value_hurdles import evaluate, render


class FourStockValueHurdlesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs=json.loads((ROOT/'tw-market-data/research/four_stock_value_inputs_20261107.json').read_text(encoding='utf-8'))

    def test_four_hurdles_and_explicit_uncertainty(self):
        r=evaluate(self.inputs)
        by={s['code']:s for s in r['stocks']}
        self.assertEqual([s['code'] for s in r['stocks']], ['6285','3231','8299','3260'])
        self.assertAlmostEqual(by['3231']['eps_hurdles_2027']['upside_35pct'],18.0)
        self.assertAlmostEqual(by['6285']['eps_hurdles_2027']['upside_35pct'],15.863,places=3)
        self.assertAlmostEqual(by['8299']['eps_hurdles_2027']['upside_35pct'],253.125,places=3)
        self.assertAlmostEqual(by['3260']['eps_hurdles_2027']['upside_35pct'],50.541,places=3)
        self.assertIsNone(r['scenario_probabilities'])
        self.assertIsNone(r['expected_net_return'])
        self.assertEqual(r['formal_grade'],'NOT_CERTIFIED')
        self.assertFalse(r['reference_close_is_executable_entry'])
        self.assertTrue(all(s['forecast_2027_eps'] is None and not s['formal_Aplus_certified'] for s in r['stocks']))

    def test_after_close_disclosures_not_lookahead_signals(self):
        r=evaluate(self.inputs)
        by={s['code']:s for s in r['stocks']}
        self.assertFalse(by['8299']['eps_available_by_reference_close'])
        self.assertTrue(by['6285']['eps_available_by_reference_close'])
        for code in ('3231','8299','3260'):
            self.assertTrue(by[code]['post_close_disclosures'])
            self.assertTrue(all(not e['available_by_reference_close'] for e in by[code]['post_close_disclosures']))
        self.assertIn('不能回填',render(r))
        self.assertIn('|6285 啟碁|164.50|10.10（3季）|14|11.75|15.28|15.87|',render(r))
        self.assertIn('|8299 群聯|1500.00|325.49（3季）|8|187.50|243.75|253.13|',render(r))

    def test_invalid_inputs_fail_closed(self):
        for bad in ('pe','stock_count','missing_sources','future_income','late_event','wrong_quarter'):
            x=copy.deepcopy(self.inputs)
            if bad=='pe':x['stocks'][0]['illustrative_pe']=0
            if bad=='stock_count':x['stocks'].pop()
            if bad=='missing_sources':x['stocks'][0]['sources']=[]
            if bad=='future_income':x['stocks'][0]['eps_published_at']='2026-11-08T10:00:00+08:00'
            if bad=='late_event':x['stocks'][1]['material_events'][0]['published_at']='2026-11-09T10:00:00+08:00'
            if bad=='wrong_quarter':x['stocks'][1]['reported_quarters']=3
            with self.subTest(bad=bad),self.assertRaises(ValueError):evaluate(x)

if __name__=='__main__':unittest.main()
