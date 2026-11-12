import json
from pathlib import Path
import unittest
from alphamax.engine import Costs, outcome, run, validate


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(Path('alphamax/examples/synthetic.json').read_text())
        self.row = self.data['cohorts'][0]['rows'][0]

    def test_future_feature_rejected(self):
        self.row['feature_available'] = '2020-01-01'
        with self.assertRaises(ValueError): validate(self.data)

    def test_survivor_only_rejected(self):
        self.data['cohorts'][0]['includes_delisted'] = False
        with self.assertRaises(ValueError): validate(self.data)

    def test_delisting_requires_recovery_evidence(self):
        self.data['cohorts'][0]['rows'][2]['settlement_verified'] = False
        with self.assertRaises(ValueError): validate(self.data)

    def test_unfilled_retains_cash(self):
        for status in ('limit_up', 'suspended', 'no_volume'):
            self.row['entry_status'] = status
            self.assertEqual(outcome(self.row, Costs())['return'], 0)

    def test_costs_lots_and_cash_exact(self):
        self.row.update(entry_price=25., exit_price=30., dividend_per_share=0.)
        result = outcome(self.row, Costs(slippage=0))
        self.assertEqual(result['shares'], 3000)
        expected = (90000 - 128.25 - 270 - 75000 - 106.875)/100000
        self.assertAlmostEqual(result['return'], expected)

    def test_blocked_and_delisted_not_removed(self):
        report = run(self.data)
        states = {e['status'] for f in report['folds'] for e in f['executions']}
        self.assertTrue({'delisted', 'blocked'} <= states)
        self.row.update(exit_status='blocked', dividend_per_share=0.)
        self.assertLess(outcome(self.row, Costs())['return'], -.7)

    def test_purged_walk_forward(self):
        report = run(self.data)
        self.assertEqual(report['folds'][0]['decision'], '2019-01-02')
        for f in report['folds']:
            self.assertLess(f['latest_train_label'], f['decision'])
            self.assertTrue(all(t < f['decision'] for t in f['train_decisions']))

    def test_future_outcomes_cannot_change_earlier_prediction(self):
        before = run(self.data)['folds'][0]
        self.data['cohorts'][-1]['rows'][0]['exit_price'] = 9999
        after = run(self.data)['folds'][0]
        self.assertEqual(before, after)

    def test_current_test_outcome_not_in_prediction(self):
        before = run(self.data)['folds'][0]
        self.data['cohorts'][2]['rows'][3]['exit_status'] = 'filled'
        self.data['cohorts'][2]['rows'][3]['exit_price'] = 999
        after = run(self.data)['folds'][0]
        self.assertEqual(before['prediction_12m'], after['prediction_12m'])
        self.assertEqual(before['threshold'], after['threshold'])
        self.assertNotEqual(before['alphamax_return'], after['alphamax_return'])

    def test_publication_lag_purges_entire_cohort(self):
        self.data['cohorts'][0]['rows'][0]['label_available'] = '2020-01-03'
        first = run(self.data)['folds'][0]
        self.assertEqual(first['decision'], '2020-01-02')
        self.assertNotIn('2017-01-02', first['train_decisions'])

    def test_no_legacy_imports(self):
        import ast
        tree = ast.parse(Path('alphamax/engine.py').read_text())
        modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(any(m and ('tw_model' in m or 'scripts' in m) for m in modules))

    def test_report_disclosures(self):
        report = run(self.data)
        for key in ('period', 'assumptions', 'version', 'engine_sha256', 'input_sha256', 'unverified'):
            self.assertTrue(report[key])
        self.assertEqual(report['data_kind'], 'synthetic')

    def test_short_horizon_rejected(self):
        self.row['exit_date'] = '2017-12-31'
        with self.assertRaises(ValueError): validate(self.data)

    def test_invalid_numbers_and_costs(self):
        for val in (float('nan'), float('inf'), -1):
            with self.assertRaises(ValueError): Costs(commission=val)
        self.row['entry_price'] = 0
        with self.assertRaises(ValueError): validate(self.data)

    def test_no_mature_fold_fails(self):
        self.data['cohorts'] = self.data['cohorts'][:1]
        with self.assertRaises(ValueError): run(self.data)


if __name__ == '__main__': unittest.main()
