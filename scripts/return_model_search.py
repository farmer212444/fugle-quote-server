#!/usr/bin/env python3
"""Source-recomputed prospective return competition; no fabricated historical list."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.benchmark_sources import load_index,month_range
from scripts.benchmark_validation import market_regime,max_drawdown,reviewed,stress_costs,verified_bars
from scripts.ensure_research_current import ensure_current,full_result_reasons
from scripts.forward_benchmark_sources import verify_month
from scripts.institutional_review import DailyTurnoverSnapshot,liquidity_history
from scripts.run_research_pipeline import atomic_json
from tw_model_v880.contracts import canonical_hash
from tw_model_v880.evidence import timestamp
from tw_model_v880.execution import net_trade
from tw_model_v880.experiments import compare_models
from tw_model_v880.math import number
from tw_model_v880.portfolio import finite
from tw_model_v880.return_search import FEATURES,FOLDER,parameters,require,select_portfolio,walk_forward,load_cohort,frozen_search_cohorts,registered_trial_count
from tw_model_v880.validation_io import source,taipei_signal_date
CONFIG='config/return_model_search_v1.json'


def read(path):return json.loads(Path(path).read_bytes())


def registration(root,policy,research,now):
    dependencies=['scripts/return_model_search.py','tw_model_v880/return_search.py','scripts/benchmark_validation.py',
                  'scripts/benchmark_sources.py','scripts/forward_benchmark_sources.py','scripts/institutional_review.py',
                  'scripts/history_archive.py','scripts/tw_history_backfill.py','scripts/v893_tpex_daily_backfill.py','scripts/execution_quote_archive.py']
    method_sources={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in dependencies}
    spec=dict(policy=policy,parameters=parameters(policy),search_method_sha256=canonical_hash(method_sources),
              search_method_source_hashes=method_sources,source_model_sha256=research['model_code_sha256'])
    identity='search-'+canonical_hash(spec)[:24];path=root/FOLDER/'registrations'/(identity+'.json')
    if path.exists():
        old=read(path);require(old['spec']==spec and old['spec_sha256']==canonical_hash(spec),'RETURN_SEARCH_REGISTERED_PARAMETERS_CHANGED');return old
    result=dict(schema='RETURN_SEARCH_REGISTERED_HYPOTHESES_V1',experiment_id=identity,registered_at=now,spec=spec,spec_sha256=canonical_hash(spec))
    atomic_json(path,result);return result


def calendar(root,asof):
    observed={};months=set();errors=[];cut=timestamp(asof)
    for path in sorted((root/'benchmarks/0050/months').glob('*.json')):
        try:
            doc=read(path);rows=verify_month(root,doc,path.stem,cut)
            checked=timestamp(doc.get('last_source_checked_at_utc',doc['original_archive']['captured_at_utc']))
            if path.stem<taipei_signal_date(asof)[:7]:
                require(checked.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime('%Y-%m')>path.stem,'RETURN_SEARCH_PRIOR_MONTH_CALENDAR_INCOMPLETE')
            for row in rows:
                if timestamp(row['close_at'])<=cut:
                    require(row['date'] not in observed or observed[row['date']]==row,'RETURN_SEARCH_CALENDAR_CONFLICT');observed[row['date']]=row
            months.add(path.stem)
        except (ValueError,KeyError,OSError,TypeError) as exc:errors.append(dict(source=path.as_posix(),reason=str(exc)))
    return observed,months,errors


def holding_dates(cal,months,signal_at,horizon):
    dates=sorted(d for d,b in cal.items() if timestamp(b['open_at'])>timestamp(signal_at))[:horizon]
    if len(dates)<horizon or set(month_range(taipei_signal_date(signal_at),dates[-1]))-months:return None
    return dates


def reviewed_momentum(root,row,asof,cache):
    path=root/'evidence/v880/momentum_reviews'/(row['code']+'.json')
    if not path.exists():return None
    leg=read(path);require((leg['market'],leg['code'])==(row['market'],row['code']),'RETURN_SEARCH_MOMENTUM_ISSUER_MISMATCH')
    raw=source(root,leg['bars']);require(len(raw)==64 and raw[-1]['date']==row['price_date'],'RETURN_SEARCH_MOMENTUM_WINDOW_MISMATCH')
    bars=verified_bars(root,leg,[b['date'] for b in raw],asof,cache);actions=source(root,leg['actions'])
    reviewed(root,leg['corporate_action_review'],leg,bars[0]['date'],bars[-1]['date'],asof,binding_key='actions_sha256',binding=leg['actions']['sha256'])
    first,last=bars[0],bars[-22];shares=1.;cash=0.;seen=set()
    for action in sorted(actions,key=lambda a:timestamp(a['effective_at'])):
        if not timestamp(first['close_at'])<timestamp(action['effective_at'])<=timestamp(last['close_at']):continue
        require(action.get('id') and action['id'] not in seen,'RETURN_SEARCH_MOMENTUM_DUPLICATE_ACTION');seen.add(action['id'])
        if action['type']=='split':
            require(finite(action.get('ratio'),positive=True),'RETURN_SEARCH_MOMENTUM_SPLIT_INVALID');shares*=action['ratio']
        elif action['type']=='cash_dividend':
            require(finite(action.get('per_share')) and action['per_share']>=0,'RETURN_SEARCH_MOMENTUM_DIVIDEND_INVALID');cash+=shares*action['per_share']
        else:raise ValueError('RETURN_SEARCH_MOMENTUM_ACTION_UNSUPPORTED')
    return 100*((shares*last['close']+cash)/first['close']-1)


def feature_rows(root,full,asof):
    daily=DailyTurnoverSnapshot(root,asof,full['asof_price_date']);income={};references={};errors=[];rows=[];cache={};earnings=None
    for row in full['all_model_rows']:
        if not row.get('rankable'):continue
        key=(row['market'],row.get('cashflow_financial_period',full['financial_last_quarter']))
        source_blocked=False
        try:
            if key[1]!=full['financial_last_quarter']:
                # An issuer can publish its cash flow before the marketwide batch.
                # Re-read the original adapter; never divide Q3 cash by Q2 sales.
                from tw_model_v880.events import load_earnings_events
                if earnings is None:earnings,_=load_earnings_events(root,asof,full['financial_last_quarter'])
                event=earnings.get(row['code']);bound=row.get('fresh_earnings_update',{}).get('event') or {}
                require(event is not None and event['event_sha256']==bound.get('event_sha256'),
                        'RETURN_SEARCH_CASH_INCOME_EVENT_NOT_RECONCILED')
                require(event.get('cashflow_period')==key[1] and event['financial_period']==row['financial_period'],
                        'RETURN_SEARCH_CASH_INCOME_EVENT_PERIOD_MISMATCH')
                require(event.get('cashflow',{}).get('ocf_k')==row.get('liquidity',{}).get('ocf_k'),
                        'RETURN_SEARCH_CASH_INCOME_EVENT_AMOUNT_MISMATCH')
                revenue=number(event['current']['revenue_k'])
                references[event['archive_path']]=event['source_sha256']
            else:
                if key not in income:
                    doc=read(root/'fundamentals'/key[1]/(key[0]+'_income.json'))
                    require(doc['period']==key[1] and doc['market']==key[0],'RETURN_SEARCH_INCOME_PERIOD_MISMATCH')
                    income[key]={r['code']:r.get('revenue_ytd_k') for r in doc['rows']}
                revenue=number(income[key].get(row['code']))
        except (ValueError,KeyError,OSError,TypeError) as exc:
            revenue=None;source_blocked=key[1]!=full['financial_last_quarter']
            errors.append(dict(code=row['code'],feature='ocf_to_sales',reason=str(exc)))
        try:
            liq=liquidity_history(root,row,asof,daily);adv=liq['median20_turnover_ntd'] if liq.get('last_date')==row['price_date'] else None
        except (ValueError,KeyError,OSError,TypeError) as exc:
            adv=None;errors.append(dict(code=row['code'],feature='adv20_ntd',reason=str(exc)))
        try:momentum=reviewed_momentum(root,row,asof,cache)
        except (ValueError,KeyError,OSError,TypeError) as exc:
            momentum=None;errors.append(dict(code=row['code'],feature='momentum_63_21_pct',reason=str(exc)))
        trend=row.get('revenue_bridge',{}).get('trend_inputs',{});margin=row.get('margin_bridge',{});ocf=row.get('liquidity',{}).get('ocf_k')
        def difference(a,b):return (a-b)*100 if finite(a) and finite(b) else None
        features=dict(forward_upside_pct=row.get('scenario_upside_pct'),revenue_acceleration_pp=difference(trend.get('latest_month_yoy'),trend.get('monthly_ytd_yoy')),
                      gross_margin_delta_pp=difference(margin.get('current_ytd_gm'),margin.get('prior_ytd_gm')),
                      ocf_to_sales=ocf/revenue if finite(ocf) and finite(revenue,positive=True) else None,momentum_63_21_pct=momentum)
        rows.append(dict(code=row['code'],market=row['market'],industry=row.get('industry'),feature_available_at=asof,features=features,adv20_ntd=adv,
                         recommendation_blocked=row.get('recommendation_blocked',False) or source_blocked,ocf_and_sales_period=key[1],features_are_research_not_quality_certification=True))
        path=root/'prices/issuer_history'/row['market']/(row['code']+'.json')
        if path.exists():references[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return rows,references,errors


def freeze(root,registered,full,features,references,horizon,now,cal,months):
    require(max(timestamp(now),timestamp(registered['registered_at']),timestamp(full['estimate_vintage']))<=dt.datetime.now(dt.timezone.utc),'RETURN_SEARCH_FREEZE_INPUT_FROM_FUTURE')
    folder=root/FOLDER/registered['experiment_id']/'cohorts'/str(horizon);prior=sorted(folder.glob('*.json'))
    if prior:
        receipt,doc=load_cohort(prior[-1]);require(doc['registration_sha256']==canonical_hash(registered),'RETURN_SEARCH_COHORT_REGISTRATION_CHANGED')
        dates=holding_dates(cal,months,receipt['signal_at'],horizon)
        if dates is None or timestamp(cal[dates[-1]]['close_at'])>=timestamp(now):return receipt,doc,False
    path=folder/(taipei_signal_date(now)+'.json')
    if path.exists():return (*load_cohort(path),False)
    candidates=[p for p in registered['spec']['parameters'] if p['holding_sessions']==horizon]
    selections={p['parameter_id']:select_portfolio(features,p,now) for p in candidates}
    doc=dict(schema='RETURN_SEARCH_FROZEN_COHORT_V1',experiment_id=registered['experiment_id'],registration_sha256=canonical_hash(registered),holding_sessions=horizon,
             source_model_sha256=full['model_code_sha256'],estimate_vintage=full['estimate_vintage'],source_price_date=full['asof_price_date'],features_checked_at=now,
             features=features,feature_source_hashes=references,selections=selections,historical_PIT_not_certified=True,formal_Aplus_created=0)
    packed=gzip.compress(json.dumps(doc,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),mtime=0);folder.mkdir(parents=True,exist_ok=True)
    with path.with_suffix('.json.gz').open('xb') as stream:stream.write(packed)
    receipt=dict(cohort_id=canonical_hash(doc)[:24],cohort_sha256=canonical_hash(doc),gzip_sha256=hashlib.sha256(packed).hexdigest(),
                 signal_at=dt.datetime.now(dt.timezone.utc).isoformat(),registered_at=registered['registered_at'],actual_archive_clock_not_backdated=True)
    atomic_json(path,receipt);return receipt,doc,True


def leg_nav(root,leg,dates,signal,asof,budget,costs,participation,cache):
    bars=verified_bars(root,leg,dates,asof,cache);execution=source(root,leg['execution_review'])
    require(timestamp(execution['from'])<=timestamp(bars[0]['open_at']),'RETURN_SEARCH_OPEN_NOT_COVERED_BY_EXECUTION_REVIEW')
    actions=source(root,leg['actions']);reviewed(root,leg['corporate_action_review'],leg,dates[0],dates[-1],asof,binding_key='actions_sha256',binding=leg['actions']['sha256'])
    notional=min(budget/(1+costs['buy_fee_rate']),budget-costs['minimum_fee_ntd']);require(notional>0,'RETURN_SEARCH_INSUFFICIENT_CAPITAL')
    paid=notional+max(notional*costs['buy_fee_rate'],costs['minimum_fee_ntd']);nav=[]
    for i,day in enumerate(dates):
        trade=net_trade(bars[:i+1],actions,signal_at=signal,exit_at=bars[i]['close_at'],costs=costs,corporate_actions_complete=True,
                        requested_notional_ntd=notional,max_participation=participation,entry_execution='NEXT_SESSION_OPEN')
        require(trade['entry_at']==bars[0]['open_at'] and trade['exit_at']==bars[i]['close_at'],'RETURN_SEARCH_EXECUTION_DATE_CHANGED')
        nav.append((budget-paid+paid*(1+trade['net_total_return']))/budget)
    return nav


def outcome(root,registered,receipt,cohort,dates,asof,cache,regime):
    require(len(dates)==cohort['holding_sessions'] and len(set(dates))==len(dates) and dates==sorted(dates),'RETURN_SEARCH_OUTCOME_HOLDING_SESSIONS_MISMATCH')
    path=root/FOLDER/'inputs'/(receipt['cohort_id']+'.json')
    if not path.exists():return None
    payload=read(path);require(payload.get('cohort_sha256')==receipt['cohort_sha256'],'RETURN_SEARCH_OUTCOME_NOT_BOUND_TO_FROZEN_SELECTION')
    ready={k:v for k,v in cohort['selections'].items() if v['parameter_inputs_ready']}
    required={(p['market'],p['code']) for s in ready.values() for p in s['positions']};legs={(l['market'],l['code']):l for l in payload['stock_legs']}
    require(len(legs)==len(payload['stock_legs']) and set(legs)==required,'RETURN_SEARCH_MISSING_OR_EXTRA_SELECTED_STOCK_LEG')
    benchmark=payload['benchmark_leg'];require((benchmark.get('market'),benchmark.get('code'))==('TWSE','0050'),'RETURN_SEARCH_WRONG_BENCHMARK')
    policy=registered['spec']['policy'];capital=policy['reference_capital_ntd'];participation=policy['max_daily_participation']
    bnav=leg_nav(root,benchmark,dates,receipt['signal_at'],asof,capital,policy['costs']['etf'],participation,cache)
    bstress=leg_nav(root,benchmark,dates,receipt['signal_at'],asof,capital,stress_costs(policy['costs']['etf'],policy['stress_cost_multiplier_excluding_tax']),participation,cache)
    params={p['parameter_id']:p for p in registered['spec']['parameters']};values={};nav_cache={}
    for identity,selection in ready.items():
        count=params[identity]['stock_count'];paths=[]
        for stress in (False,True):
            costs=policy['costs']['stock']
            if stress:costs=stress_costs(costs,policy['stress_cost_multiplier_excluding_tax'])
            nav=[selection['cash_weight']]*len(dates)
            for position in selection['positions']:
                key=(position['market'],position['code'],count,stress)
                if key not in nav_cache:nav_cache[key]=leg_nav(root,legs[key[:2]],dates,receipt['signal_at'],asof,capital/count,costs,participation,cache)
                nav=[a+position['weight']*b for a,b in zip(nav,nav_cache[key])]
            paths.append(nav)
        values[identity]=dict(net_return=paths[0][-1]-1,stress_net_return=paths[1][-1]-1,benchmark_net_return=bnav[-1]-1,
            stress_benchmark_net_return=bstress[-1]-1,model_max_drawdown=max_drawdown([1.]+paths[0]),benchmark_max_drawdown=max_drawdown([1.]+bnav),
            market_regime=regime,cash_weight=selection['cash_weight'])
    result=dict(signal_at=receipt['signal_at'],exit_at=source(root,benchmark['bars'])[-1]['close_at'],holding_sessions=cohort['holding_sessions'],outcomes=values,input_sha256=canonical_hash(payload))
    target=root/FOLDER/registered['experiment_id']/'outcomes'/(receipt['cohort_id']+'.json')
    if target.exists():
        prior=read(target);require(all(prior.get(k)==v for k,v in result.items()),'RETURN_SEARCH_PREVIOUS_OUTCOME_REVISED_REVIEW_REQUIRED');return prior
    result['first_verified_at']=dt.datetime.now(dt.timezone.utc).isoformat();atomic_json(target,result);return result


def evaluate(root,registered,cohort,receipt,horizon,cal,months,index,calendar_errors,now,cache):
    policy=registered['spec']['policy'];outcomes=[];pending=[];rejected=[]
    for path in sorted((root/FOLDER/registered['experiment_id']/'cohorts'/str(horizon)).glob('*.json')):
        old_receipt,old=load_cohort(path)
        try:
            dates=holding_dates(cal,months,old_receipt['signal_at'],horizon)
            result=None if dates is None else outcome(root,registered,old_receipt,old,dates,now,cache,market_regime(index,old_receipt['signal_at'],dict(regime_lookback_sessions=63,regime_return_threshold=.03)))
            if result is None:pending.append(dict(cohort_id=old_receipt['cohort_id'],status='AWAITING_FUTURE_HOLDING_SESSIONS_OR_CALENDAR' if dates is None else 'MATURED_AWAITING_REVIEWED_OUTCOME_SOURCES'))
            else:outcomes.append(result)
        except (ValueError,KeyError,TypeError,OSError) as exc:rejected.append(dict(cohort_id=old_receipt['cohort_id'],reason=str(exc)))
    candidates=[p for p in registered['spec']['parameters'] if p['holding_sessions']==horizon]
    report=walk_forward(outcomes,candidates,policy,dt.datetime.now(dt.timezone.utc).isoformat())
    report.update(holding_sessions=horizon,parameter_count=len(candidates),current_cohort=receipt['cohort_id'],
        current_ready_parameter_count=sum(s['parameter_inputs_ready'] for s in cohort['selections'].values()),verified_return_periods=len(outcomes),pending_cohorts=pending,rejected_cohorts=rejected,
        performance_comparison_scope='MATCHED_NONOVERLAPPING_PERIODS_NOT_CONTINUOUS_BUY_AND_HOLD_CAGR',
        current_parameter_readiness=[dict(parameter_id=p['parameter_id'],family=p['family'],stock_count=p['stock_count'],minimum_adv20_ntd=p['minimum_adv20_ntd'],sector_cap=p['sector_cap'],
            eligible_issuer_count=cohort['selections'][p['parameter_id']]['eligible_issuer_count'],selected_issuer_count=len(cohort['selections'][p['parameter_id']]['positions']),
            inputs_ready=cohort['selections'][p['parameter_id']]['parameter_inputs_ready']) for p in candidates])
    tests=report['walk_forward_tests']
    if tests and not any(p['status'].startswith('MATURED') for p in pending) and not rejected and not calendar_errors and not index['errors']:
        pairs=[dict(signal_date=taipei_signal_date(t['signal_at']),signal_at=t['signal_at'],champion_net_return=t['benchmark_net_return'],challenger_net_return=t['net_return'],
            outcome_end_champion=t['exit_at'],outcome_end_challenger=t['exit_at'],champion_frozen_at=registered['registered_at'],challenger_frozen_at=registered['registered_at'],
            execution_and_actions_verified=True,market_regime=t['market_regime'],cost_policy_sha256_champion=canonical_hash(policy['costs']),cost_policy_sha256_challenger=canonical_hash(policy['costs'])) for t in tests]
        trials=registered_trial_count(root)+len(list((root/'experiments/registrations').glob('*.json')))+len(list((root/'experiments/benchmark_registrations').glob('*.json')))
        primary=root/'config/forward_top30_0050_v1.json'
        if primary.exists():trials+=len(read(primary)['predeclared_hold_periods_months'])
        kwargs=dict(trials=max(1,trials),block_size=policy['bootstrap_block_size'],min_dates=policy['minimum_oos_periods'],draws=max(policy['bootstrap_draws'],40*trials))
        inference=compare_models(pairs,**kwargs)
        stress=compare_models([dict(p,champion_net_return=t['stress_benchmark_net_return'],challenger_net_return=t['stress_net_return']) for p,t in zip(pairs,tests)],**kwargs)
        report.update(trial_adjusted_comparison=inference,trial_adjusted_cost_stress_comparison=stress)
        report['evidence_supports_0050_edge']=bool(inference.get('promotion_eligible') and stress.get('promotion_eligible')
            and inference.get('regime_count',0)>=policy['minimum_market_regimes'] and not report['rejected_test_periods']
            and all(t['model_max_drawdown']<=t['benchmark_max_drawdown'] for t in tests))
    return report


def run(root,now=None):
    root=Path(root).resolve();now=now or dt.datetime.now(dt.timezone.utc).isoformat();ensure_current(root,now)
    research=read(root/'rankings/latest_research.json');require(not full_result_reasons(root,research),'RETURN_SEARCH_MODEL_RESULTS_INVALID')
    require(timestamp(research['estimate_vintage'])<=timestamp(now),'RETURN_SEARCH_MODEL_FROM_FUTURE')
    full=json.loads(gzip.decompress((root/'rankings/v880_full_results.json.gz').read_bytes()));policy=read(root/CONFIG);reg=registration(root,policy,research,now)
    features,references,errors=feature_rows(root,full,dt.datetime.now(dt.timezone.utc).isoformat());prepared=dt.datetime.now(dt.timezone.utc).isoformat()
    cal,months,cal_errors=calendar(root,prepared);index=load_index(root,prepared);reports=[];cache={};queue={}
    for horizon in policy['grid']['holding_sessions']:
        receipt,cohort,created=freeze(root,reg,full,features,references,horizon,prepared,cal,months)
        report=evaluate(root,reg,cohort,receipt,horizon,cal,months,index,cal_errors,prepared,cache);report['newly_frozen']=created;reports.append(report)
    for _,cohort in frozen_search_cohorts(root):
        for selection in cohort['selections'].values():
            if selection['parameter_inputs_ready']:
                for p in selection['positions']:queue[(p['market'],p['code'])]=dict(market=p['market'],code=p['code'])
    result=dict(schema='RETURN_MODEL_SEARCH_STATUS_V1',observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),model=research['model'],estimate_vintage=research['estimate_vintage'],
        asof_price_date=research['asof_price_date'],experiment_id=reg['experiment_id'],registered_at=reg['registered_at'],policy_sha256=canonical_hash(policy),
        parameter_count=len(reg['spec']['parameters']),parameters=reg['spec']['parameters'],family_count=len(policy['families']),source_universe_count=len(features),
        feature_coverage={f:sum(finite(r['features'][f]) for r in features) for f in FEATURES},adv20_coverage=sum(finite(r['adv20_ntd'],positive=True) for r in features),
        horizon_reports=reports,feature_source_errors=errors,calendar_errors=cal_errors,regime_source_errors=index['errors'],collection_queue=list(queue.values()),all_registered_search_trials=registered_trial_count(root),
        selected_live_model=None,status='PARAMETER_HYPOTHESES_REGISTERED_AWAITING_VERIFIED_RETURNS' if not any(h['walk_forward_test_periods'] for h in reports) else 'RETURN_MODELS_EVALUATED_REVIEW_REQUIRED',
        formal_Aplus_created=0,trade_orders_created=0,automatic_deployment=False,
        limitations=['Starting weights are hypotheses, not optimal estimates or probabilities.','Current research universe is not certified historical PIT.',
                     'No retrospective August 1 list is created.','Matched nonoverlapping cohort results are not continuous buy-and-hold CAGR.','Engineering tests are not investment performance.'])
    atomic_json(root/'rankings/latest_return_model_search.json',result);(root/'rankings/latest_return_model_search.md').write_text(render(result));return result


def render(r):
    names=dict(valuation='估值',growth='成長',momentum='動能',quality='品質',balanced='綜合')
    labels=dict(forward_upside_pct='預估Base價差',revenue_acceleration_pp='營收加速',gross_margin_delta_pp='毛利率年變動',ocf_to_sales='營業現金流／同期間營收',momentum_63_21_pct='前63日至前21日含息動能')
    lines=['# 以投資報酬選模型：參數競賽','',f"模型 {r['model']}；價格日 {r['asof_price_date']}；候選參數 {r['parameter_count']} 組。",
        '**起始參數待驗；目前未核准任何實盤模型，原有13項品質及治理擋關維持。**','',
        '目標：同持有期內，最大化扣成本後相對0050的平均對數超額報酬；不同持有天數分開選參。',
        '持股10／20／30／50檔；持有21／63／126交易日（含進場日）；20日成交額中位數門檻1,200萬／3,000萬元；產業上限25%／40%。','',
        '|組別|起始特徵權重（待驗）|','|---|---|']
    for family,weights in {p['family']:p['weights'] for p in r['parameters']}.items():lines.append('|'+names[family]+'|'+'、'.join(f'{labels[k]} {v:.0%}' for k,v in weights.items())+'|')
    lines+=['','|持有交易日|參數數|當期可生成候選|已驗證報酬期數|滾動測試期數|','|---:|---:|---:|---:|---:|']
    for h in r['horizon_reports']:lines.append(f"|{h['holding_sessions']}|{h['parameter_count']}|{h['current_ready_parameter_count']}|{h['verified_return_periods']}|{h['walk_forward_test_periods']}|")
    lines+=['','|持股檔數|每一持有期可生成參數組數|','|---:|---:|']
    for count in sorted({p['stock_count'] for p in r['parameters']}):lines.append(f"|{count}|{sum(p['inputs_ready'] for p in r['horizon_reports'][0]['current_parameter_readiness'] if p['stock_count']==count)}|")
    lines+=['','先以12–36個較早、已驗證且不重疊期間選參，隔離5日後再測後續期間。首次驗證時間也必須早於選參訊號。',
        '正式證據須60個不重疊測試期間、至少2種市況、全部試驗數校正及非稅成本加倍壓測；30%訓練回撤上限是明示假設。',
        '買賣手續費各0.1425%、最低20元；股票／ETF賣出稅假設0.3%／0.1%；單邊滑價0.1%加半邊價差0.05%。',
        '缺必要特徵的候選不算報酬、不填0；產業上限留下的現金則明確保留。',
        '動能缺完整原始行情與公司行動審閱時留空。歷史PIT、完整公司行動及可成交性仍須補齊，不回填8月1日事前名單。',
        '這是配對區間研究，沒有冒充連續買入持有CAGR、最佳參數、勝率或已打敗0050。','']
    return '\n'.join(lines)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data-root',default=str(ROOT/'tw-market-data'));args=parser.parse_args();r=run(args.data_root)
    print(json.dumps(dict(parameters=r['parameter_count'],horizons=[dict(sessions=h['holding_sessions'],ready=h['current_ready_parameter_count'],verified=h['verified_return_periods']) for h in r['horizon_reports']],formal_Aplus_created=0)))
