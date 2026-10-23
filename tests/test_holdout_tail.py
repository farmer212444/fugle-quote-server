"""Held-out accounting error tails must not imply 2027 share-price success."""
import copy
import unittest

from tw_model_v880.calibration import holdout_tail_diagnostics, fit_accounting
from test_v880 import CalibrationTests


class HoldoutTailTests(unittest.TestCase):
    @staticmethod
    def row(actual, forecast, baseline, growth):
        return dict(actual_revenue=actual, fixed_forecast=forecast,
                    prior_revenue=baseline, growth=growth)

    def test_quantiles_baseline_outperformance_and_signed_bias(self):
        rows=[self.row(100,90,80,0.2),self.row(100,100,100,0.1),
              self.row(100,120,100,-0.1),self.row(100,105,90,0.25),
              self.row(100,60,50,0.3)]
        out=holdout_tail_diagnostics(rows,lambda r:r['fixed_forecast'],
                                     lambda r:r['prior_revenue'],min_cell_n=2)
        self.assertEqual(out['n'],5)
        self.assertAlmostEqual(out['median_absolute_pct_error'],10)
        self.assertAlmostEqual(out['p90_absolute_pct_error'],32)
        self.assertAlmostEqual(out['p95_absolute_pct_error'],36)
        self.assertAlmostEqual(out['beats_prior_year_unchanged_share'],.6)
        self.assertAlmostEqual(out['ties_prior_year_unchanged_share'],.2)
        self.assertAlmostEqual(out['worse_than_prior_year_unchanged_share'],.2)
        self.assertFalse(out['calibrates_stock_return_probability'])
        self.assertFalse(out['calibrates_2027_eps_probability'])

    def test_small_subgroups_suppressed(self):
        rows=[self.row(100,95,98,.3),self.row(100,90,101,0)]
        out=holdout_tail_diagnostics(rows,lambda r:r['fixed_forecast'],
                                     lambda r:r['prior_revenue'],min_cell_n=4)
        self.assertEqual(out['groups']['HIGH_GROWTH_AT_LEAST_20PCT']['status'],
                         'INSUFFICIENT_SUBGROUP')

    def test_holdout_changes_errors_not_training_coefficients(self):
        history=CalibrationTests().data()
        old=fit_accounting(history,'2026-Q2')
        self.assertEqual(old['holdout_error_tail']['n'],old['holdout_count'])
        modified=copy.deepcopy(history)
        for row in modified.values():row['2026-Q2']['revenue_ytd_k']*=1.25
        new=fit_accounting(modified,'2026-Q2')
        for name in ('revenue_persistence','margin_persistence','cost_persistence'):
            self.assertEqual(old[name],new[name])
        self.assertNotEqual(old['holdout_error_tail']['median_absolute_pct_error'],
                            new['holdout_error_tail']['median_absolute_pct_error'])
        self.assertFalse(new['holdout_error_tail']['qualifies_formal_oos_trading_test'])

    def test_no_data_remains_uncalibrated(self):
        out=holdout_tail_diagnostics([],lambda r:1,lambda r:1)
        self.assertEqual(out['status'],'NO_HELDOUT_ROWS')
        self.assertFalse(out['calibrates_stock_return_probability'])


if __name__=='__main__': unittest.main()
