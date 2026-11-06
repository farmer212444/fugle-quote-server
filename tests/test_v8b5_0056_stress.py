"""0056 forward TOP10: independent H1 EPS and non-probabilistic stress."""
import copy
import math
from pathlib import Path
import tempfile
import unittest

from scripts.v8b5_0056_stress_audit import audit_0056,write_report
from scripts.v8b4_0056_forward_top10 import filter_top10,load_inputs
ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'


class Fund0056EPSStressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=audit_0056(ROOT)

    def test_all_34_rows_present_exact_constituents(self):
        r=self.report
        self.assertEqual(r['tracked_etf_holdings_count'],50)
        self.assertEqual(r['base_price_rankable_count'],34)
        self.assertEqual(r['not_rankable_count'],16)
        self.assertEqual(len(r['all_34_ranked']),34)
        self.assertEqual(len(r['top10']),10)
        self.assertTrue(r['original_base_ranking_and_targets_unchanged'])
        self.assertTrue(r['no_formal_gate_pass_granted'])
        self.assertTrue(r['dividends_and_fees_unmodeled'])
        self.assertTrue(r['strategy_outperformance_vs_0056_not_tested'])

    def test_named_issuer_stretch_binds_current_forecast_to_historical_h1(self):
        # Today's prices may legitimately reorder the same issuers. Check the
        # source/forecast contract rather than freeze an old market ranking.
        rows={x['code']:x for x in self.report['all_34_ranked']}
        _,_,full=load_inputs(ROOT)
        forecasts={r['code']:r for r in full['all_model_rows']}
        for code,h1 in {'2317':7.84,'2376':17.73,'2382':12.93}.items():
            row=rows[code]
            self.assertEqual(row['h1_2026_basic_eps'],h1)
            self.assertEqual(row['forward_2027_eps'],forecasts[code]['base']['eps'])
            stretch=100*(forecasts[code]['base']['eps']/(2*h1)-1)
            self.assertAlmostEqual(row['base_2027_eps_vs_h1_annualized_pct'],stretch)
            self.assertEqual(row['base_2027_eps_above_h1_runrate_by_30pct'],stretch>=30)
            self.assertEqual(row['base_2027_eps_above_h1_runrate_by_50pct'],stretch>=50)

    def test_eps_pe_stress_mathematically_exact_not_certified(self):
        for row in self.report['all_34_ranked']:
            with self.subTest(code=row['code']):
                expected=row['forward_2027_eps']*.8*row['reasonable_pe']*.8
                self.assertAlmostEqual(row['combined_eps_pe_minus20_price_ntd'],expected)
                self.assertAlmostEqual(row['combined_eps_pe_minus20_upside_pct'],
                    100*(expected/row['price_ntd']-1))
                self.assertFalse(row['issuer_2026_h1_statement_PIT_verified'])
                self.assertTrue(row['EPS_PE_stress_is_not_a_probability'])
                self.assertTrue(row['no_formal_Aplus_promotion'])

    def test_does_not_modify_snapshot_model_or_holdings(self):
        holdings,_,full=load_inputs(ROOT)
        before=copy.deepcopy((holdings,full))
        result=audit_0056(ROOT)
        matched=filter_top10(holdings,full)
        self.assertEqual([x['code'] for x in result['all_34_ranked']],
                         [x['code'] for x in matched['all_ranked']])
        self.assertEqual(before,(holdings,full))

    def test_report_files_are_reproducible_and_no_formal_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'0056_test.json'
            write_report(self.report,path)
            write_report(self.report,path.with_suffix('.md'))
            first=path.read_bytes()
            write_report(self.report,path)
            self.assertEqual(first,path.read_bytes())
            text=path.with_suffix('.md').read_text(encoding='utf-8')
            self.assertIn('鴻海',text)
            self.assertIn('EPS和合理PE各下修20%',text)
            self.assertIn('正式A+沒有新增',text)

    def test_log_review_ready_all_ten(self):
        r=self.report
        import json
        print('BEGIN_0056_STRESS_V1='+json.dumps({
            'asof_price_date':r['reference_close_date'],
            'model':r['model_version'],
            'eps_stretch_ge30_count':r['higher_than_h1_annualized_by_30pct_count'],
            'rows':[dict(code=x['code'],name=x['name'],
                H1_EPS=x['h1_2026_basic_eps'],
                EPS_2027=x['forward_2027_eps'],
                EPS_vs_H1_annualized_pct=round(x['base_2027_eps_vs_h1_annualized_pct'],1),
                Base_upside_pct=round(x['potential_price_upside_pct'],1),
                EPS_PE_both_down20_upside_pct=round(x['combined_eps_pe_minus20_upside_pct'],1),
                original_current=x['original_current_issuer_numeric_checked'])
                for x in r['top10']]},ensure_ascii=False,separators=(',',':')))


if __name__=='__main__':
    unittest.main()
