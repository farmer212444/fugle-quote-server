#!/usr/bin/env python3
"""Preregister Top30 research selections and compare verified NAV with TAIEX TR.

No historical winner list, manual return, missing leg, or review flag alone can
become an observed return. New model/policy identities start distinct trials.
"""
import argparse
import datetime as dt
import json
import math
import random
import re
import statistics
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.benchmark_sources import close_at,load_index,month_range
from scripts.history_archive import verify_original,canonical,digest
from scripts.run_research_pipeline import atomic_json
from scripts.tw_history_backfill import parse as parse_twse
from scripts.v893_tpex_daily_backfill import parse_daily as parse_tpex
from scripts.v897_freeze_model_vintage import verify_frozen_receipt
from tw_model_v880.contracts import canonical_hash
from tw_model_v880.evidence import timestamp
from tw_model_v880.execution import COST_FIELDS,net_trade
from tw_model_v880.portfolio import finite
from tw_model_v880.validation_io import source,taipei_signal_date

PROTOCOL='TOP30_VS_TAIEX_TR_V1'
SELECTION='RESEARCH_TOP30_EQUAL_WEIGHT_NEXT_SESSION_CLOSE'


def read(path):
    return json.loads(Path(path).read_text())


def immutable(path,document):
    path=Path(path)
    if path.exists():
        old=read(path)
        if old!=document:raise ValueError('BENCHMARK_RECORD_IS_IMMUTABLE')
        return old
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(document,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    return document


def frozen(root,relative):
    path=(root/relative).resolve();rel=Path(relative)
    if rel.is_absolute() or '..' in rel.parts or root not in path.parents:
        raise ValueError('UNSAFE_BENCHMARK_FROZEN_PATH')
    receipt=verify_frozen_receipt(path)
    return receipt,read(path.parent/'latest_research.json')


def validate_spec(spec):
    policy=spec['benchmark_policy'];costs=spec['cost_policy']
    if (spec.get('protocol')!=PROTOCOL or policy.get('benchmark_id')!='TAIEX_TR'
            or policy.get('selection_rule')!=SELECTION or policy.get('number_of_stocks')!=30
            or policy.get('selection_source')!='top30_provisional'
            or policy.get('benchmark_cost_policy')!='COSTLESS_OFFICIAL_GROSS_TOTAL_RETURN_INDEX'
            or policy.get('dividend_policy')!='GROSS_DIVIDENDS_RETAINED_AS_CASH_OR_RECEIVABLE_NO_REINVESTMENT'
            or policy.get('fractional_shares_are_research_assumption') is not True
            or policy.get('automatic_deployment') is not False):
        raise ValueError('UNSUPPORTED_BENCHMARK_PROTOCOL')
    for key in ('holding_intervals','minimum_nonoverlapping_oos_periods','minimum_market_regimes',
                'bootstrap_draws','bootstrap_block_size','regime_lookback_sessions'):
        if type(policy.get(key)) is not int or policy[key]<=0:
            raise ValueError('INVALID_BENCHMARK_POLICY_'+key)
    if (not finite(policy.get('stress_cost_multiplier_excluding_tax'))
            or policy['stress_cost_multiplier_excluding_tax']<1
            or not finite(policy.get('regime_return_threshold'))
            or not 0<policy['regime_return_threshold']<1):
        raise ValueError('INVALID_BENCHMARK_STRESS_OR_REGIME_POLICY')
    for name in COST_FIELDS:
        if not finite(costs.get(name)) or not 0<=costs[name]<1:
            raise ValueError('EXPLICIT_BENCHMARK_COST_REQUIRED_'+name)
    if (costs['sell_fee_rate']+costs['sell_tax_rate']>=1
            or not finite(costs.get('minimum_fee_ntd')) or costs['minimum_fee_ntd']<0
            or not finite(spec.get('reference_capital_ntd'),positive=True)
            or not finite(spec.get('max_daily_participation'),positive=True)
            or not 0<spec['max_daily_participation']<=1
            or not re.fullmatch('[a-f0-9]{64}',spec.get('strategy_variant_sha256',''))):
        raise ValueError('INVALID_BENCHMARK_CAPITAL_COST_OR_STRATEGY')


def window(index,signal_at,intervals):
    """Official sessions, including the entry close plus N held return intervals."""
    day=taipei_signal_date(signal_at)
    later=sorted(d for d in index['rows'] if d>day)
    if not later:return None
    selected=later[:intervals+1]
    missing=set(month_range(day,selected[-1]))-set(index['months'])
    if missing:raise ValueError('BENCHMARK_CALENDAR_MONTHS_MISSING_'+','.join(sorted(missing)))
    if len(selected)<intervals+1:return None
    return selected


def market_regime(index,signal_at,policy):
    eligible=sorted(d for d,r in index['rows'].items() if timestamp(r['close_at'])<timestamp(signal_at))
    n=policy['regime_lookback_sessions']
    if len(eligible)<n+1:return None
    first,last=eligible[-n-1],eligible[-1]
    if set(month_range(first,last))-set(index['months']):return None
    value=index['rows'][last]['level']/index['rows'][first]['level']-1
    threshold=policy['regime_return_threshold']
    return 'UP' if value>threshold else 'DOWN' if value < -threshold else 'SIDEWAYS'


def register(root,receipt_path,now):
    root=Path(root).resolve();timestamp(now)
    receipt,model=frozen(root,receipt_path);config=read(root/'config/institutional_research.json')
    if max(timestamp(receipt['archived_at_utc']),timestamp(receipt['estimate_vintage']))>timestamp(now):
        raise ValueError('FROZEN_MODEL_FROM_FUTURE')
    if (timestamp(now)-timestamp(receipt['estimate_vintage'])).total_seconds()>7*86400:
        raise ValueError('STALE_FROZEN_SELECTION')
    spec=dict(protocol=PROTOCOL,strategy_variant_sha256=receipt['strategy_variant_sha256'],
              model_code_sha256=receipt['model_code_sha256'],model_target_date=model['target_date'],
              cost_policy=config['cost_policy'],benchmark_policy=config['benchmark_policy'],
              reference_capital_ntd=config['reference_capital_ntd'],
              max_daily_participation=config['risk_policy']['max_daily_participation'])
    validate_spec(spec);trial_id='taiex-tr-'+canonical_hash(spec)[:24]
    regpath=root/'experiments/benchmark_registrations'/(trial_id+'.json')
    if regpath.exists():
        registration=read(regpath)
        if registration['spec']!=spec or registration['spec_sha256']!=canonical_hash(spec):
            raise ValueError('BENCHMARK_REGISTRATION_IS_IMMUTABLE')
    else:
        registration=immutable(regpath,dict(schema=PROTOCOL,trial_id=trial_id,registered_at=now,
                                           spec=spec,spec_sha256=canonical_hash(spec)))
    if timestamp(registration['registered_at'])>timestamp(now):
        raise ValueError('BENCHMARK_REGISTRATION_FROM_FUTURE')
    index=load_index(root,now)
    if index['errors']:raise ValueError('BENCHMARK_SOURCE_ERRORS_REQUIRE_REVIEW')
    existing=sorted((root/'experiments/benchmark_cohorts'/trial_id).glob('*.json'))
    prior=[]
    for path in existing:
        cohort=read(path)
        if cohort['cohort_sha256']!=canonical_hash({k:v for k,v in cohort.items() if k!='cohort_sha256'}):
            raise ValueError('BENCHMARK_COHORT_HASH_MISMATCH')
        prior.append(cohort)
    if prior:
        latest=max(prior,key=lambda c:timestamp(c['signal_at']))
        dates=window(index,latest['signal_at'],spec['benchmark_policy']['holding_intervals'])
        if dates is None or timestamp(close_at(dates[-1]))>=timestamp(now):
            return dict(trial_id=trial_id,status='EXISTING_NONOVERLAPPING_COHORT_STILL_OPEN',cohort_id=latest['cohort_id'])
    selected=model.get(spec['benchmark_policy']['selection_source'],[])
    identities=[(r['market'],r['code']) for r in selected]
    if len(identities)!=30 or len(set(identities))!=30:
        raise ValueError('EXACT_FROZEN_TOP30_REQUIRED')
    signal=max(timestamp(now),timestamp(registration['registered_at']),timestamp(receipt['estimate_vintage']),
               timestamp(receipt['archived_at_utc'])).isoformat()
    if timestamp(signal)>timestamp(now):raise ValueError('FROZEN_MODEL_FROM_FUTURE')
    cohort=dict(trial_id=trial_id,registration_sha256=canonical_hash(registration),
                frozen_receipt_path=receipt_path,signal_at=signal,
                market_regime=market_regime(index,signal,spec['benchmark_policy']),
                legs=[dict(market=m,code=c,weight=1/30) for m,c in identities])
    cohort['cohort_id']=canonical_hash(cohort)[:24]
    cohort['cohort_sha256']=canonical_hash(cohort)
    immutable(root/'experiments/benchmark_cohorts'/trial_id/(cohort['cohort_id']+'.json'),cohort)
    return dict(trial_id=trial_id,status='REGISTERED_NEW_RESEARCH_COHORT',cohort_id=cohort['cohort_id'],
                signal_at=signal,formal_Aplus_added=0,trade_orders_created=0)


def reviewed(root,reference,leg,first,last,asof,*,binding_key,binding):
    review=source(root,reference)
    if (review.get('complete') is not True or not review.get('reviewer_id')
            or review.get('code')!=leg['code'] or review.get('market')!=leg['market']
            or review.get(binding_key)!=binding or not review.get('original_sources')
            or timestamp(review['from'])>timestamp(close_at(first))
            or timestamp(review['through'])<timestamp(close_at(last))
            or not timestamp(close_at(last))<=timestamp(review['checked_at'])<=timestamp(asof)):
        raise ValueError('FULL_WINDOW_SOURCE_BOUND_REVIEW_REQUIRED_'+binding_key)
    for ref in review['original_sources']:source(root,ref,decode=False)


def verified_bars(root,leg,dates,asof,cache):
    bars=source(root,leg['bars']);observed={}
    if not leg.get('quote_originals'):raise ValueError('QUOTE_ORIGINAL_BYTES_REQUIRED')
    for ref in leg['quote_originals']:
        key=canonical_hash(ref)
        if key not in cache:
            raw=verify_original(root,ref)
            if timestamp(ref['captured_at_utc'])>timestamp(asof):
                raise ValueError('QUOTE_SOURCE_CAPTURE_AFTER_ASOF')
            if ref['market']=='TWSE':
                code,month=ref['identity'].split('-',1)
                parsed=parse_twse(raw,code,month)
                normalized=parsed
            else:
                normalized=parse_tpex(raw,ref['identity']);parsed=list(normalized.values())
            if digest(canonical(normalized))!=ref['parsed_rows_sha256']:
                raise ValueError('QUOTE_PARSED_ROWS_HASH_MISMATCH')
            if any(timestamp(r['close_at'])>timestamp(ref['captured_at_utc']) for r in parsed):
                raise ValueError('QUOTE_SESSION_AFTER_ORIGINAL_CAPTURE')
            cache[key]=parsed
        for row in cache[key]:
            if row['code']==leg['code'] and row['market']==leg['market']:
                day=row['date']
                if day in observed and observed[day]!=row:raise ValueError('CONFLICTING_QUOTE_ORIGINALS')
                observed[day]=row
    if (not isinstance(bars,list) or [b.get('date') for b in bars]!=dates
            or any(b.get('code')!=leg['code'] or b.get('market')!=leg['market'] for b in bars)):
        raise ValueError('MISSING_DUPLICATE_OR_WRONG_PORTFOLIO_SESSIONS')
    fields=('code','market','date','open','high','low','close','turnover_ntd','open_at','close_at')
    for bar in bars:
        original=observed.get(bar['date'],{})
        if any(bar.get(k)!=original.get(k) for k in fields):
            raise ValueError('EXECUTION_BARS_DIFFER_FROM_OFFICIAL_ORIGINALS')
    reviewed(root,leg['execution_review'],leg,dates[0],dates[-1],asof,
             binding_key='bars_sha256',binding=leg['bars']['sha256'])
    return bars


def stress_costs(costs,multiplier):
    return {key:value if key=='sell_tax_rate' else value*multiplier for key,value in costs.items()}


def outcome(root,registration,cohort,index,asof,cache):
    spec=registration['spec'];policy=spec['benchmark_policy']
    if (cohort.get('registration_sha256')!=canonical_hash(registration)
            or cohort.get('cohort_sha256')!=canonical_hash({k:v for k,v in cohort.items() if k!='cohort_sha256'})
            or cohort.get('trial_id')!=registration['trial_id']):
        raise ValueError('BENCHMARK_COHORT_REGISTRATION_OR_HASH_MISMATCH')
    receipt,model=frozen(root,cohort['frozen_receipt_path'])
    signal=timestamp(cohort['signal_at'])
    if (not timestamp(registration['registered_at'])<=signal<=timestamp(asof)
            or max(timestamp(receipt['archived_at_utc']),timestamp(receipt['estimate_vintage']))>signal
            or receipt.get('strategy_variant_sha256')!=spec['strategy_variant_sha256']
            or model['target_date']!=spec['model_target_date']):
        raise ValueError('MODEL_NOT_FROZEN_BEFORE_SIGNAL_OR_WRONG_STRATEGY')
    required=[(r['market'],r['code']) for r in model.get(policy['selection_source'],[])]
    if (len(required)!=30 or len(set(required))!=30
            or [(r['market'],r['code']) for r in cohort['legs']]!=required
            or any(r.get('weight')!=1/30 for r in cohort['legs'])):
        raise ValueError('WINNER_SELECTION_OR_MISSING_FROZEN_TOP30_LEGS')
    dates=window(index,cohort['signal_at'],policy['holding_intervals'])
    if dates is None:return dict(status='AWAITING_FUTURE_HOLDING_SESSIONS',cohort_id=cohort['cohort_id'])
    path=root/'experiments/benchmark_inputs'/(cohort['cohort_id']+'.json')
    if not path.exists():return dict(status='MATURED_AWAITING_REVIEWED_OUTCOME_SOURCES',cohort_id=cohort['cohort_id'],dates=dates)
    payload=read(path)
    if payload.get('cohort_sha256')!=canonical_hash(cohort):raise ValueError('OUTCOME_INPUT_NOT_BOUND_TO_COHORT')
    legs=payload['legs'];identities=[(r['market'],r['code']) for r in legs]
    if len(legs)!=30 or set(identities)!=set(required) or len(set(identities))!=30:
        raise ValueError('WINNER_SELECTION_OR_MISSING_FROZEN_TOP30_LEGS')
    paths=[[],[]];entry_at=close_at(dates[0]);exit_at=close_at(dates[-1])
    policies=[spec['cost_policy'],stress_costs(spec['cost_policy'],policy['stress_cost_multiplier_excluding_tax'])]
    for leg in legs:
        bars=verified_bars(root,leg,dates,asof,cache);actions=source(root,leg['actions'])
        reviewed(root,leg['corporate_action_review'],leg,dates[0],dates[-1],asof,
                 binding_key='actions_sha256',binding=leg['actions']['sha256'])
        for i,costs in enumerate(policies):
            budget=spec['reference_capital_ntd']/30
            notional=min(budget/(1+costs['buy_fee_rate']),budget-costs['minimum_fee_ntd'])
            if notional<=0:raise ValueError('CAPITAL_INSUFFICIENT_FOR_MINIMUM_FEES')
            nav=[]
            for n,day in enumerate(dates):
                trade=net_trade(bars[:n+1],actions,signal_at=cohort['signal_at'],exit_at=close_at(day),
                                costs=costs,corporate_actions_complete=True,requested_notional_ntd=notional,
                                max_participation=spec['max_daily_participation'],entry_execution='NEXT_SESSION_CLOSE')
                if trade['entry_at']!=entry_at or trade['exit_at']!=close_at(day):
                    raise ValueError('STRATEGY_AND_BENCHMARK_EXECUTION_CLOCKS_DIFFER')
                nav.append(1+trade['net_total_return'])
            paths[i].append(nav)
    navs=[[statistics.fmean(p[n] for p in paths[i]) for n in range(len(dates))] for i in (0,1)]
    base=index['rows'][dates[0]]['level']
    regime=market_regime(index,cohort['signal_at'],policy)
    if cohort.get('market_regime') is not None and cohort['market_regime']!=regime:
        raise ValueError('PRE_SIGNAL_REGIME_SOURCE_CHANGED_REVIEW_REQUIRED')
    return dict(status='SOURCE_RECOMPUTED_RESEARCH_OUTCOME',cohort_id=cohort['cohort_id'],
                dates=dates,entry_at=entry_at,exit_at=exit_at,market_regime=regime,
                model_nav=navs[0],stress_nav=navs[1],
                benchmark_nav=[index['rows'][d]['level']/base for d in dates],
                net_total_return=navs[0][-1]-1,stress_net_total_return=navs[1][-1]-1,
                benchmark_total_return=index['rows'][dates[-1]]['level']/base-1,
                formal_out_of_sample_pass=False)


def max_drawdown(values):
    peak=1.;worst=0.
    for value in values:
        peak=max(peak,value);worst=max(worst,1-value/peak)
    return worst


def summarize(outcomes,index,policy,trials):
    """Continuous benchmark across cash gaps; daily NAV, not cohort endpoint DD."""
    rows=sorted(outcomes,key=lambda r:r['entry_at'])
    if not rows:return dict(status='NO_VERIFIED_OUTCOMES',verified_nonoverlapping_periods=0,
                            model_total_return=None,benchmark_total_return=None,excess_return_pp=None,
                            evidence_supports_benchmark_edge=False,formal_out_of_sample_pass=False)
    previous=None;model={};stressed={};wealth=stress_wealth=1.
    for row in rows:
        if previous is not None and timestamp(row['entry_at'])<=timestamp(previous):
            raise ValueError('OVERLAPPING_BENCHMARK_COHORTS')
        for day,value,stress in zip(row['dates'],row['model_nav'],row['stress_nav']):
            model[day]=wealth*value;stressed[day]=stress_wealth*stress
        wealth*=1+row['net_total_return'];stress_wealth*=1+row['stress_net_total_return'];previous=row['exit_at']
    first,last=rows[0]['dates'][0],rows[-1]['dates'][-1]
    if set(month_range(first,last))-set(index['months']):raise ValueError('CONTINUOUS_BENCHMARK_MONTHS_MISSING')
    dates=sorted(d for d in index['rows'] if first<=d<=last)
    # Before each next entry the strategy remains cash; index stays invested.
    nav=[1.];stress_nav=[1.];benchmark=[1.];current=stress_current=1.
    base=index['rows'][first]['level']
    for day in dates:
        current=model.get(day,current);stress_current=stressed.get(day,stress_current)
        nav.append(current);stress_nav.append(stress_current);benchmark.append(index['rows'][day]['level']/base)
    model_dd=max_drawdown(nav);benchmark_dd=max_drawdown(benchmark)
    enough=len(rows)>=policy['minimum_nonoverlapping_oos_periods']
    labels=[r.get('market_regime') for r in rows];regimes={x for x in labels if x}
    coverage=all(labels);bounds=[None,None]
    draws=policy['bootstrap_draws'];block=policy['bootstrap_block_size']
    resolvable=trials<=draws*.025
    if enough and resolvable and min(nav+stress_nav)>0:
        # Paired, circular moving blocks of daily log relative wealth changes.
        diffs=[[math.log(values[n]/values[n-1])-math.log(benchmark[n]/benchmark[n-1])
                for n in range(1,len(values))] for values in (nav,stress_nav)]
        rng=random.Random(8103);samples=[[],[]];count=len(dates)
        for _ in range(draws):
            chosen=[]
            while len(chosen)<count:
                start=rng.randrange(count);chosen.extend((start+j)%count for j in range(block))
            chosen=chosen[:count]
            for k in (0,1):samples[k].append(statistics.fmean(diffs[k][n] for n in chosen))
        for k in (0,1):
            samples[k].sort();bounds[k]=samples[k][max(0,int(draws*.025/trials)-1)]
    benchmark_return=benchmark[-1]-1
    support=(enough and coverage and len(regimes)>=policy['minimum_market_regimes']
             and bounds[0] is not None and min(bounds)>0 and wealth>benchmark[-1]
             and stress_wealth>benchmark[-1] and model_dd<=benchmark_dd+1e-12)
    return dict(status='DESCRIPTIVE_VERIFIED_RESEARCH_PERFORMANCE',verified_nonoverlapping_periods=len(rows),
                required_nonoverlapping_periods=policy['minimum_nonoverlapping_oos_periods'],
                first_entry=first,last_exit=last,daily_nav_observations=len(dates),
                model_total_return=wealth-1,stress_model_total_return=stress_wealth-1,
                benchmark_total_return=benchmark_return,excess_return_pp=(wealth-benchmark[-1])*100,
                model_max_drawdown=model_dd,benchmark_max_drawdown=benchmark_dd,
                period_win_rate=statistics.fmean(r['net_total_return']>r['benchmark_total_return'] for r in rows),
                regime_count=len(regimes),regime_coverage_complete=coverage,
                trial_adjusted_daily_log_excess_lower_bound=bounds[0],stress_lower_bound=bounds[1],
                declared_trials=trials,bootstrap_draws=draws,block_size=block,
                inference='PAIRED_DAILY_LOG_RELATIVE_RETURN_CIRCULAR_BLOCK_BOOTSTRAP_BONFERRONI',
                daily_observations_are_not_independent_cohorts=True,
                benchmark_includes_returns_during_strategy_cash_gaps=True,
                evidence_supports_benchmark_edge=bool(support),formal_out_of_sample_pass=False,
                research_selection_does_not_certify_issuer_quality=True,automatic_deployment=False)


def build(root,asof):
    root=Path(root).resolve();index=load_index(root,asof);trials=[];queue={};cache={};needed_months=set()
    paths=sorted((root/'experiments/benchmark_registrations').glob('*.json'))
    # Count every registered design, including prior model comparisons.
    trial_count=len(paths)+len(list((root/'experiments/registrations').glob('*.json')))
    primary_policy=root/'config/forward_top30_0050_v1.json'
    if primary_policy.exists():
        # Preserve the separate primary-original Top30/0050 experiment and
        # count its predeclared horizons rather than cherry-picking a winner.
        trial_count+=len(read(primary_policy)['predeclared_hold_periods_months'])
    for path in paths:
        results=[];errors=[];registration=None
        try:
            registration=read(path);spec=registration['spec'];validate_spec(spec)
            if (registration.get('schema')!=PROTOCOL or registration['spec_sha256']!=canonical_hash(spec)
                    or registration['trial_id']!=path.stem):raise ValueError('BENCHMARK_REGISTRATION_HASH_MISMATCH')
            if timestamp(registration['registered_at'])>timestamp(asof):continue
            for cp in sorted((root/'experiments/benchmark_cohorts'/path.stem).glob('*.json')):
                cohort=read(cp)
                if timestamp(cohort['signal_at'])>timestamp(asof):continue
                # A fixed lagged-price rule can be resolved after a source
                # outage using only closes strictly before the signal.
                lag_start=(timestamp(cohort['signal_at']).date()-dt.timedelta(days=180)).isoformat()
                needed_months.update(set(month_range(lag_start,asof[:10]))-set(index['months']))
                try:
                    result=outcome(root,registration,cohort,index,asof,cache)
                    results.append(result)
                except (OSError,ValueError,KeyError,TypeError,EOFError) as exc:
                    errors.append(dict(cohort_id=cp.stem,reason=str(exc)))
                    result=None
                if result is None or result['status']!='SOURCE_RECOMPUTED_RESEARCH_OUTCOME':
                    for leg in cohort['legs']:
                        key=(leg['market'],leg['code'])
                        queue.setdefault(key,dict(market=key[0],code=key[1],cohort_ids=[]))['cohort_ids'].append(cohort['cohort_id'])
            valid=[r for r in results if r['status']=='SOURCE_RECOMPUTED_RESEARCH_OUTCOME']
            summary=summarize(valid,index,spec['benchmark_policy'],max(1,trial_count))
            missing=sum(r['status']=='MATURED_AWAITING_REVIEWED_OUTCOME_SOURCES' for r in results)
            if errors or missing or index['errors']:summary['evidence_supports_benchmark_edge']=False
            trials.append(dict(trial_id=path.stem,registered_at=registration['registered_at'],spec=spec,
                               outcomes=results,rejected_outcomes=errors,matured_unusable_periods=missing,
                               **summary))
        except (OSError,ValueError,KeyError,TypeError,EOFError) as exc:
            trials.append(dict(trial_id=path.stem,status='BENCHMARK_INPUTS_REJECTED',reason=str(exc),
                               evidence_supports_benchmark_edge=False,formal_out_of_sample_pass=False))
    return dict(schema=PROTOCOL,observed_at=asof,benchmark_id='TAIEX_TR',trials=trials,
                registered_benchmark_trials=len(paths),all_registered_designs=trial_count,
                verified_outcomes=sum(len([r for r in t.get('outcomes',[]) if r['status']=='SOURCE_RECOMPUTED_RESEARCH_OUTCOME']) for t in trials),
                benchmark_sessions=len(index['rows']),benchmark_months=sorted(index['months']),source_errors=index['errors'],
                collection_queue=list(queue.values()),
                benchmark_months_required=sorted(needed_months),
                missing_for_certified_historical_replay=[
                    'Original issuer publication/revision versions before each historical signal',
                    'Contemporaneous listings/delistings and original model training vintages',
                    'Dated monthly revenue releases, issued shares, CB terms and historical valuation inputs',
                    'Complete source-bound corporate actions and execution/fillability reviews'],
                formal_Aplus_added=0,formal_out_of_sample_pass=False,trade_orders_created=0)


def render(report):
    lines=['# 模型與大盤含息比較','',f"查核時間：{report['observed_at']}。",'',
           '研究Top30等權；訊號後下一交易日收盤進場，持有21個交易日報酬區間。',
           '加權報酬指數包含股息再投資且不扣交易成本；模型保留股息為現金／應收款，扣手續費、證交稅、價差與滑價。',
           '每組名單事前封存；尚未結束的持有期不另開重疊樣本；新版本另立實驗。',
           '連續大盤報酬包含模型持有現金空檔；回撤使用每日淨清算資產。',
           '60個不重疊期間、至少2種事前定義市況、試驗數校正後信賴下限及成本壓測是預先指定驗收政策，不是最適參數。','',
           '|實驗|已驗證期間|模型含息淨報酬|大盤含息報酬|超額百分點|有足夠勝過大盤證據|',
           '|---|---:|---:|---:|---:|---|']
    def fmt(value,scale=100):return '尚無' if value is None else f'{value*scale:.2f}'
    for trial in report['trials']:
        lines.append(f"|{trial['trial_id']}|{trial.get('verified_nonoverlapping_periods',0)}|"
                     f"{fmt(trial.get('model_total_return'))}%|{fmt(trial.get('benchmark_total_return'))}%|"
                     f"{fmt(trial.get('excess_return_pp'),1)}|{trial.get('evidence_supports_benchmark_edge',False)}|")
    lines+=['',f"行情待回補或持續蒐集公司：{len(report['collection_queue'])}家；已重算觀測：{report['verified_outcomes']}。",
            '完整歷史PIT財報、當時上市下市母體、公司行動與可成交性審查仍須補齊。',
            '本報告不核發正式A+，不產生券商委託；程式驗證成功不等於投資績效通過。','']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',default='tw-market-data')
    p.add_argument('--register-receipt');args=p.parse_args();root=Path(args.data_root)
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    if args.register_receipt:print(json.dumps(register(root,args.register_receipt,now),ensure_ascii=False))
    report=build(root,now);atomic_json(root/'rankings/latest_benchmark_validation.json',report)
    (root/'rankings/latest_benchmark_validation.md').write_text(render(report))
    print(json.dumps(dict(registered=report['registered_benchmark_trials'],verified=report['verified_outcomes'],
                          source_errors=len(report['source_errors']),trade_orders_created=0),ensure_ascii=False))


if __name__=='__main__':main()
