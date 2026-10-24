"""Regression and printable 0056 top10 on exact current 2027 archived model vintage."""
import copy
import json
from pathlib import Path
import unittest

from scripts.v8b4_0056_forward_top10 import load_inputs,filter_top10

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'


class Yuanta0056ForwardTop10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holdings,cls.compact,cls.full=load_inputs(ROOT)

    def test_0056_full_constituents_join_no_outside_issuers(self):
        result=filter_top10(self.holdings,self.full)
        self.assertEqual(result['holdings_count'],50)
        self.assertGreaterEqual(result['rankable_count'],10)
        self.assertEqual(result['absent_count']+result['model_matched_count'],50)
        allowed={x['code'] for x in self.holdings['positions']}
        self.assertTrue(all(x['code'] in allowed for x in result['all_ranked']))
        self.assertEqual(len({x['code'] for x in result['all_ranked']}),len(result['all_ranked']))
        self.assertFalse(result['price_model_alpha_vs_etf_unverified'] is False)
        self.assertTrue(result['future_dividends_excluded_not_imputed_zero'])

    def test_price_upside_sorted_and_per_issuer_consistent(self):
        result=filter_top10(self.holdings,self.full)
        expected=result['all_ranked'][:10]
        self.assertEqual(result['top10'],expected)
        self.assertTrue(all(expected[i]['potential_price_upside_pct']>=
                            expected[i+1]['potential_price_upside_pct']
                            for i in range(9)))
        for r in expected:
            self.assertAlmostEqual(
                r['potential_price_upside_pct'],
                100*(r['base_target_ntd']/r['price_ntd']-1),places=2)

    def test_rejects_forged_holdings_or_invalid_model_price(self):
        c=copy.deepcopy(self.holdings)
        c['positions'][1]['code']=c['positions'][0]['code']
        with self.assertRaisesRegex(ValueError,'0056_DUPLICATED_OR_BAD_POSITION'):
            filter_top10(c,self.full)
        c=copy.deepcopy(self.holdings)
        c['historical_pit_not_certified']=False
        with self.assertRaisesRegex(ValueError,'0056_HOLDINGS_IDENTITY_OR_COVERAGE_INVALID'):
            filter_top10(c,self.full)
        c=copy.deepcopy(self.full)
        code=self.holdings['positions'][0]['code']
        match=next((x for x in c['all_model_rows']
                    if x.get('code')==code and x.get('rankable')),None)
        if match:
            match['base']['price_upside_pct']+=10
            with self.assertRaisesRegex(ValueError,'0056_BASE_PRICE_UPSIDE_NOT_RECONCILED'):
                filter_top10(self.holdings,c)

    def test_print_exact_research_top10_for_auditable_response(self):
        r=filter_top10(self.holdings,self.full)
        slim={k:r[k] for k in ['etf','etf_holdings_date','asof_price_date',
            'estimate_vintage','holdings_count','model_matched_count',
            'rankable_count','unrankable_count','absent_count','top10','unrankable','absent']}
        print('BEGIN_0056_2027_TOP10='+json.dumps(slim,ensure_ascii=False,separators=(',',':')))


if __name__=='__main__':
    unittest.main()
