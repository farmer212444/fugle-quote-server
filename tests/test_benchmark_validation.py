"""Synthetic accounting and hostile-input checks, never real market performance."""
import copy
import datetime as dt
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.benchmark_sources import archive,close_at,load_index,parse,verify,month_url
from scripts.benchmark_validation import register,build,window,summarize,PROTOCOL
from scripts.history_archive import archive_original,outstanding_benchmark_codes
from scripts.tw_history_backfill import parse as parse_twse,historical_url,prioritized_candidates
from scripts.v893_tpex_daily_backfill import parse_daily,selected_codes,daily_url
from scripts.v897_freeze_model_vintage import freeze
from tests import test_v897_freeze_model_vintage as vintage_fixtures
from tests.test_tw_history_backfill import response
from tests.test_v893_tpex_daily_backfill import payload as tpex_payload
from tw_model_v880.contracts import canonical_hash
from tw_model_v880.execution import net_trade,COST_FIELDS

ASOF='2026-10-28T16:00:00+08:00'
CAPTURE='2026-10-27T16:00:00+08:00'
DATES=['2026-10-21','2026-10-22','2026-10-23','2026-10-26','2026-10-27']


def benchmark_raw(dates=DATES,levels=None):
    levels=levels or [100,100,102,105,106]
    return json.dumps(dict(stat='OK',title='115年10月 發行量加權股價報酬指數',
        fields=['日　期','發行量加權股價報酬指數'],
        data=[[f'{int(d[:4])-1911}/{d[5:7]}/{d[8:]}',str(v)] for d,v in zip(dates,levels)])).encode()


class BenchmarkSources(unittest.TestCase):
    def test_price_index_wrong_month_duplicate_and_nonfinite_are_rejected(self):
        raw=json.loads(benchmark_raw())
        for changed in [dict(raw,title='115年10月 發行量加權股價指數'),
                        dict(raw,title='115年09月 發行量加權股價報酬指數'),
                        dict(raw,data=raw['data']+[raw['data'][-1]]),
                        dict(raw,data=[['115/10/21','NaN']])]:
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):parse(json.dumps(changed).encode(),'2026-10')

    def test_archive_reparses_original_and_preserves_first_capture(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);raw=benchmark_raw()
            ref=archive(root,'2026-10',raw,CAPTURE)
            again=archive(root,'2026-10',raw,ASOF)
            self.assertEqual(ref,again)
            doc=verify(root,ref,ASOF);self.assertEqual(doc['captured_at'],CAPTURE)
            self.assertEqual(len(load_index(root,ASOF)['rows']),5)
            target=root/doc['archive_path'];target.write_bytes(gzip.compress(b'{}'))
            self.assertTrue(load_index(root,ASOF)['errors'])

    def test_no_source_captured_in_future_and_no_future_market_close(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            with self.assertRaisesRegex(ValueError,'CLOSE_AFTER_SOURCE_CAPTURE'):
                archive(root,'2026-10',benchmark_raw(),'2026-10-21T12:00:00+08:00')
            archive(root,'2026-10',benchmark_raw(),CAPTURE)
            self.assertTrue(load_index(root,'2026-10-26T16:00:00+08:00')['errors'])


class BenchmarkIntegration(unittest.TestCase):
    def setUp(self):
        f=vintage_fixtures.FrozenVintageTests('test_current_real_run_archive_contains_full_universe_and_exact_quotes')
        f.setUp();self.addCleanup(f.doCleanups);self.root=f.root;self.f=f
        legs=[dict(market='TWSE',code=str(1000+i)) for i in range(29)]+[dict(market='TPEX',code='6494')]
        f.full['all_model_rows']=legs
        full=json.dumps(f.full,separators=(',',':')).encode();packed=gzip.compress(full,mtime=0)
        (self.root/'rankings/v880_full_results.json.gz').write_bytes(packed)
        f.research['data_scope']['model_rows']=30
        f.research['top30_provisional']=legs;f.research['strategy_variant_sha256']='c'*64
        f.research['full_results'].update(sha256=hashlib.sha256(packed).hexdigest(),json_sha256=hashlib.sha256(full).hexdigest())
        f.rewrite_research()
        config=json.loads((Path(__file__).parents[1]/'tw-market-data/config/institutional_research.json').read_text())
        config['cost_policy']={k:0. for k in COST_FIELDS};config['cost_policy']['minimum_fee_ntd']=0
        config['benchmark_policy']['holding_intervals']=2
        (self.root/'config').mkdir();(self.root/'config/institutional_research.json').write_text(json.dumps(config))
        self.frozen=freeze(self.root,vintage_fixtures.NOW,'V8.8.2')['path']
        self.registration=register(self.root,self.frozen,'2026-10-21T08:15:00+08:00')
        self.trial_id=self.registration['trial_id'];self.cohort_id=self.registration['cohort_id']
        self.cohort=read(self.root/'experiments/benchmark_cohorts'/self.trial_id/(self.cohort_id+'.json'))

    def save(self,name,obj):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj))
        return dict(path=name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def original(self,market,identity,url,raw,parsed):
        ref=archive_original(self.root,market,identity,url,raw,parsed)
        # A synthetic capture clock; production always uses the real fetch time.
        path=self.root/ref['receipt_path'];doc=read(path);doc['captured_at_utc']=CAPTURE
        path.write_text(json.dumps(doc));ref['captured_at_utc']=CAPTURE
        return ref

    def inputs(self):
        archive(self.root,'2026-10',benchmark_raw(),CAPTURE)
        review_original=self.save('synthetic-review-original.json',dict(synthetic_test_only=True))
        tpex_rows={};tpex_refs=[]
        for day in DATES[1:4]:
            doc=json.loads(tpex_payload(day))
            row=doc['tables'][0]['data'][0];row[9]='100,000,000';row[8]='2,000,000'
            if day==DATES[3]:row[2]='55';row[5]='55'
            raw=json.dumps(doc).encode();parsed=parse_daily(raw,day)
            tpex_refs.append(self.original('TPEX',day,daily_url(day),raw,parsed));tpex_rows[day]=parsed['6494']
        legs=[]
        for selected in self.cohort['legs']:
            code,market=selected['code'],selected['market']
            if market=='TWSE':
                doc=json.loads(response('2026-10',DATES).replace(b'6206',code.encode()))
                for row in doc['data']:row[3]='100,000,000'
                doc['data'][3][7]='23.1';doc['data'][3][5]='23.1'
                raw=json.dumps(doc).encode();parsed=parse_twse(raw,code,'2026-10')
                refs=[self.original('TWSE',code+'-2026-10',historical_url(code,'2026-10'),raw,parsed)]
                bars=[r for r in parsed if r['date'] in DATES[1:4]]
            else:refs=tpex_refs;bars=[tpex_rows[d] for d in DATES[1:4]]
            bars=copy.deepcopy(bars)
            for bar in bars:bar['fillability_verified']=True
            bar_ref=self.save('test-bars-'+code+'.json',bars);actions=self.save('test-actions-'+code+'.json',[])
            base=dict(code=code,market=market,complete=True,reviewer_id='SYNTHETIC_TEST_ONLY',
                      **{'from':close_at(DATES[1]),'through':close_at(DATES[3])},
                      checked_at=CAPTURE,original_sources=[review_original])
            execution=self.save('execution-review-'+code+'.json',dict(base,bars_sha256=bar_ref['sha256']))
            review=self.save('action-review-'+code+'.json',dict(base,actions_sha256=actions['sha256']))
            legs.append(dict(code=code,market=market,bars=bar_ref,quote_originals=refs,actions=actions,
                             execution_review=execution,corporate_action_review=review))
        self.input_doc=dict(cohort_sha256=canonical_hash(self.cohort),legs=legs)
        self.input_path=self.root/'experiments/benchmark_inputs'/(self.cohort_id+'.json')
        self.input_path.parent.mkdir(parents=True);self.flush()

    def flush(self):self.input_path.write_text(json.dumps(self.input_doc))

    def test_same_day_reruns_are_one_pending_period_and_no_performance_is_invented(self):
        repeated=register(self.root,self.frozen,'2026-10-21T08:20:00+08:00')
        self.assertEqual(repeated['cohort_id'],self.cohort_id)
        report=build(self.root,'2026-10-21T08:21:00+08:00')
        self.assertEqual(report['verified_outcomes'],0)
        self.assertIsNone(report['trials'][0]['model_total_return'])
        self.assertEqual(len(report['collection_queue']),30)
        self.assertFalse(report['formal_out_of_sample_pass'])

    def test_source_backed_twse_and_tpex_recompute_identical_periods(self):
        self.inputs();report=build(self.root,ASOF);trial=report['trials'][0]
        self.assertFalse(trial['rejected_outcomes']);self.assertFalse(report['source_errors'])
        self.assertEqual(report['verified_outcomes'],1)
        self.assertAlmostEqual(trial['model_total_return'],.1)
        self.assertAlmostEqual(trial['benchmark_total_return'],.05)
        self.assertAlmostEqual(trial['excess_return_pp'],5)
        self.assertEqual(trial['daily_nav_observations'],3)
        self.assertFalse(trial['evidence_supports_benchmark_edge'])
        self.assertFalse(report['collection_queue'])

    def test_omitting_one_of_thirty_stocks_rejects_whole_period(self):
        self.inputs();self.input_doc['legs'].pop();self.flush()
        trial=build(self.root,ASOF)['trials'][0]
        self.assertEqual(trial['verified_nonoverlapping_periods'],0)
        self.assertIn('MISSING_FROZEN_TOP30',trial['rejected_outcomes'][0]['reason'])

    def test_normalized_price_rewrite_fails_even_with_new_file_digest(self):
        self.inputs();leg=self.input_doc['legs'][0]
        bars=read(self.root/leg['bars']['path']);bars[-1]['close']=1000
        leg['bars']=self.save(leg['bars']['path'],bars);self.flush()
        trial=build(self.root,ASOF)['trials'][0]
        self.assertIn('DIFFER_FROM_OFFICIAL_ORIGINALS',trial['rejected_outcomes'][0]['reason'])

    def test_removing_calendar_bar_or_source_or_review_is_not_a_profit(self):
        self.inputs()
        for field in ('quote_originals','corporate_action_review','execution_review'):
            prior=copy.deepcopy(self.input_doc)
            self.input_doc['legs'][0].pop(field);self.flush()
            trial=build(self.root,ASOF)['trials'][0]
            self.assertEqual(trial['verified_nonoverlapping_periods'],0)
            self.assertTrue(trial['rejected_outcomes'])
            self.input_doc=prior

    def test_forged_no_action_list_without_matching_review_is_rejected(self):
        self.inputs();leg=self.input_doc['legs'][0]
        leg['actions']=self.save('forged-actions.json',[dict(id='unreviewed',type='cash_dividend',
            effective_at=close_at(DATES[2]),per_share=1000)])
        self.flush();trial=build(self.root,ASOF)['trials'][0]
        self.assertIn('SOURCE_BOUND_REVIEW',trial['rejected_outcomes'][0]['reason'])

    def test_changed_cost_policy_starts_new_trial_and_preserves_prior_registration(self):
        path=self.root/'config/institutional_research.json';config=read(path)
        prior=(self.root/'experiments/benchmark_registrations'/(self.trial_id+'.json')).read_bytes()
        config['cost_policy']['buy_fee_rate']=.001425;path.write_text(json.dumps(config))
        new=register(self.root,self.frozen,'2026-10-21T08:20:00+08:00')
        self.assertNotEqual(new['trial_id'],self.trial_id)
        self.assertEqual((self.root/'experiments/benchmark_registrations'/(self.trial_id+'.json')).read_bytes(),prior)

    def test_future_archive_cannot_be_registered_as_an_old_signal(self):
        path=self.root/self.frozen;doc=read(path);doc['archived_at_utc']='2026-10-21T20:00:00+00:00'
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError,'FROM_FUTURE'):
            register(self.root,self.frozen,'2026-10-21T08:20:00+08:00')

    def test_standalone_freeze_cli_can_import_and_register_from_outside_repository(self):
        env=dict(os.environ);env.pop('PYTHONPATH',None)
        script=Path(__file__).parents[1]/'scripts/v897_freeze_model_vintage.py'
        completed=subprocess.run([sys.executable,str(script),'--data-root',str(self.root),'--register-benchmark'],
                                 cwd=self.root,env=env,check=True,capture_output=True,text=True)
        output=json.loads(completed.stdout)
        self.assertEqual(output['benchmark_registration']['trial_id'],self.trial_id)


def read(path):return json.loads(Path(path).read_text())


class ExecutionAndPerformance(unittest.TestCase):
    def test_close_entry_excludes_same_day_ex_dividend_and_respects_fee_floor(self):
        bars=[dict(open_at='2026-10-22T09:00:00+08:00',close_at=close_at('2026-10-22'),
                   open=10,close=20,turnover_ntd=1000000,fillability_verified=True),
              dict(open_at='2026-10-23T09:00:00+08:00',close_at=close_at('2026-10-23'),
                   open=20,close=22,turnover_ntd=1000000,fillability_verified=True)]
        costs=dict.fromkeys(COST_FIELDS,0.);costs['minimum_fee_ntd']=20
        actions=[dict(id='earlier-dividend',type='cash_dividend',effective_at='2026-10-22T09:00:00+08:00',per_share=100)]
        actual=net_trade(bars,actions,signal_at='2026-10-21T16:00:00+08:00',exit_at=bars[-1]['close_at'],
                         costs=costs,corporate_actions_complete=True,requested_notional_ntd=1000,
                         max_participation=.05,entry_execution='NEXT_SESSION_CLOSE')
        self.assertEqual(actual['entry_at'],bars[0]['close_at'])
        self.assertEqual(actual['dividend_cash'],0)
        self.assertAlmostEqual(actual['net_total_return'],1080/1020-1)

    def index(self,dates,levels):
        return dict(rows={d:dict(level=l,close_at=close_at(d)) for d,l in zip(dates,levels)},
                    months={d[:7]:{} for d in dates})

    def result(self,dates,model,benchmark):
        return dict(entry_at=close_at(dates[0]),exit_at=close_at(dates[-1]),dates=dates,
                    model_nav=model,stress_nav=model,net_total_return=model[-1]-1,
                    stress_net_total_return=model[-1]-1,benchmark_total_return=benchmark[-1]-1,
                    market_regime='UP')

    def policy(self):
        return read(Path(__file__).parents[1]/'tw-market-data/config/institutional_research.json')['benchmark_policy']

    def test_daily_drawdown_does_not_hide_large_intraperiod_loss(self):
        dates=DATES[1:4];index=self.index(dates,[100,90,105])
        result=summarize([self.result(dates,[1,.5,1.1],[1,.9,1.05])],index,self.policy(),1)
        self.assertAlmostEqual(result['model_max_drawdown'],.5)
        self.assertAlmostEqual(result['benchmark_max_drawdown'],.1)
        self.assertFalse(result['evidence_supports_benchmark_edge'])

    def test_cash_gap_is_compared_with_continuously_invested_benchmark(self):
        dates=['2026-10-01','2026-10-02','2026-10-05','2026-10-06','2026-10-07']
        index=self.index(dates,[100,100,150,150,150])
        a=self.result(dates[:2],[1,1.1],[1,1]);b=self.result(dates[3:],[1,1.1],[1,1])
        result=summarize([a,b],index,self.policy(),1)
        self.assertAlmostEqual(result['model_total_return'],.21)
        self.assertAlmostEqual(result['benchmark_total_return'],.5)
        self.assertAlmostEqual(result['excess_return_pp'],-29)

    def test_overlapping_periods_and_missing_calendar_months_fail(self):
        dates=DATES[1:4];index=self.index(dates,[100,101,102]);r=self.result(dates,[1,1.1,1.2],[1,1.01,1.02])
        with self.assertRaisesRegex(ValueError,'OVERLAPPING'):
            summarize([r,r],index,self.policy(),1)
        index=self.index(['2026-10-22','2026-12-01','2026-12-02'],[100,101,102])
        with self.assertRaisesRegex(ValueError,'CALENDAR_MONTHS_MISSING'):
            window(index,'2026-10-21T16:00:00+08:00',2)

    def test_trial_correction_regime_and_sample_gates_are_exercised(self):
        dates=DATES[1:]+['2026-10-28']
        index=self.index(dates,[100,101,102,103,104])
        a=self.result(dates[:2],[1,1.1],[1,1.01])
        b=self.result(dates[3:],[1,1.1],[1,104/103]);b['market_regime']='DOWN'
        policy=dict(self.policy(),minimum_nonoverlapping_oos_periods=2,bootstrap_draws=200)
        valid=summarize([a,b],index,policy,1)
        self.assertTrue(valid['evidence_supports_benchmark_edge'])
        self.assertFalse(valid['formal_out_of_sample_pass'])
        self.assertFalse(summarize([a,b],index,policy,6)['evidence_supports_benchmark_edge'])
        b['market_regime']=None
        self.assertFalse(summarize([a,b],index,policy,1)['evidence_supports_benchmark_edge'])


class CollectionQueue(unittest.TestCase):
    def test_both_markets_follow_frozen_legs_even_after_current_ranking_changes(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'rankings').mkdir()
            (root/'rankings/latest_benchmark_validation.json').write_text(json.dumps(dict(schema=PROTOCOL,
                collection_queue=[dict(market='TWSE',code='1234'),dict(market='TPEX',code='6494')])))
            day='2026-10-22'
            (root/'rankings/v891_gate_progress.json').write_text(json.dumps(dict(asof_price_date=day,issuer_diagnostics=[])))
            raw=json.dumps([dict(market='TWSE',code='1234'),dict(market='TWSE',code='6206'),
                            dict(market='TWSE',code='9802'),dict(market='TPEX',code='6494')]).encode()
            self.assertEqual(prioritized_candidates(raw,day,root=root)[0],'1234')
            self.assertEqual(selected_codes(root,day,raw)[0],['6494'])
            self.assertEqual(outstanding_benchmark_codes(root,'TPEX'),['6494'])


if __name__=='__main__':unittest.main()
