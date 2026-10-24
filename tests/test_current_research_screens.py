"""Current selections must be visible without claiming an untested best model."""
import copy
import unittest

from scripts.return_model_search import current_research_screens,render
from tw_model_v880.return_search import parameters,select_portfolio
from tests.test_return_model_search import ASOF,features,policy


class CurrentResearchScreens(unittest.TestCase):
    def setUp(self):
        self.features=features()
        self.full=dict(model='TEST',estimate_vintage='2026-10-22T18:00:00+08:00',
            asof_price_date='2026-10-22',all_model_rows=[dict(code=r['code'],market=r['market'],
                name='Synthetic '+r['code'],rankable=True,recommendation_blocked=False,
                reference_close=100,scenario_upside_pct=r['features']['forward_upside_pct'],
                warning_flags=['COMPANY_OPERATING_BRIDGE_UNVERIFIED'],formal_Aplus=False,
                certification=dict(gates_pending=['forecast_bridge'],gates_failed=[])) for r in self.features])
        self.reg=dict(experiment_id='SYNTHETIC',spec=dict(parameters=parameters(policy())))

    def build(self):return current_research_screens(self.full,self.features,self.reg,ASOF)

    def test_displays_exact_existing_parameter_selection_without_return_fitting(self):
        result=self.build()
        self.assertEqual(len(result['screens']),5)
        self.assertFalse(result['selection_uses_realized_returns'])
        self.assertFalse(result['performance_winner_selected'])
        self.assertEqual(result['formal_Aplus_created'],0)
        for screen in result['screens']:
            expected=select_portfolio(self.features,screen['parameter'],ASOF)
            self.assertEqual([p['code'] for p in screen['positions']],[p['code'] for p in expected['positions']])
            for row in screen['positions']:
                self.assertIsNone(row['expected_net_return'])
                self.assertIsNone(row['calibrated_win_probability'])
                self.assertEqual(row['pending_gates'],['forecast_bridge'])
                self.assertEqual(row['warning_flags'],['COMPANY_OPERATING_BRIDGE_UNVERIFIED'])
                self.assertFalse(row['formal_Aplus'])

    def test_missing_momentum_does_not_silently_change_balanced_weights(self):
        for row in self.features:row['features']['momentum_63_21_pct']=None
        screens={s['family']:s for s in self.build()['screens']}
        for family in ('momentum','balanced'):
            self.assertFalse(screens[family]['inputs_ready'])
            self.assertEqual(screens[family]['positions'],[])
        self.assertTrue(screens['valuation']['inputs_ready'])

    def test_governance_blocked_issuer_stays_out(self):
        self.features[-1]['recommendation_blocked']=True
        self.full['all_model_rows'][-1]['recommendation_blocked']=True
        self.assertTrue(all('9059' not in [r['code'] for r in s['positions']] for s in self.build()['screens']))

    def test_inconsistent_model_or_future_data_rejected(self):
        baseline=copy.deepcopy(self.full)
        self.full['all_model_rows'][-1]['scenario_upside_pct']=999
        with self.assertRaisesRegex(ValueError,'VALUATION_CONTEXT_MISMATCH'):self.build()
        self.full=baseline
        self.full['estimate_vintage']='2027-01-01T00:00:00+08:00'
        with self.assertRaisesRegex(ValueError,'FUTURE_MODEL'):self.build()

    def test_report_exposes_stock_names_and_scenario_limits(self):
        report=dict(model='TEST',asof_price_date='2026-10-22',parameter_count=240,
            parameters=self.reg['spec']['parameters'],current_research_screens=self.build(),
            input_coverage_by_market={'TWSE':dict(source_universe_count=60,adv20_coverage=60)},
            horizon_reports=[dict(holding_sessions=21,parameter_count=80,current_ready_parameter_count=80,
                verified_return_periods=0,walk_forward_test_periods=0,current_parameter_readiness=[
                    dict(stock_count=p['stock_count'],inputs_ready=True) for p in self.reg['spec']['parameters']])])
        text=render(report)
        self.assertIn('9059 Synthetic 9059',text)
        self.assertIn('未認證',text)
        self.assertIn('不是所列持有天數的預期報酬',text)


if __name__=='__main__':unittest.main()
