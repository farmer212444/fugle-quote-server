"""Finite, registered return hypotheses; chronological fitting never grants A+."""
import datetime as dt
import gzip
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from .contracts import canonical_hash
from .evidence import timestamp
from .portfolio import finite
from .execution import COST_FIELDS

FOLDER='experiments/return_model_search_v1'
FEATURES=('forward_upside_pct','revenue_acceleration_pp','gross_margin_delta_pp','ocf_to_sales','momentum_63_21_pct')


def require(ok,reason):
    if not ok:raise ValueError(reason)


def validate_policy(p):
    require(p.get('schema')=='RETURN_MODEL_SEARCH_POLICY_V1' and p.get('benchmark')=='0050_NET_TOTAL_RETURN'
            and p.get('objective')=='MEAN_NET_LOG_EXCESS_RETURN_WITHIN_SAME_HORIZON'
            and p.get('automatic_deployment') is False,'RETURN_SEARCH_POLICY_UNSUPPORTED')
    require(isinstance(p.get('families'),dict) and p['families'],'RETURN_SEARCH_FAMILIES_MISSING')
    for weights in p['families'].values():
        require(isinstance(weights,dict) and weights and set(weights)<=set(FEATURES)
                and all(finite(v,positive=True) for v in weights.values())
                and abs(sum(weights.values())-1)<1e-12,'RETURN_SEARCH_WEIGHTS_INVALID')
    grid=p['grid']
    for key in ('stock_counts','holding_sessions','minimum_adv20_ntd','sector_caps'):
        values=grid.get(key)
        require(isinstance(values,list) and values and len(values)==len(set(values))
                and all(finite(v,positive=True) for v in values),'RETURN_SEARCH_GRID_INVALID_'+key)
    require(all(type(v) is int and 10<=v<=50 for v in grid['stock_counts'])
            and all(type(v) is int for v in grid['holding_sessions']) and max(grid['sector_caps'])<=1,
            'RETURN_SEARCH_GRID_OUTSIDE_REVIEWED_RANGE')
    for key in ('minimum_train_periods','maximum_train_periods','minimum_oos_periods','minimum_market_regimes','bootstrap_draws','bootstrap_block_size'):
        require(type(p.get(key)) is int and p[key]>0,'RETURN_SEARCH_WINDOW_INVALID_'+key)
    require(p['maximum_train_periods']>=p['minimum_train_periods']
            and type(p.get('embargo_calendar_days')) is int and p['embargo_calendar_days']>=0,'RETURN_SEARCH_TRAIN_OR_EMBARGO_INVALID')
    require(finite(p.get('reference_capital_ntd'),positive=True)
            and finite(p.get('max_daily_participation'),positive=True) and p['max_daily_participation']<=.05
            and finite(p.get('max_training_drawdown'),positive=True) and p['max_training_drawdown']<=1,
            'RETURN_SEARCH_RISK_LIMIT_INVALID')
    require(finite(p.get('stress_cost_multiplier_excluding_tax')) and p['stress_cost_multiplier_excluding_tax']>=1,
            'RETURN_SEARCH_COST_STRESS_INVALID')
    for asset in ('stock','etf'):
        costs=p.get('costs',{}).get(asset,{})
        require(all(finite(costs.get(k)) and 0<=costs[k]<1 for k in COST_FIELDS)
                and costs['sell_fee_rate']+costs['sell_tax_rate']<1
                and finite(costs.get('minimum_fee_ntd')) and costs['minimum_fee_ntd']>=0,'RETURN_SEARCH_COSTS_INVALID_'+asset)
    return p


def parameters(policy):
    validate_policy(policy);g=policy['grid'];rows=[]
    for family,count,horizon,adv,cap in itertools.product(sorted(policy['families']),g['stock_counts'],g['holding_sessions'],g['minimum_adv20_ntd'],g['sector_caps']):
        row=dict(family=family,weights=policy['families'][family],stock_count=count,holding_sessions=horizon,minimum_adv20_ntd=adv,sector_cap=cap)
        row['parameter_id']=canonical_hash(row)[:20];rows.append(row)
    require(len(rows)==len({x['parameter_id'] for x in rows}) and len(rows)<=500,'RETURN_SEARCH_GRID_TOO_LARGE_OR_DUPLICATE')
    return rows


def percentile_ranks(values):
    positions={};ordered=sorted(values)
    for i,value in enumerate(ordered):positions.setdefault(value,[]).append(i)
    return {v:statistics.fmean(indices)/max(1,len(ordered)-1) for v,indices in positions.items()}


def select_portfolio(rows,p,signal_at):
    require(len({(r['market'],r['code']) for r in rows})==len(rows),'RETURN_SEARCH_DUPLICATE_ISSUER')
    eligible=[];excluded=Counter()
    for row in rows:
        reason=None
        if row.get('recommendation_blocked') is True:reason='MATERIAL_GOVERNANCE_BLOCK'
        elif not row.get('industry'):reason='INDUSTRY_UNKNOWN'
        elif not finite(row.get('adv20_ntd'),positive=True) or row['adv20_ntd']<p['minimum_adv20_ntd']:reason='ADV20_MISSING_OR_BELOW_THRESHOLD'
        elif any(not finite(row.get('features',{}).get(f)) for f in p['weights']):reason='REQUIRED_FEATURE_MISSING'
        if reason:excluded[reason]+=1;continue
        require(timestamp(row['feature_available_at'])<=timestamp(signal_at),'RETURN_SEARCH_FUTURE_FEATURE')
        eligible.append(row)
    ranks={f:percentile_ranks([r['features'][f] for r in eligible]) for f in p['weights']}
    scored=[(sum(w*ranks[f][r['features'][f]] for f,w in p['weights'].items()),r) for r in eligible]
    scored.sort(key=lambda x:(-x[0],x[1]['market'],x[1]['code']))
    weight=1/p['stock_count'];positions=[];sectors=Counter()
    for score,row in scored:
        sector=row['industry']
        if sectors[sector]+weight>p['sector_cap']+1e-12:continue
        positions.append(dict(code=row['code'],market=row['market'],industry=sector,weight=weight,score=score));sectors[sector]+=weight
        if len(positions)==p['stock_count']:break
    ready=len(eligible)>=p['stock_count']
    return dict(parameter_id=p['parameter_id'],positions=positions,cash_weight=max(0,1-len(positions)*weight),
                eligible_issuer_count=len(eligible),parameter_inputs_ready=ready,exclusions=dict(excluded),
                status='RESEARCH_PORTFOLIO_FROZEN_NOT_A_BUY_SIGNAL' if ready else 'INPUT_COVERAGE_INCOMPLETE_NOT_A_PERFORMANCE_CANDIDATE',
                missing_feature_is_not_zero_return=True,formal_Aplus_created=0)


def fit_parameters(records,candidates,policy):
    require(candidates and len({p['holding_sessions'] for p in candidates})==1,'RETURN_SEARCH_MIXED_HOLDING_HORIZONS')
    records=records[-policy['maximum_train_periods']:]
    if len(records)<policy['minimum_train_periods']:
        return dict(status='AWAITING_VERIFIED_TRAINING_PERIODS',selected_parameter_id=None,training_periods=len(records),required_periods=policy['minimum_train_periods'])
    scores=[]
    for p in candidates:
        identity=p['parameter_id']
        if not all(identity in r['outcomes'] for r in records):continue
        items=[r['outcomes'][identity] for r in records]
        if any(x['model_max_drawdown']>policy['max_training_drawdown'] or x['net_return']==-1 for x in items):continue
        value=statistics.fmean(math.log1p(x['net_return'])-math.log1p(x['benchmark_net_return']) for x in items)
        scores.append((value,identity))
    if not scores:return dict(status='NO_PARAMETER_WITH_COMPLETE_SHARED_TRAINING_SUPPORT',selected_parameter_id=None,training_periods=len(records))
    scores.sort(key=lambda x:(-x[0],x[1]))
    return dict(status='TRAINING_PICK_NOT_YET_VALIDATED',selected_parameter_id=scores[0][1],training_mean_net_log_excess=scores[0][0],
                training_periods=len(records),evaluated_parameters=len(scores),optimum_or_probability_not_claimed=True)


def walk_forward(records,candidates,policy,asof):
    require(candidates and len({p['holding_sessions'] for p in candidates})==1,'RETURN_SEARCH_MIXED_HOLDING_HORIZONS')
    horizon=candidates[0]['holding_sessions'];ordered=sorted(records,key=lambda r:timestamp(r['signal_at']));previous=None
    for record in ordered:
        require(record.get('holding_sessions')==horizon,'RETURN_SEARCH_OUTCOME_HORIZON_MISMATCH')
        signal,end,verified=(timestamp(record[k]) for k in ('signal_at','exit_at','first_verified_at'))
        require(signal<end<=verified<=timestamp(asof),'RETURN_SEARCH_OUTCOME_CLOCK_INVALID')
        require(previous is None or signal>previous,'RETURN_SEARCH_OVERLAPPING_COHORTS');previous=end
        for item in record['outcomes'].values():
            for key in ('net_return','stress_net_return','benchmark_net_return','stress_benchmark_net_return'):
                require(finite(item.get(key)) and item[key]>=-1,'RETURN_SEARCH_NET_RETURN_INVALID')
            require(item['benchmark_net_return']>-1,'RETURN_SEARCH_BENCHMARK_LOG_UNDEFINED')
            for key in ('model_max_drawdown','benchmark_max_drawdown'):
                require(finite(item.get(key)) and 0<=item[key]<=1,'RETURN_SEARCH_DRAWDOWN_INVALID')
    tests=[];blocked=[]
    def training(cut):
        return [r for r in ordered if timestamp(r['exit_at'])<cut and timestamp(r['first_verified_at'])<cut]
    for current in ordered:
        train=training(timestamp(current['signal_at'])-dt.timedelta(days=policy['embargo_calendar_days']))
        fitted=fit_parameters(train,candidates,policy);identity=fitted['selected_parameter_id']
        if identity is None:continue
        if identity not in current['outcomes']:
            blocked.append(dict(signal_at=current['signal_at'],reason='CHOSEN_PARAMETER_INPUTS_NOT_READY_AT_TEST_SIGNAL'));continue
        tests.append(dict(signal_at=current['signal_at'],exit_at=current['exit_at'],selected_parameter_id=identity,
                          training_periods=fitted['training_periods'],last_training_verified_at=max(r['first_verified_at'] for r in train),**current['outcomes'][identity]))
    latest=fit_parameters(training(timestamp(asof)-dt.timedelta(days=policy['embargo_calendar_days'])),candidates,policy)
    return dict(latest_training_pick=latest,walk_forward_tests=tests,rejected_test_periods=blocked,walk_forward_test_periods=len(tests),
                selection_uses_test_outcomes=False,evidence_supports_0050_edge=False,automatic_deployment=False,formal_Aplus_created=0,trade_orders_created=0)


def load_cohort(path):
    path=Path(path);receipt=json.loads(path.read_bytes());packed=path.with_suffix('.json.gz').read_bytes()
    require(hashlib.sha256(packed).hexdigest()==receipt['gzip_sha256'],'RETURN_SEARCH_COHORT_BYTES_CHANGED')
    doc=json.loads(gzip.decompress(packed));identity=canonical_hash(doc)
    require(identity==receipt['cohort_sha256'] and identity[:24]==receipt['cohort_id'],'RETURN_SEARCH_COHORT_HASH_MISMATCH')
    signal=timestamp(receipt['signal_at'])
    require(timestamp(doc['features_checked_at'])<=signal,'RETURN_SEARCH_FEATURES_AFTER_SIGNAL')
    require(timestamp(doc['estimate_vintage'])<=signal and timestamp(receipt['registered_at'])<=signal,'RETURN_SEARCH_MODEL_OR_REGISTRATION_AFTER_SIGNAL')
    return receipt,doc


def frozen_search_cohorts(root):
    root=Path(root);cohorts=[]
    for path in sorted((root/FOLDER).glob('search-*/cohorts/*/*.json')):
        receipt,doc=load_cohort(path);reg=json.loads((root/FOLDER/'registrations'/(doc['experiment_id']+'.json')).read_bytes())
        require(doc['registration_sha256']==canonical_hash(reg),'RETURN_SEARCH_COHORT_REGISTRATION_CHANGED')
        cohorts.append((receipt,doc))
    return cohorts


def registered_trial_count(root):
    total=0
    for path in sorted((Path(root)/FOLDER/'registrations').glob('*.json')):
        r=json.loads(path.read_bytes());spec=r['spec']
        require(r['spec_sha256']==canonical_hash(spec),'RETURN_SEARCH_REGISTRATION_HASH_MISMATCH')
        rows=parameters(spec['policy']);require(rows==spec['parameters'],'RETURN_SEARCH_REGISTERED_GRID_CHANGED');total+=len(rows)
    return total
