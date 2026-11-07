#!/usr/bin/env python3
"""Seal annual forecasts; derive outcomes only from complete official sources."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from tw_model_v880.contracts import canonical_hash
from tw_model_v880.evidence import timestamp
from tw_model_v880.expected_returns import (POLICY,FOLDER,RETURN_DEFINITION,TAIPEI,
    estimate,frozen_cohorts,prices,require,validate_forecast_at,validate_observations)
from tw_model_v880.portfolio import finite
from tw_model_v880.superforecast import read_record,write_once,digest
from tw_model_v880.validation_io import source
from scripts.benchmark_sources import load_index,month_range
from scripts.benchmark_validation import market_regime,reviewed,verified_bars
from scripts.return_model_search import calendar
from scripts.run_research_pipeline import atomic_json

KEYS = ('market','code','name','industry','reference_close','price_date','estimate_vintage',
        'target_date','forecast_binding','bear','base','bull')


def read(path):
    return json.loads(Path(path).read_bytes())


def sealed(path, body):
    body = dict(body); body['record_sha256'] = digest(body)
    return write_once(path,body)


def load_current(root):
    r = read(root/'rankings/latest_research.json'); ref = r['full_results']
    raw = (root/'rankings/v880_full_results.json.gz').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ref['sha256'],'EXPECTED_RETURN_FULL_GZIP_HASH_MISMATCH')
    unpacked = gzip.decompress(raw)
    require(hashlib.sha256(unpacked).hexdigest() == ref['json_sha256'],'EXPECTED_RETURN_FULL_JSON_HASH_MISMATCH')
    full = json.loads(unpacked); rows = full['all_model_rows']
    require(all(full[k] == r[k] for k in ('model','estimate_vintage','asof_price_date','target_date')),
            'EXPECTED_RETURN_CURRENT_CONTEXT_MISMATCH')
    require(len(rows) == r['data_scope']['model_rows']
            and len({(x['market'],x['code']) for x in rows}) == len(rows),'EXPECTED_RETURN_UNIVERSE_MISMATCH')
    return r,rows


def register(root,costs,notional,now):
    code = (ROOT/'tw_model_v880/expected_returns.py').read_bytes()+Path(__file__).read_bytes()
    spec = dict(policy=POLICY,costs=costs,notional_ntd=notional,
                method_sha256=hashlib.sha256(code).hexdigest(),return_definition=RETURN_DEFINITION)
    identity = canonical_hash(spec); path = root/FOLDER/'registrations'/(identity+'.json')
    if path.exists():
        old = read_record(path)
        require(old['spec'] == spec and old['registration_id'] == identity,'EXPECTED_RETURN_REGISTRATION_CHANGED')
        return old
    return sealed(path,dict(spec=spec,registered_at=now,registration_id=identity))


def freeze(root,research,rows,registration,now):
    instant = timestamp(now); vintage = timestamp(research['estimate_vintage'])
    age = instant.astimezone(TAIPEI).date()-dt.date.fromisoformat(research['asof_price_date'])
    require(0 <= age.days <= 7 and 0 <= (instant-vintage).total_seconds() <= 7*86400,
            'EXPECTED_RETURN_STALE_OR_FUTURE_SOURCE')
    validate_forecast_at(research,now)
    forecasts,excluded = [],[]
    for row in rows:
        try:
            require(row.get('rankable') is True,'NO_COMPARABLE_FORECAST'); prices(row)
            require(row['target_date'] == research['target_date'] and row['estimate_vintage'] == research['estimate_vintage']
                    and row['price_date'] == research['asof_price_date'],'FORECAST_CONTEXT_MISMATCH')
            forecasts.append({k:row[k] for k in KEYS})
        except (ValueError,KeyError,TypeError) as exc:
            excluded.append(dict(market=row['market'],code=row['code'],reason=str(exc)))
    require(bool(forecasts),'EXPECTED_RETURN_NO_VALID_FORECASTS')
    identity = canonical_hash(dict(day=instant.astimezone(TAIPEI).date().isoformat(),
        registration=registration['registration_id'],model=research['model_code_sha256'],target=research['target_date']))
    path = root/FOLDER/'cohorts'/(identity+'.json')
    if path.exists():
        return read_record(path)
    manifest = read(root/'prices/latest_manifest.json')
    require(manifest['date'] == research['asof_price_date'],'EXPECTED_RETURN_PRICE_MANIFEST_MISMATCH')
    ref = dict(path=manifest['path'].removeprefix('tw-market-data/'),sha256=manifest['normalized_sha256'])
    quotes = {(r['market'],r['code']):r for r in source(root,ref)}
    require(all(quotes.get((r['market'],r['code']),{}).get('close') == r['reference_close'] for r in forecasts),
            'EXPECTED_RETURN_REFERENCE_NOT_IN_HASHED_SNAPSHOT')
    return sealed(path,dict(cohort_id=identity,issued_at=now,registration_id=registration['registration_id'],
        registration_sha256=registration['record_sha256'],source_research_sha256=canonical_hash(research),
        source_full_sha256=research['full_results']['sha256'],reference_snapshot=ref,
        target_date=research['target_date'],forecasts=forecasts,exclusions=excluded,
        return_definition=RETURN_DEFINITION,archive_is_not_historic_filing_PIT_certification=True))


def settle(root,cohort,now,cache):
    if timestamp(now).astimezone(TAIPEI).date() <= dt.date.fromisoformat(cohort['target_date']):
        return None
    path = root/FOLDER/'inputs'/(cohort['cohort_id']+'.json')
    if not path.exists():
        return None
    payload = read(path)
    require(payload.get('cohort_sha256') == cohort['record_sha256'],'EXPECTED_RETURN_OUTCOME_NOT_BOUND')
    legs = {(x['market'],x['code']):x for x in payload['stock_legs']}
    require(len(legs) == len(payload['stock_legs']) and set(legs) ==
            {(x['market'],x['code']) for x in cohort['forecasts']},'EXPECTED_RETURN_PARTIAL_OR_EXTRA_OUTCOME_LEGS')
    cal,months,errors = calendar(root,now); require(not errors,'EXPECTED_RETURN_CALENDAR_REJECTED')
    reference = cohort['forecasts'][0]['price_date']
    require(not set(month_range(reference,cohort['target_date']))-months,'EXPECTED_RETURN_CALENDAR_MONTHS_MISSING')
    dates = sorted(d for d in cal if reference <= d <= cohort['target_date'])
    require(dates and dates[0] == reference,'EXPECTED_RETURN_REFERENCE_SESSION_MISSING')
    index = load_index(root,now); require(not index['errors'],'EXPECTED_RETURN_REGIME_INDEX_REJECTED')
    regime = market_regime(index,cohort['issued_at'],dict(regime_lookback_sessions=63,regime_return_threshold=.03))
    require(regime is not None,'EXPECTED_RETURN_REGIME_HISTORY_MISSING')
    regime = 'FLAT' if regime == 'SIDEWAYS' else regime
    records = []
    for f in cohort['forecasts']:
        leg = legs[(f['market'],f['code'])]; bars = verified_bars(root,leg,dates,now,cache)
        require(bars[0]['close'] == f['reference_close'],'EXPECTED_RETURN_REFERENCE_CLOSE_CHANGED')
        actions = source(root,leg['actions'])
        reviewed(root,leg['corporate_action_review'],leg,dates[0],dates[-1],now,
                 binding_key='actions_sha256',binding=leg['actions']['sha256'])
        units,dividends,seen = 1.,0.,set()
        for a in sorted(actions,key=lambda x:timestamp(x['effective_at'])):
            if not timestamp(bars[0]['close_at']) < timestamp(a['effective_at']) <= timestamp(bars[-1]['close_at']):
                continue
            require(a.get('id') and a['id'] not in seen,'EXPECTED_RETURN_DUPLICATE_ACTION');seen.add(a['id'])
            if a['type'] == 'split':
                require(finite(a.get('ratio'),positive=True),'EXPECTED_RETURN_SPLIT_INVALID');units *= a['ratio']
            elif a['type'] == 'cash_dividend':
                require(finite(a.get('per_share')) and a['per_share'] >= 0,'EXPECTED_RETURN_DIVIDEND_INVALID')
                dividends += units*a['per_share']
            else:
                raise ValueError('EXPECTED_RETURN_RIGHTS_OR_DELISTING_REQUIRES_EXPLICIT_RESOLUTION')
        records.append(dict(cohort_id=cohort['cohort_id'],issued_at=cohort['issued_at'],forecast=f,
            exit_at=bars[-1]['close_at'],first_verified_at=now,return_definition=RETURN_DEFINITION,
            terminal_value_per_initial_share=units*bars[-1]['close'],dividends_per_initial_share=dividends,
            market_regime=regime,sources_verified=True,cohort_complete=True))
    validate_observations(records,now)
    result = dict(cohort_sha256=cohort['record_sha256'],input_sha256=canonical_hash(payload),records=records)
    target = root/FOLDER/'outcomes'/(cohort['cohort_id']+'.json')
    if target.exists():
        old = read_record(target)
        require(old['input_sha256'] == result['input_sha256'],'EXPECTED_RETURN_SETTLED_INPUT_REVISED')
        require(len(old['records']) == len(records),'EXPECTED_RETURN_SETTLED_COHORT_CHANGED')
        for new,prior in zip(records,old['records']):
            new['first_verified_at'] = prior['first_verified_at']
        require(result == {k:v for k,v in old.items() if k != 'record_sha256'},'EXPECTED_RETURN_SETTLED_OUTCOME_REVISED')
        return old['records']
    return sealed(target,result)['records']


def run(root,now=None):
    root = Path(root).resolve(); now = now or dt.datetime.now(dt.timezone.utc).isoformat()
    research,rows = load_current(root); config = read(root/'config/institutional_research.json')
    costs,notional = config['cost_policy'],config['reference_capital_ntd']/10
    registration = register(root,costs,notional,now)
    observations,errors,pending,cohorts = [],[],[],[]
    try:
        cohorts = list(frozen_cohorts(root))
    except (ValueError,KeyError,TypeError,OSError) as exc:
        errors.append(dict(stage='cohort_integrity',reason=str(exc)))
    for c in cohorts:
        if c['registration_id'] != registration['registration_id']:
            continue
        try:
            require(timestamp(c['issued_at']) <= timestamp(now),'EXPECTED_RETURN_FUTURE_COHORT')
            result = settle(root,c,now,{})
            if result is None:
                pending.append(dict(cohort_id=c['cohort_id'],target_date=c['target_date'],stocks=len(c['forecasts'])))
            else:
                observations.extend(result)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            errors.append(dict(cohort_id=c['cohort_id'],reason=str(exc)))
    try:
        c = freeze(root,research,rows,registration,now)
        if not any(x['cohort_id'] == c['cohort_id'] for x in pending):
            pending.append(dict(cohort_id=c['cohort_id'],target_date=c['target_date'],stocks=len(c['forecasts'])))
    except (ValueError,KeyError,TypeError,OSError) as exc:
        errors.append(dict(stage='prospective_archive',reason=str(exc)))
    output,statuses = [],Counter()
    for row in rows:
        try:
            require(row.get('rankable') is True,'NO_COMPARABLE_FORECAST')
            require(not errors,'SOURCE_OR_COHORT_REJECTIONS_REQUIRE_REPAIR')
            result = estimate(row,observations,asof=now,costs=costs,notional=notional)
            if row.get('recommendation_blocked'):
                result.update(status='MATERIAL_GOVERNANCE_BLOCK',scenario_probabilities=None,
                              expected_net_total_return=None,annualized_expected_terminal_wealth=None)
        except (ValueError,KeyError,TypeError) as exc:
            result = dict(status=str(exc),scenario_probabilities=None,expected_net_total_return=None)
        statuses[result['status']] += 1
        output.append(dict(market=row['market'],code=row['code'],name=row.get('name'),**result))
    ranking = sorted([r for r in output if r['expected_net_total_return'] is not None],
                     key=lambda r:(-r['expected_net_total_return'],r['market'],r['code']))
    return dict(schema='EXPECTED_RETURN_STATUS_V1',model=research['model'],observed_at=now,
        source_estimate_vintage=research['estimate_vintage'],source_price_date=research['asof_price_date'],
        target_date=research['target_date'],return_definition=RETURN_DEFINITION,
        status='SOURCE_REJECTED' if errors else 'RESEARCH_ESTIMATES_AFTER_OOS_CHECKS' if ranking else 'AWAITING_MATCHED_MATURE_CALIBRATION',
        policy=POLICY,registration_id=registration['registration_id'],registration_sha256=registration['record_sha256'],
        universe_rows=len(rows),comparable_forecasts=sum(r.get('rankable') is True for r in rows),
        verified_mature_observations=len(observations),source_errors=errors,issuer_status_counts=dict(statuses),
        issuer_results=output,research_expected_return_ranking=ranking,pending_cohorts=pending,
        scenario_probabilities=None,expected_net_return=None,existing_schedules_reused=True,
        binary_event_scores_reused_as_stock_return_probabilities=False,formal_Aplus_added=0,trade_orders_created=0)


def render(r):
    lines = ['# 2027 機率加權期望報酬率驗證','',
        f"模型：{r['model']}；來源收盤：{r['source_price_date']}；目標：{r['target_date']}。",'',
        f"狀態：`{r['status']}`；全體 {r['universe_rows']} 筆，研究可估值 {r['comparable_forecasts']} 筆。",
        f"同期限成熟原件樣本：{r['verified_mature_observations']}；可列研究期望報酬率：{len(r['research_expected_return_ranking'])} 檔。",'',
        '期間為參考收盤至目標日，不是 2027 單一曆年績效，也不宣稱已成交。',
        '不套用 25%／50%／25%，不把 Base 價差、會計誤差或二元事件分數當成股票期望報酬。',
        '條件平均與機率取自完整經驗分布，保留虧損及尾部；年化欄為期望期末財富年化，並非年化報酬期望。','',
        '|待補狀態|公司筆數|','|---|---:|']
    lines += [f'|{k}|{v}|' for k,v in r['issuer_status_counts'].items()]
    lines += ['',f"封存佇列：{len(r['pending_cohorts'])} 批；不回填歷史預測。",
        '同方法、同產業及完全相同日數才可校準；不足資料維持空值。',
        '固定研究政策：訓練100筆及12個不重疊批次；樣本外100筆及12批次、20家公司及2種市況。',
        '檢查可靠度、Brier及報酬誤差；均值重抽樣區間不是未來報酬預測區間。原13項正式認證仍另外審查。','']
    lines += ['- 來源待修：'+str(e) for e in r['source_errors']]
    if r['research_expected_return_ranking']:
        lines += ['','|股票|研究期望淨總報酬|','|---|---:|']
        lines += [f"|{x['code']} {x.get('name','')}|{x['expected_net_total_return']:.2%}|" for x in r['research_expected_return_ranking'][:20]]
    return '\n'.join(lines)+'\n'


def main():
    p = argparse.ArgumentParser();p.add_argument('--root',default=str(ROOT/'tw-market-data'));a = p.parse_args()
    root = Path(a.root).resolve();report = run(root)
    atomic_json(root/'rankings/latest_expected_returns.json',report)
    (root/'rankings/latest_expected_returns.md').write_text(render(report),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('status','universe_rows','verified_mature_observations','source_errors')},ensure_ascii=False))
    return int(bool(report['source_errors']))


if __name__ == '__main__':
    raise SystemExit(main())
