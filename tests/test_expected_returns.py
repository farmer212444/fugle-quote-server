"""All fixtures are synthetic engineering checks, not investment evidence."""
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import expected_returns as runner
from tw_model_v880.expected_returns import (POLICY,RETURN_DEFINITION,distribution,estimate,
    independent_cohorts,net_return,state,validate_observations,walk_forward)

COSTS = dict(buy_fee_rate=.001425,sell_fee_rate=.001425,sell_tax_rate=.003,
             buy_slippage_rate=.001,sell_slippage_rate=.001,half_spread_rate=.0005,minimum_fee_ntd=20.)
ZERO = dict.fromkeys(COSTS,0.)


def forecast(start='2026-01-01',code='1000',days=365):
    day = dt.date.fromisoformat(start)
    return dict(market='TWSE',code=code,name='SYNTHETIC',industry='SYNTHETIC_SECTOR',
        reference_close=100.,price_date=start,target_date=(day+dt.timedelta(days=days)).isoformat(),
        estimate_vintage=start+'T13:30:00+08:00',rankable=True,
        forecast_binding=dict(forecast_method_sha256='a'*64),
        bear=dict(target_price=70.),base=dict(target_price=100.),bull=dict(target_price=130.))


def records(cohorts=24,stocks=20):
    result = []
    for i in range(cohorts):
        start = f'{1970+2*i}-01-01'
        for j in range(stocks):
            f = forecast(start,str(1000+j))
            result.append(dict(cohort_id=f'cohort-{i:02}',forecast=f,issued_at=start+'T13:31:00+08:00',
                exit_at=f['target_date']+'T13:30:00+08:00',first_verified_at=f['target_date']+'T14:00:00+08:00',
                terminal_value_per_initial_share=100.,dividends_per_initial_share=5.,
                market_regime='UP' if i%2 else 'DOWN',sources_verified=True,cohort_complete=True,
                return_definition=RETURN_DEFINITION))
    return result


class ExpectedReturns(unittest.TestCase):
    def calculate(self,f=None,samples=None,**kw):
        return estimate(f or forecast(),samples or [],asof='2026-01-01T15:00:00+08:00',costs=ZERO,notional=1e6,**kw)

    def test_empty_outcomes_produce_no_default_weights(self):
        r = self.calculate();self.assertIsNone(r['scenario_probabilities']);self.assertIsNone(r['expected_net_total_return'])
        self.assertEqual(r['matched_rows'],0);self.assertEqual(r['formal_Aplus_added'],0)

    def test_tails_losses_and_conditional_means_reconcile(self):
        sample = records(1,3)
        for r,price,cash in zip(sample,(0.,100.,400.),(0.,5.,10.)):
            r['terminal_value_per_initial_share'],r['dividends_per_initial_share'] = price,cash
        r = distribution(forecast(),[sample],ZERO,1000.)
        self.assertAlmostEqual(sum(r['scenario_probabilities'].values()),1.)
        self.assertEqual(r['conditional_scenario_means']['bear']['net_return'],-1.)
        self.assertAlmostEqual(r['conditional_scenario_means']['bull']['net_return'],3.1)
        self.assertAlmostEqual(sum(r['scenario_probabilities'][s]*r['conditional_scenario_means'][s]['net_return']
                                  for s in ('bear','base','bull')),r['expected_net_total_return'])
        self.assertEqual(state(85.,[70.,100.,130.]),'base');self.assertEqual(state(115.,[70.,100.,130.]),'bull')

    def test_fees_tax_and_unknown_dividends(self):
        shares = 1000./100.15;sale = shares*120*.9985
        self.assertAlmostEqual(net_return(100.,120.,5.,COSTS,1000.),(sale-20-sale*.003+shares*5)/1020-1)
        with self.assertRaisesRegex(ValueError,'WEALTH'):
            net_return(100.,120.,None,COSTS,1000.)

    def test_same_date_reruns_and_many_stocks_do_not_add_independent_dates(self):
        sample = records(1);repeated = copy.deepcopy(sample)
        for r in repeated:r.update(cohort_id='rerun',issued_at=r['issued_at'].replace('13:31','14:00'))
        self.assertEqual(len(independent_cohorts(sample+repeated)),1)
        self.assertEqual(walk_forward(records(1,1000),ZERO,1e6)['oos_cohorts'],0)

    def test_late_verification_cannot_train_earlier_signal(self):
        sample = records();self.assertEqual(walk_forward(sample,ZERO,1e6)['oos_cohorts'],12)
        for r in sample:r['first_verified_at'] = '2025-12-01T14:00:00+08:00'
        self.assertEqual(walk_forward(sample,ZERO,1e6)['oos_cohorts'],0)

    def test_complete_oos_path_computes_a_research_expectation(self):
        r = self.calculate(samples=records())
        self.assertEqual(r['status'],'EMPIRICAL_EXPECTATION_AFTER_OOS_CHECKS_RESEARCH_ONLY')
        self.assertAlmostEqual(r['expected_net_total_return'],.05)
        self.assertEqual(r['scenario_probabilities']['base'],1.)
        self.assertTrue(r['interval_is_not_a_future_return_prediction_interval'])
        self.assertFalse(r['investment_outperformance_proven'])

    def test_method_sector_and_exact_horizon_must_match(self):
        for f in (dict(forecast(),industry='OTHER'),forecast(days=366),
                  dict(forecast(),forecast_binding=dict(forecast_method_sha256='b'*64))):
            self.assertEqual(self.calculate(f,records(13))['matched_rows'],0)

    def test_invalid_partial_future_duplicate_components_are_rejected(self):
        for field,value,reason in [('dividends_per_initial_share',None,'COMPONENT'),('cohort_complete',False,'PARTIAL'),
            ('first_verified_at','2030-01-01T00:00:00+08:00','CLOCK'),('terminal_value_per_initial_share',float('nan'),'COMPONENT')]:
            sample = records(1,1);sample[0][field] = value
            with self.assertRaisesRegex(ValueError,reason):validate_observations(sample,'2026-01-01T15:00:00+08:00')
        sample = records(1,1)
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):self.calculate(samples=sample+sample)

    def test_failed_oos_diagnostics_keep_expectation_null(self):
        sample = records()
        for r in sample[240:]:r['terminal_value_per_initial_share'] = 1.
        r = self.calculate(samples=sample)
        self.assertFalse(r['diagnostics']['diagnostics_passed']);self.assertIsNone(r['scenario_probabilities'])

    def test_policy_floors_and_boolean_inputs(self):
        with self.assertRaisesRegex(ValueError,'FLOOR'):self.calculate(policy=dict(POLICY,minimum_train_rows=1))
        f = forecast();f['base']['target_price'] = True
        with self.assertRaisesRegex(ValueError,'SCENARIOS'):self.calculate(f)

    def test_annualization_has_correct_definition(self):
        sample = records(1,2);sample[0]['terminal_value_per_initial_share'] = 50.;sample[1]['terminal_value_per_initial_share'] = 200.
        r = distribution(forecast(days=730),[sample],ZERO,1000.)
        self.assertAlmostEqual(r['annualized_expected_terminal_wealth'],1.30**(365.25/730)-1)
        self.assertTrue(r['annualized_expected_terminal_wealth_is_not_expected_annualized_return'])

    def test_registration_is_immutable_and_cost_change_creates_new_identity(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t);a = runner.register(root,COSTS,1e6,'2026-01-01T15:00:00+08:00')
            self.assertEqual(a,runner.register(root,COSTS,1e6,'2026-01-02T15:00:00+08:00'))
            self.assertNotEqual(a['registration_id'],runner.register(root,ZERO,1e6,'2026-01-02T15:00:00+08:00')['registration_id'])

    def test_stale_vintage_is_not_reissued(self):
        with tempfile.TemporaryDirectory() as t:
            r = dict(estimate_vintage='2026-01-01T15:00:00+08:00',asof_price_date='2026-01-01')
            with self.assertRaisesRegex(ValueError,'STALE'):runner.freeze(Path(t),r,[],{},'2026-01-15T15:00:00+08:00')

    def test_future_outcomes_are_pending_not_zero(self):
        self.assertIsNone(runner.settle(Path('/unused'),dict(target_date='2027-12-31'),'2026-01-01T15:00:00+08:00',{}))

    def test_missing_one_selected_leg_rejects_whole_cohort(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t);c = dict(cohort_id='synthetic',record_sha256='x'*64,target_date='2020-01-01',
                                    forecasts=[forecast(code='1000'),forecast(code='1001')])
            p = root/runner.FOLDER/'inputs/synthetic.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps(dict(cohort_sha256='x'*64,stock_legs=[dict(market='TWSE',code='1000')])))
            with self.assertRaisesRegex(ValueError,'PARTIAL_OR_EXTRA'):runner.settle(root,c,'2026-01-01T15:00:00+08:00',{})


if __name__ == '__main__':unittest.main()
