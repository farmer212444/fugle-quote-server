"""0056 nine financials: official price/H1 EPS and dated secondary BVPS.

This is a reverse ROE/PB hurdle research screen only. It must never certify
2027 fair value or mix conditional financial rows into the 34 price-upsides.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.v8b6_0056_financial_pb_hurdle import screen,validate_bvps,write_report
from scripts.v8b4_0056_forward_top10 import load_inputs

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'
INPUT=ROOT/'config/0056_financial_bvps_2026-Q2_watch.json'
ASOF="2026-10-24T20:00:00+08:00"


class FinancialNine0056Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=screen(ROOT,ASOF)

    def test_all_nine_guarded_and_seven_other_issuers_remain_missing(self):
        a=self.data
        self.assertEqual(a['total_constituents'],50)
        self.assertEqual(a['other_sector_base_price_comparable_count'],34)
        self.assertEqual(a['nine_financial_ROE_PB_hurdle_only_count'],9)
        self.assertEqual(a['remaining_missing_comparable_count'],7)
        self.assertEqual(len(a['financials_sorted_by_conditional_hurdle_gap']),9)
        self.assertTrue(a['finance_ranking_is_not_a_2027_return_ranking'])
        self.assertTrue(a['exact_historical_original_BVPS_unverified'])
        self.assertFalse(a['same_day_intraday_PIT_proven'])
        self.assertTrue(a['original_0056_top10_unchanged'])
        self.assertTrue(a['all_13_formal_gates_preserved'])

    def test_h1_eps_and_pb_market_identity(self):
        rows={r['code']:r for r in self.data['financials_sorted_by_conditional_hurdle_gap']}
        self.assertEqual(set(rows),{'2880','2883','2884','2885','2886','2887','2890','2891','5876'})
        self.assertAlmostEqual(rows['2891']['current_pb_multiple'],74.9/34.99)
        self.assertAlmostEqual(rows['5876']['current_pb_multiple'],54.6/44.14)
        self.assertAlmostEqual(rows['2883']['current_pb_multiple'],37.75/25.28)
        self.assertEqual(rows['2890']['eps_2026_h1_official_ytd'],1.66)
        for r in rows.values():
            self.assertAlmostEqual(r['illustrative_required_sustainable_roe_pct'],
                                   3+7*r['current_pb_multiple'])
            self.assertAlmostEqual(r['h1_annualized_eps_divided_by_end_book_proxy_pct'],
                                   200*r['eps_2026_h1_official_ytd']/r['book_per_share_2026q2_ntd'])
            self.assertIsNone(r['financial_base_2027_eps_ntd'])
            self.assertIsNone(r['financial_base_2027_PB'])
            self.assertIsNone(r['financial_2027_price_upside_pct'])
            self.assertFalse(r['formal_Aplus'])

    def test_source_identity_and_accountability_fail_closed(self):
        original=json.loads(INPUT.read_text(encoding='utf-8'))
        holdings,_,_=load_inputs(ROOT)
        with self.assertRaisesRegex(ValueError,'0056_FINANCIAL_BVPS_NOT_OBSERVED_AS_OF_DAY'):
            validate_bvps(original,holdings,'2026-10-23T23:59:59+08:00')
        tampered=copy.deepcopy(original)
        tampered['positions'][0]['code']='2330'
        with self.assertRaisesRegex(ValueError,'0056_FINANCIAL_BVPS_ISSUER_QUARTER_OR_SOURCE_INVALID'):
            validate_bvps(tampered,holdings,ASOF)
        tampered=copy.deepcopy(original)
        tampered['positions'][1]['source_url']='https://fake.example/nav'
        with self.assertRaisesRegex(ValueError,'0056_FINANCIAL_BVPS_ISSUER_QUARTER_OR_SOURCE_INVALID'):
            validate_bvps(tampered,holdings,ASOF)
        tampered=copy.deepcopy(original)
        tampered['issuer_original_financial_statements_PIT_verified']=True
        with self.assertRaisesRegex(ValueError,'0056_FINANCIAL_SECONDARY_PROVENANCE_OR_SCOPE_INVALID'):
            validate_bvps(tampered,holdings,ASOF)

    def test_report_nonmixed_and_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'finance.json'
            write_report(self.data,p)
            write_report(self.data,p.with_suffix('.md'))
            before=p.read_bytes()
            write_report(self.data,p)
            self.assertEqual(before,p.read_bytes())
            t=p.with_suffix('.md').read_text(encoding='utf-8')
            self.assertIn('仍',t)
            self.assertIn('不屬2027合理價',t)
            self.assertIn('正式2027 EPS',t)
            self.assertIn('凱基金',t)

    def test_print_financial_hurdle_for_research_review(self):
        import json
        print('BEGIN_0056_NINE_FINANCE='+json.dumps({
            'nine':self.data['nine_financial_ROE_PB_hurdle_only_count'],
            'not_yet_rankable':self.data['remaining_missing_comparable_count'],
            'rows':[{
              'code':x['code'],'name':x['name'],
              'close':x['official_reference_close_ntd'],
              'bvps':x['book_per_share_2026q2_ntd'],
              'pb':round(x['current_pb_multiple'],2),
              '2026_H1_eps':x['eps_2026_h1_official_ytd'],
              'profit_to_BV_proxy':round(x['h1_annualized_eps_divided_by_end_book_proxy_pct'],1),
              'illustrative_roe_hurdle':round(x['illustrative_required_sustainable_roe_pct'],1),
              'gap':round(x['illustrative_required_roe_minus_h1_proxy_pp'],1)}
              for x in self.data['financials_sorted_by_conditional_hurdle_gap']]},
            ensure_ascii=False,separators=(',',':')))


if __name__=='__main__':
    unittest.main()
