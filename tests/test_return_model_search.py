"""Synthetic controls and source-format arithmetic; never investment evidence."""
import copy
import datetime as dt
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tw_model_v880.contracts import canonical_hash
from tw_model_v880.return_search import FEATURES,FOLDER,parameters,percentile_ranks,select_portfolio,fit_parameters,walk_forward,registered_trial_count,load_cohort
from scripts.return_model_search import registration,freeze,leg_nav,outcome,holding_dates
from scripts.history_archive import outstanding_benchmark_codes,archive_original
from scripts.tw_history_backfill import parse,historical_url
from tests.test_tw_history_backfill import response
ROOT=Path(__file__).resolve().parents[1]
ASOF='2026-10-23T12:00:00+08:00'


def policy():return json.loads((ROOT/'tw-market-data/config/return_model_search_v1.json').read_bytes())


def features():
    return [dict(code=str(9000+i),market='TWSE',industry=str(i%5),adv20_ntd=50000000,feature_available_at='2026-10-22T18:00:00+08:00',
                 recommendation_blocked=False,features={f:float(i) for f in FEATURES}) for i in range(60)]


def candidates():return [p for p in parameters(policy()) if p['holding_sessions']==21][:2]


def observation(i,a=.1,b=.01):
    start=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc)+dt.timedelta(days=30*i)
    def item(v):return dict(net_return=v,stress_net_return=max(-1,v-.01),benchmark_net_return=.02,stress_benchmark_net_return=.01,
                           model_max_drawdown=.05,benchmark_max_drawdown=.06,market_regime='UP' if i%2 else 'DOWN')
    ids=[p['parameter_id'] for p in candidates()]
    return dict(signal_at=start.isoformat(),exit_at=(start+dt.timedelta(days=5)).isoformat(),first_verified_at=(start+dt.timedelta(days=6)).isoformat(),
                holding_sessions=21,outcomes={ids[0]:item(a),ids[1]:item(b)})


class Selection(unittest.TestCase):
    def test_240_distinct_parameters_with_five_families_and_three_horizons(self):
        p=policy();rows=parameters(p)
        self.assertEqual(len(rows),240);self.assertEqual(len({r['parameter_id'] for r in rows}),240)
        self.assertEqual(len(p['families']),5);self.assertEqual({r['holding_sessions'] for r in rows},{21,63,126})

    def test_invalid_policy_weights_grid_costs_and_deployment_fail(self):
        for kind in ('weight','grid','cost','deployment'):
            p=policy()
            if kind=='weight':p['families']['valuation']['forward_upside_pct']=.5
            elif kind=='grid':p['grid']['stock_counts']=[10,10]
            elif kind=='cost':p['costs']['stock']['buy_fee_rate']=-1
            else:p['automatic_deployment']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):parameters(p)

    def test_tied_percentiles_do_not_depend_on_input_order(self):
        self.assertEqual(percentile_ranks([10,10,20]),{10:.25,20:1})
        self.assertEqual(percentile_ranks([10,10,20]),percentile_ranks([20,10,10]))

    def test_equal_50_stock_weights_ignore_unseen_outcomes(self):
        p=next(p for p in parameters(policy()) if p['family']=='valuation' and p['stock_count']==50 and p['sector_cap']==.4)
        rows=features();result=select_portfolio(rows,p,ASOF)
        self.assertTrue(result['parameter_inputs_ready']);self.assertEqual(len(result['positions']),50)
        self.assertEqual(result['positions'][0]['code'],'9059');self.assertTrue(all(x['weight']==.02 for x in result['positions']))
        for r in rows:r['later_realized_return']=100 if r['code']=='9000' else -100
        self.assertEqual(result,select_portfolio(list(reversed(rows)),p,ASOF))

    def test_missing_features_do_not_create_zero_return_performance(self):
        rows=features();p=next(p for p in parameters(policy()) if p['family']=='momentum' and p['stock_count']==50)
        for r in rows:r['features']['momentum_63_21_pct']=None
        result=select_portfolio(rows,p,ASOF)
        self.assertFalse(result['parameter_inputs_ready']);self.assertNotIn('net_return',result)

    def test_future_features_and_duplicate_issuers_rejected(self):
        rows=features();rows[0]['feature_available_at']='2027-01-01T00:00:00+08:00'
        with self.assertRaisesRegex(ValueError,'FUTURE_FEATURE'):select_portfolio(rows,candidates()[0],ASOF)
        rows=features();rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ISSUER'):select_portfolio(rows,candidates()[0],ASOF)

    def test_sector_cash_and_known_governance_are_preserved(self):
        rows=features()
        for r in rows:r['industry']='ONE_SECTOR'
        rows[-1]['recommendation_blocked']=True
        result=select_portfolio(rows,candidates()[0],ASOF)
        self.assertTrue(result['parameter_inputs_ready']);self.assertGreater(result['cash_weight'],.5)
        self.assertNotIn('9059',[r['code'] for r in result['positions']])
        self.assertEqual(result['exclusions']['MATERIAL_GOVERNANCE_BLOCK'],1)


class Chronology(unittest.TestCase):
    def setUp(self):self.p=policy();self.p.update(minimum_train_periods=2,maximum_train_periods=3,embargo_calendar_days=5)

    def test_unseen_test_winner_cannot_select_test_parameters(self):
        r=walk_forward([observation(0),observation(1),observation(2,-.2,.8)],candidates(),self.p,ASOF)
        self.assertEqual(r['walk_forward_tests'][0]['selected_parameter_id'],candidates()[0]['parameter_id'])
        self.assertEqual(r['walk_forward_tests'][0]['net_return'],-.2);self.assertFalse(r['evidence_supports_0050_edge'])

    def test_late_verified_training_label_cannot_enter_earlier_selection(self):
        rows=[observation(0),observation(1),observation(2)];rows[0]['first_verified_at']='2026-04-01T00:00:00+00:00'
        self.assertEqual(walk_forward(rows,candidates(),self.p,ASOF)['walk_forward_test_periods'],0)

    def test_overlap_future_labels_and_mixed_horizons_rejected(self):
        rows=[observation(0),observation(1)];rows[1]['signal_at']=rows[0]['exit_at']
        with self.assertRaisesRegex(ValueError,'OVERLAPPING'):walk_forward(rows,candidates(),self.p,ASOF)
        rows=[observation(0)];rows[0]['first_verified_at']='2027-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'CLOCK_INVALID'):walk_forward(rows,candidates(),self.p,ASOF)
        with self.assertRaisesRegex(ValueError,'MIXED_HOLDING'):fit_parameters([],parameters(policy()),self.p)

    def test_missing_selected_test_leg_blocks_instead_of_counting_a_win(self):
        rows=[observation(0),observation(1),observation(2)];del rows[-1]['outcomes'][candidates()[0]['parameter_id']]
        result=walk_forward(rows,candidates(),self.p,ASOF)
        self.assertEqual(result['walk_forward_test_periods'],0);self.assertEqual(len(result['rejected_test_periods']),1)

    def test_total_loss_remains_in_test_results(self):
        rows=[observation(0),observation(1),observation(2,-1)];rows[-1]['outcomes'][candidates()[0]['parameter_id']]['model_max_drawdown']=1
        self.assertEqual(walk_forward(rows,candidates(),self.p,ASOF)['walk_forward_tests'][0]['net_return'],-1)

    def test_insufficient_training_creates_no_optimal_model(self):
        r=walk_forward([observation(0)],candidates(),policy(),ASOF)
        self.assertIsNone(r['latest_training_pick']['selected_parameter_id']);self.assertEqual(r['trade_orders_created'],0)


class Archives(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name);self.now=dt.datetime.now(dt.timezone.utc).isoformat()
        self.reg=registration(self.root,policy(),{'model_code_sha256':'a'*64},self.now)
        self.full=dict(model_code_sha256='a'*64,estimate_vintage=self.now,asof_price_date='2026-10-22')
    def freeze(self):return freeze(self.root,self.reg,self.full,features(),{},21,self.now,{},set())

    def test_registration_reuse_preserves_clock_and_new_design_does_not_reset_trials(self):
        old=registration(self.root,policy(),{'model_code_sha256':'a'*64},'2027-01-01T00:00:00+08:00')
        self.assertEqual(old,self.reg);self.assertEqual(registered_trial_count(self.root),240)
        p=policy();p['max_training_drawdown']=.25;registration(self.root,p,{'model_code_sha256':'a'*64},self.now)
        self.assertEqual(registered_trial_count(self.root),480)

    def test_actual_archive_clock_daily_reuse_and_hash_validation(self):
        receipt,doc,created=self.freeze();self.assertTrue(created)
        path=next((self.root/FOLDER/self.reg['experiment_id']/'cohorts/21').glob('*.json'))
        self.assertEqual(load_cohort(path),(receipt,doc));self.assertFalse(self.freeze()[2])
        self.assertGreaterEqual(dt.datetime.fromisoformat(receipt['signal_at']),dt.datetime.fromisoformat(self.now))
        path.with_suffix('.json.gz').write_bytes(b'tamper')
        with self.assertRaisesRegex(ValueError,'BYTES_CHANGED'):load_cohort(path)

    def test_future_feature_clock_cannot_be_backdated_into_actual_archive(self):
        future=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError,'FREEZE_INPUT_FROM_FUTURE'):freeze(self.root,self.reg,self.full,features(),{},21,future,{},set())

    def test_old_frozen_picks_remain_collectible_without_todays_rank_report(self):
        self.freeze();changed=policy();changed['max_training_drawdown']=.25;registration(self.root,changed,{'model_code_sha256':'a'*64},self.now)
        self.assertIn('9059',outstanding_benchmark_codes(self.root,'TWSE'))
        self.assertEqual(outstanding_benchmark_codes(self.root,'TPEX'),[])

    def test_missing_source_input_stays_pending(self):
        receipt,doc,_=self.freeze()
        self.assertIsNone(outcome(self.root,self.reg,receipt,doc,[str(i) for i in range(100,121)],self.now,{},'UP'))

    def test_omitted_stock_cannot_remove_losers_from_returns(self):
        receipt,doc,_=self.freeze();path=self.root/FOLDER/'inputs'/(receipt['cohort_id']+'.json');path.parent.mkdir()
        path.write_text(json.dumps(dict(cohort_sha256=receipt['cohort_sha256'],stock_legs=[],benchmark_leg={})))
        with self.assertRaisesRegex(ValueError,'MISSING_OR_EXTRA_SELECTED'):outcome(self.root,self.reg,receipt,doc,[str(i) for i in range(100,121)],self.now,{},'UP')

    def test_calendar_gap_stays_pending_instead_of_skipping_missing_month(self):
        cal={'2026-12-01':dict(open_at='2026-12-01T09:00:00+08:00')}
        self.assertIsNone(holding_dates(cal,{'2026-10','2026-12'},'2026-10-21T18:00:00+08:00',1))


class SourceRecomputedReturns(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name);self.policy=policy();self.policy['grid']['holding_sessions']=[2]
        self.reg=registration(self.root,self.policy,{'model_code_sha256':'a'*64},dt.datetime.now(dt.timezone.utc).isoformat())
        self.p=next(p for p in self.reg['spec']['parameters'] if p['family']=='valuation' and p['stock_count']==10 and p['sector_cap']==.4)
        selection=select_portfolio(features(),self.p,ASOF);self.cohort=dict(holding_sessions=2,selections={self.p['parameter_id']:selection})
        self.receipt=dict(cohort_id='SYNTHETIC',cohort_sha256=canonical_hash(self.cohort),signal_at='2026-10-20T18:00:00+08:00')
        self.dates=['2026-10-21','2026-10-22'];self.original_review=self.save('synthetic-review-source.json',{'synthetic_test_only':True})
        self.payload=dict(cohort_sha256=self.receipt['cohort_sha256'],stock_legs=[self.leg(p['code'],110) for p in selection['positions']],benchmark_leg=self.leg('0050',105))
        self.path=self.root/FOLDER/'inputs/SYNTHETIC.json';self.path.parent.mkdir(parents=True);self.flush()
    def save(self,name,doc):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(doc))
        return dict(path=name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    def leg(self,code,exit_close):
        doc=json.loads(response('2026-10',self.dates).replace(b'6206',code.encode()))
        for i,row in enumerate(doc['data']):
            close=100 if i==0 else exit_close;row[3]='2,000,000,000';row[4]='100';row[5]=str(max(100,close));row[6]='100';row[7]=str(close)
        raw=json.dumps(doc).encode();rows=parse(raw,code,'2026-10');original=archive_original(self.root,'TWSE',code+'-2026-10',historical_url(code,'2026-10'),raw,rows)
        bars=copy.deepcopy(rows)
        for bar in bars:bar['fillability_verified']=True
        b=self.save('bars-'+code+'.json',bars);a=self.save('actions-'+code+'.json',[])
        review=dict(code=code,market='TWSE',complete=True,reviewer_id='SYNTHETIC_TEST_ONLY',**{'from':'2026-10-21T08:00:00+08:00','through':'2026-10-22T13:30:00+08:00'},
                    checked_at=dt.datetime.now(dt.timezone.utc).isoformat(),original_sources=[self.original_review])
        return dict(code=code,market='TWSE',quote_originals=[original],bars=b,actions=a,execution_review=self.save('execution-'+code+'.json',dict(review,bars_sha256=b['sha256'])),
                    corporate_action_review=self.save('review-'+code+'.json',dict(review,actions_sha256=a['sha256'])))
    def flush(self):self.path.write_text(json.dumps(self.payload))
    def calculate(self):return outcome(self.root,self.reg,self.receipt,self.cohort,self.dates,dt.datetime.now(dt.timezone.utc).isoformat(),{},'UP')

    def test_source_bytes_produce_matched_fee_adjusted_returns_and_stable_receipt(self):
        r=self.calculate();v=r['outcomes'][self.p['parameter_id']]
        def expected(ratio,c):return ratio*(1-c['sell_slippage_rate']-c['half_spread_rate'])*(1-c['sell_fee_rate']-c['sell_tax_rate'])/((1+c['buy_slippage_rate']+c['half_spread_rate'])*(1+c['buy_fee_rate']))-1
        self.assertAlmostEqual(v['net_return'],expected(1.1,self.policy['costs']['stock']))
        self.assertAlmostEqual(v['benchmark_net_return'],expected(1.05,self.policy['costs']['etf']))
        self.assertLess(v['stress_net_return'],v['net_return']);self.assertEqual(self.calculate(),r)

    def test_modified_normalized_close_cannot_override_official_source(self):
        leg=self.payload['stock_legs'][0];bars=json.loads((self.root/leg['bars']['path']).read_bytes());bars[-1]['close']=9999
        leg['bars']=self.save(leg['bars']['path'],bars);self.flush()
        with self.assertRaisesRegex(ValueError,'DIFFER_FROM_OFFICIAL'):self.calculate()

    def test_close_only_review_cannot_authorize_open_fill(self):
        leg=self.payload['stock_legs'][0];ref=leg['execution_review'];r=json.loads((self.root/ref['path']).read_bytes());r['from']='2026-10-21T13:30:00+08:00'
        leg['execution_review']=self.save(ref['path'],r);self.flush()
        with self.assertRaisesRegex(ValueError,'OPEN_NOT_COVERED'):self.calculate()

    def test_split_dividend_cash_and_minimum_fee_math(self):
        leg=self.payload['stock_legs'][0];bars=json.loads((self.root/leg['bars']['path']).read_bytes());bars[-1].update(open=50,close=55)
        actions=[dict(id='split',type='split',ratio=2,effective_at='2026-10-22T00:00:00+08:00'),dict(id='dividend',type='cash_dividend',per_share=1,effective_at='2026-10-22T01:00:00+08:00')]
        costs={k:0. for k in self.policy['costs']['stock']};costs['minimum_fee_ntd']=20
        def sourced(root,ref):return actions if ref['path']==leg['actions']['path'] else {'from':'2026-10-21T08:00:00+08:00'}
        with patch('scripts.return_model_search.verified_bars',return_value=bars),patch('scripts.return_model_search.reviewed'),patch('scripts.return_model_search.source',side_effect=sourced):
            nav=leg_nav(self.root,leg,self.dates,self.receipt['signal_at'],ASOF,1000,costs,.05,{})
        self.assertAlmostEqual(nav[0],.96);self.assertAlmostEqual(nav[-1],1.0776)


if __name__=='__main__':unittest.main()
