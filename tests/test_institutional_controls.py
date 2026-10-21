import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tw_model_v880.events import FIELDS,load_earnings_events,parse_press
from tw_model_v880.contracts import forecast_binding,matches_forecast,review_work,valuation_diagnostics
from tw_model_v880.evidence import GATES
from tw_model_v880.execution import COST_FIELDS,net_trade
from tw_model_v880.experiments import purged_walk_forward,compare_models,calibration_summary
from tw_model_v880.portfolio import constrained_portfolio,reverse_execution_capacity
from tw_model_v880.specialists import segment
from tw_model_v880.validation_io import immutable_registration,collect_trials,source
from scripts.tw_v880_run import run
from tests.test_integration_v880 import FakeData,CAL
from tw_model_v880.model import estimate


ASOF='2026-10-21T12:00:00+08:00'
COSTS={k:0. for k in COST_FIELDS}
POLICY=dict(max_stock_weight=.1,max_sector_weight=.25,max_common_risk_weight=.2,
            max_portfolio_bear_loss=.05,max_daily_participation=.05,max_exit_sessions=5)


def pages():
    values={
        'revenue_k':[300,250,20,900,800,12.5,300,0],
        'gross_profit_k':[60,50,20,180,160,12.5,60,0],
        'opex_k':[30,25,20,90,80,12.5,30,0],
        'operating_profit_k':[30,25,20,90,80,12.5,30,0],
        'nonoperating_k':[0,0,'-',0,0,'-',0,'-'],
        'pretax_profit_k':[30,25,20,90,80,12.5,30,0],
        'net_income_k':[24,20,20,72,64,12.5,24,0],
        'parent_net_income_k':[24,20,20,72,64,12.5,24,0],
        'basic_eps':[.24,.2,20,.72,.64,12.5,.24,0],
    }
    return ['鈺齊國際(9802)2026年第三季自結財報新聞稿',
            '新台幣仟元 2026/Q3 2025/Q3 '+
            ' '.join(label+' '+' '.join(map(str,values[key])) for key,label in FIELDS)+
            ' 業外匯兌評價影響數']


class EarningsEvents(unittest.TestCase):
    def archive(self,root):
        folder=root/'evidence/v880/originals/9802';folder.mkdir(parents=True)
        pdf=folder/'press.pdf';pdf.write_bytes(b'%PDF-synthetic-only')
        doc=dict(document_kind='news',title='2026年第三季自結財報新聞稿',
                 captured_at_utc='2026-10-20T23:00:00+00:00',
                 source_url='https://www.fulgentsun.com/img/News_Release/test.pdf',
                 archive_path=pdf.relative_to(root).as_posix(),bytes=pdf.stat().st_size,
                 sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
        manifest=folder/'manifest.json'
        manifest.write_text(json.dumps(dict(issuer='9802',documents=[doc])))
        return pdf,manifest,doc

    def test_full_table_reconciles_including_parent_and_noncontrolling_profit(self):
        result=parse_press(pages())
        self.assertEqual(result['current']['revenue_k'],900)
        self.assertEqual(result['single_quarter']['net_income_k'],24)

    def test_wrong_company_year_or_units_block(self):
        for old,new in [('9802','6206'),('2026年第三季','2025年第三季'),('新台幣仟元','美元')]:
            bad=[s.replace(old,new) for s in pages()]
            with self.assertRaises(ValueError):parse_press(bad)

    def test_column_shift_not_silently_read_as_current_period(self):
        bad=pages();bad[1]=bad[1].replace('合併營收 300 250','合併營收 300')
        with self.assertRaisesRegex(ValueError,'COLUMN_COUNT'):parse_press(bad)

    def test_broken_income_arithmetic_blocks(self):
        bad=pages();bad[1]=bad[1].replace('營業利益 30 25 20 90','營業利益 35 25 20 90')
        with self.assertRaisesRegex(ValueError,'RECONCILIATION'):parse_press(bad)

    def test_valid_original_is_research_event_without_formal_pass(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.archive(root)
            events,states=load_earnings_events(root,ASOF,'2026-Q2',reader=lambda _:pages())
            self.assertIn('9802',events);self.assertFalse(events['9802']['formal_quality_pass'])
            self.assertFalse(events['9802']['historical_issuer_publication_PIT_verified'])
            self.assertFalse(states['9802']['blocks_current_decision'])

    def test_pdf_tampering_isolated_and_blocks_old_decision(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);pdf,_,_=self.archive(root);pdf.write_bytes(b'%PDF-tampered')
            events,states=load_earnings_events(root,ASOF,'2026-Q2',reader=lambda _:pages())
            self.assertFalse(events);self.assertTrue(states['9802']['blocks_current_decision'])

    def test_future_capture_is_not_available_in_historical_research(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.archive(root)
            events,states=load_earnings_events(root,'2026-10-20T12:00:00+08:00','2026-Q2',reader=lambda _:pages())
            self.assertFalse(events);self.assertEqual(states['9802']['status'],'FUTURE_CAPTURE_NOT_USED')

    def test_formal_q3_supersedes_the_press_event(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.archive(root)
            events,_=load_earnings_events(root,ASOF,'2026-Q3',reader=lambda _:pages())
            self.assertFalse(events)

    def test_external_host_does_not_become_issuer_original(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);_,manifest,doc=self.archive(root)
            doc['source_url']='https://example.invalid/press.pdf'
            manifest.write_text(json.dumps(dict(issuer='9802',documents=[doc])))
            events,states=load_earnings_events(root,ASOF,'2026-Q2',reader=lambda _:pages())
            self.assertFalse(events);self.assertIn('HOST',states['9802']['reason'])


class EarningsForecastIntegration(unittest.TestCase):
    def data(self):
        d=FakeData();code='SYNTHETIC_A'
        d.detailed_values=lambda key,period:d.evidence['primary'][key[1]]['prior_full_year'] if period=='2025-Q4' else None
        event=dict(code=code,financial_period='2026-Q3',prior_period='2025-Q3',available_at='2026-10-20T12:00:00+08:00',
                   source_kind='ISSUER_SELF_REPORTED_UNAUDITED',event_sha256='a'*64,
                   current=dict(revenue_k=900,gross_profit_k=150,operating_profit_k=60,pretax_profit_k=70,net_income_k=56,parent_net_income_k=56,nonoperating_k=10),
                   prior=dict(revenue_k=750,gross_profit_k=150,operating_profit_k=75,pretax_profit_k=90,net_income_k=72,parent_net_income_k=72,nonoperating_k=15),
                   single_quarter=dict(revenue_k=300,gross_profit_k=30,operating_profit_k=0,pretax_profit_k=0,net_income_k=0,parent_net_income_k=0))
        return d,event

    def test_new_income_updates_forecast_and_preserves_old_cashflow_period(self):
        d,event=self.data();key=('TEST','SYNTHETIC_A')
        before=estimate(d,key,CAL,ASOF,'2027-12-31')
        d.earnings_events={'SYNTHETIC_A':event}
        after=estimate(d,key,CAL,ASOF,'2027-12-31')
        self.assertLess(after['base']['eps'],before['base']['eps'])
        self.assertEqual(after['financial_period'],'2026-Q3')
        self.assertEqual(after['cashflow_financial_period'],'2026-Q2')
        self.assertFalse(after['formal_Aplus'])

    def test_restatement_or_future_source_is_not_a_free_forecast_override(self):
        d,event=self.data();d.earnings_events={'SYNTHETIC_A':event}
        event['current']['parent_net_income_k']=99
        with self.assertRaisesRegex(ValueError,'RESTATEMENT'):estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        event['available_at']='2026-10-22T00:00:00+08:00'
        with self.assertRaisesRegex(ValueError,'FUTURE'):estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')

    def test_unparsed_new_earnings_blocks_reusing_old_valuation_as_current(self):
        d,_=self.data();d.earnings_event_states={'SYNTHETIC_A':dict(blocks_current_decision=True)}
        row=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        self.assertFalse(row['rankable'])
        self.assertIn('NEW_ORIGINAL_EARNINGS_NOT_RECONCILED_OLD_VALUATION_DIAGNOSTIC_ONLY',row['exclusion_reasons'])


class EconomicContracts(unittest.TestCase):
    def cases(self):
        return {k:dict(revenue_k=1000,gross_margin=.3,opex_ratio=.1,nonoperating_k=0,
                       tax_rate=.2,parent_fraction=1,shares=10000,eps=16,pe=10,target_price=160)
                for k in ('base','bear','bull')}

    def test_quote_date_and_upside_do_not_invalidate_unchanged_economics(self):
        cases=self.cases();a=forecast_binding('X','2026-Q2','2027-12-31',cases)
        cases['base']['price_upside_pct']=99
        b=forecast_binding('X','2026-Q2','2027-12-31',cases)
        self.assertEqual(a,b)
        self.assertTrue(matches_forecast(a,b,'unrelated-runtime','2026-10-22','2027-12-31'))

    def test_capital_or_cost_change_invalidates_forecast_contract(self):
        a=forecast_binding('X','2026-Q2','2027-12-31',self.cases())
        for key,value in [('shares',20000),('gross_margin',.2)]:
            cases=self.cases();cases['base'][key]=value
            b=forecast_binding('X','2026-Q2','2027-12-31',cases)
            self.assertFalse(matches_forecast(a,b,'runtime','2026-10-21','2027-12-31'))

    def test_legacy_certificate_keeps_date_and_code_guard(self):
        cert=dict(model_code_sha256='old',reference_price_date='2026-10-20',target_date='2027-12-31')
        binding=forecast_binding('X','2026-Q2','2027-12-31',self.cases())
        self.assertFalse(matches_forecast(cert,binding,'old','2026-10-21','2027-12-31'))

    def test_source_count_never_manufactures_thirteen_passes(self):
        work=review_work(dict(code='X',source_document_count=100))
        self.assertEqual({r['gate'] for r in work},set(GATES))
        self.assertFalse(any(r['formal_pass'] for r in work))
        self.assertEqual(next(r for r in work if r['gate']=='out_of_sample_validation')['scope'],'STRATEGY')

    def test_reverse_margin_rebuilds_the_market_price(self):
        row=dict(reference_close=100,base=self.cases()['base'],bear=dict(target_price=70))
        d=valuation_diagnostics(row)
        gm=d['market_implied_gross_margin']
        rebuilt=1000*(gm-.1)*.8*1000/10000*10
        self.assertAlmostEqual(rebuilt,100)
        self.assertAlmostEqual(d['eps_pe_each_minus20_upside_pct'],2.4)

    def test_end_of_year_capacity_is_not_full_year_capacity(self):
        spec=dict(kind='manufacturing',quarterly_capacity_schedule=[dict(quarter=q,capacity_units_for_quarter=100*q,utilization=.5) for q in range(1,5)],
                  asp_twd=100,unit_cost_twd=50,opex_fixed_k=0,opex_rate=0)
        self.assertEqual(segment(spec)['revenue_k'],50)

    def test_partial_capacity_schedule_and_double_depreciation_rejected(self):
        spec=dict(kind='manufacturing',capacity_units=100,utilization=.5,asp_twd=100,unit_cost_twd=50,opex_fixed_k=0,opex_rate=0)
        with self.assertRaises(ValueError):segment(dict(spec,quarterly_capacity_schedule=[]))
        with self.assertRaisesRegex(ValueError,'DOUBLE_COUNTED'):segment(dict(spec,fixed_factory_cost_k=2,depreciation_k=1,fixed_factory_cost_ex_depreciation_k=2))


class RiskBudget(unittest.TestCase):
    def candidate(self,code,sector='A',tag='AI'):
        return dict(code=code,market='TEST',industry=sector,formal_Aplus=True,
                    execution_review=dict(spread_and_exit_verified=True,median20_turnover_ntd=100000000),
                    common_risk_tags=[tag],reviewed_stress_loss_fraction=.3)

    def test_common_risk_and_sector_limits_across_different_stocks(self):
        result=constrained_portfolio([self.candidate(str(i),sector=str(i%2)) for i in range(5)],10000000,POLICY)
        self.assertLessEqual(sum(p['weight'] for p in result['positions']),.2+1e-10)
        self.assertLessEqual(result['scenario_bear_loss'],.05+1e-10)
        self.assertGreater(result['cash_weight'],.8)

    def test_unverified_liquidity_and_quality_remain_cash(self):
        row=self.candidate('X');row['formal_Aplus']=False
        result=constrained_portfolio([row],10000000,POLICY)
        self.assertEqual(result['cash_weight'],1)
        self.assertEqual(result['trade_orders_created'],0)

    def test_unknown_common_exposure_not_assumed_diversified(self):
        row=self.candidate('X');row['common_risk_tags']=None
        self.assertFalse(constrained_portfolio([row],10000000,POLICY)['positions'])

    def test_unknown_or_zero_stress_does_not_allow_unlimited_position(self):
        for value in (None,0,-.2,float('nan')):
            row=self.candidate('X');row['reviewed_stress_loss_fraction']=value
            self.assertFalse(constrained_portfolio([row],10000000,POLICY)['positions'])

    def test_exit_capacity_constrains_position_size(self):
        row=self.candidate('X');row['execution_review']['median20_turnover_ntd']=100000
        position=constrained_portfolio([row],10000000,POLICY)['positions'][0]
        self.assertAlmostEqual(position['weight'],.0025)
        self.assertLessEqual(position['required_exit_sessions'],5)

    def test_duplicate_issuer_is_not_a_second_risk_budget(self):
        with self.assertRaises(ValueError):constrained_portfolio([self.candidate('X')]*2,10000000,POLICY)

    def test_bad_policy_and_missing_capital_rejected(self):
        for value in (None,0,True,float('inf')):
            with self.assertRaises(ValueError):constrained_portfolio([],value,POLICY)
        with self.assertRaises(ValueError):constrained_portfolio([],100,dict(POLICY,max_stock_weight=2))
        self.assertIsNone(reverse_execution_capacity(None,100))


class ExecutionControls(unittest.TestCase):
    def bars(self):
        return [dict(open_at='2026-10-19T09:00:00+08:00',close_at='2026-10-19T13:30:00+08:00',open=100,close=102,turnover_ntd=10000000,fillability_verified=True),
                dict(open_at='2026-10-20T09:00:00+08:00',close_at='2026-10-20T13:30:00+08:00',open=51,close=55,turnover_ntd=10000000,fillability_verified=True)]

    def trade(self,**kw):
        params=dict(bars=self.bars(),actions=[],signal_at='2026-10-16T17:00:00+08:00',exit_at='2026-10-20T14:00:00+08:00',
                    costs=COSTS,corporate_actions_complete=True,requested_notional_ntd=100000,max_participation=.05)
        params.update(kw);return net_trade(**params)

    def test_split_dividend_and_both_sides_of_execution_cost(self):
        actions=[dict(id='split',type='split',effective_at='2026-10-20T00:00:00+08:00',ratio=2),
                 dict(id='dividend',type='cash_dividend',effective_at='2026-10-20T08:00:00+08:00',per_share=1)]
        r=self.trade(actions=actions,costs=dict(COSTS,buy_fee_rate=.001,sell_fee_rate=.001,sell_tax_rate=.003))
        self.assertEqual(r['entry_at'],'2026-10-19T09:00:00+08:00')
        self.assertAlmostEqual(r['net_total_return'],(110000*.996+2000)/100100-1)

    def test_no_close_fill_on_signal_session(self):
        with self.assertRaisesRegex(ValueError,'AWAITING'):self.trade(signal_at='2026-10-20T13:30:00+08:00')

    def test_missing_costs_and_unknown_actions_not_zero(self):
        with self.assertRaises(ValueError):self.trade(costs={})
        with self.assertRaises(ValueError):self.trade(corporate_actions_complete=False)
        with self.assertRaises(ValueError):self.trade(actions=[dict(id='rights',type='rights',effective_at='2026-10-20T08:00:00+08:00')])

    def test_zero_volume_or_unverified_queue_cannot_be_skipped(self):
        bars=self.bars();bars[0]['turnover_ntd']=0
        with self.assertRaises(ValueError):self.trade(bars=bars)
        bars=self.bars();bars[0]['fillability_verified']=False
        with self.assertRaises(ValueError):self.trade(bars=bars)

    def test_buy_and_sell_participation_both_checked(self):
        with self.assertRaisesRegex(ValueError,'PARTICIPATION'):self.trade(requested_notional_ntd=1000000)

    def test_duplicate_session_or_corporate_action_rejected(self):
        with self.assertRaisesRegex(ValueError,'SESSION'):self.trade(bars=self.bars()*2)
        a=dict(id='D',type='cash_dividend',effective_at='2026-10-20T08:00:00+08:00',per_share=1)
        with self.assertRaisesRegex(ValueError,'ACTION'):self.trade(actions=[a,a])


class WalkForwardControls(unittest.TestCase):
    def pairs(self,n=65):
        start=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc)
        records=[]
        for i in range(n):
            day=start+dt.timedelta(days=i)
            records.append(dict(signal_date=day.date().isoformat(),signal_at=day.isoformat(),
                                champion_frozen_at=(start-dt.timedelta(days=1)).isoformat(),
                                challenger_frozen_at=(start-dt.timedelta(days=1)).isoformat(),
                                champion_net_return=.001,challenger_net_return=.002,
                                execution_and_actions_verified=True,cost_policy_sha256_champion='a'*64,
                                cost_policy_sha256_challenger='a'*64,
                                outcome_end_champion=(day+dt.timedelta(hours=10)).isoformat(),
                                outcome_end_challenger=(day+dt.timedelta(hours=10)).isoformat(),
                                market_regime='up' if i%2 else 'down'))
        return records

    def test_overlapping_training_labels_are_purged(self):
        samples=[dict(id='old',signal_at='2026-01-01T00:00:00+00:00',label_end='2026-01-10T00:00:00+00:00'),
                 dict(id='overlap',signal_at='2026-01-15T00:00:00+00:00',label_end='2026-02-10T00:00:00+00:00'),
                 dict(id='test',signal_at='2026-02-02T00:00:00+00:00',label_end='2026-03-02T00:00:00+00:00')]
        fold=purged_walk_forward(samples,[('2026-02-01T00:00:00+00:00','2026-03-01T00:00:00+00:00')],2)[0]
        self.assertEqual(fold['train'],['old']);self.assertEqual(fold['test'],['test'])

    def test_positive_evidence_can_be_eligible_without_deploying(self):
        r=compare_models(self.pairs(),trials=2)
        self.assertTrue(r['promotion_eligible']);self.assertFalse(r['automatic_deployment'])

    def test_insufficient_data_never_returns_a_win_probability(self):
        r=compare_models(self.pairs(3),trials=1)
        self.assertFalse(r['promotion_eligible']);self.assertNotIn('win_probability',r)

    def test_negative_edge_never_promotes(self):
        records=self.pairs()
        for r in records:r['challenger_net_return']=-.001
        self.assertFalse(compare_models(records,trials=1)['promotion_eligible'])

    def test_same_day_reruns_are_not_independent_dates(self):
        records=self.pairs();records[1]['signal_date']=records[0]['signal_date']
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):compare_models(records,trials=1)

    def test_overlapping_outcome_windows_not_chained_into_portfolio_cagr(self):
        records=self.pairs();records[0]['outcome_end_champion']=records[0]['outcome_end_challenger']=records[2]['signal_at']
        with self.assertRaisesRegex(ValueError,'OVERLAPPING'):compare_models(records,trials=1)

    def test_cost_mismatch_or_future_model_rejected(self):
        records=self.pairs();records[0]['cost_policy_sha256_challenger']='b'*64
        with self.assertRaises(ValueError):compare_models(records,trials=1)
        records=self.pairs();records[0]['challenger_frozen_at']='2027-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError):compare_models(records,trials=1)

    def test_one_regime_and_excessive_trials_block_promotion(self):
        records=self.pairs()
        for r in records:r['market_regime']='up'
        self.assertFalse(compare_models(records,trials=1)['promotion_eligible'])
        self.assertFalse(compare_models(self.pairs(),trials=1000)['promotion_eligible'])

    def test_post_outcome_probabilities_cannot_be_calibrated(self):
        row=dict(sample_id='X',predicted_probability=.9,outcome=True,
                 probability_issued_at='2026-10-21T12:00:00+08:00',outcome_at='2026-10-20T12:00:00+08:00')
        with self.assertRaises(ValueError):calibration_summary([row])
        self.assertIsNone(calibration_summary([])['calibrated_probability'])

    def test_reliability_bin_boundaries_do_not_double_count_outcomes(self):
        rows=[dict(sample_id=str(i),predicted_probability=p,outcome=True,
                   probability_issued_at='2026-10-19T00:00:00+08:00',outcome_at='2026-10-20T00:00:00+08:00')
              for i,p in enumerate((0,.2,.4,.6,.8,1))]
        result=calibration_summary(rows,min_samples=5)
        self.assertEqual(sum(b['count'] for b in result['reliability_bins']),6)
        self.assertIsNone(result['calibrated_probability'])


class TrialRegistration(unittest.TestCase):
    def test_registration_cannot_be_rewritten_after_results(self):
        with tempfile.TemporaryDirectory() as t:
            spec=dict(trial_id='test',hypothesis='synthetic only',cost_policy=None)
            first=immutable_registration(t,spec,ASOF)
            self.assertEqual(first,immutable_registration(t,spec,'2026-10-22T12:00:00+08:00'))
            with self.assertRaisesRegex(ValueError,'IMMUTABLE'):immutable_registration(t,dict(spec,cost_policy=COSTS),ASOF)

    def test_trial_without_outcomes_is_pending_not_a_zero_return(self):
        with tempfile.TemporaryDirectory() as t:
            immutable_registration(t,dict(trial_id='test'),ASOF)
            r=collect_trials(t,ASOF)
            self.assertEqual(r['trials'][0]['status'],'AWAITING_FUTURE_OUTCOME_INPUTS')
            self.assertEqual(r['validated_trade_observations'],0)

    def test_unbound_sources_and_unsafe_paths_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'x.json';p.write_text('{}')
            with self.assertRaises(ValueError):source(root,dict(path='x.json',sha256='a'*64))
            with self.assertRaises(ValueError):source(root,dict(path='../x.json',sha256='a'*64))

    def test_shadow_variant_cannot_overwrite_main_ranking(self):
        with self.assertRaisesRegex(ValueError,'SEPARATE_OUTPUT'):run('tw-market-data',ASOF,'2027-12-31',variant='without-earnings-events')


if __name__=='__main__':unittest.main()
