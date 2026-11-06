#!/usr/bin/env python3
"""Fail-closed readiness audit for a 2027 expected-return TOP10.

The existing Base-upside research ranking is not an expected-return ranking.
No probabilities, outcomes or certified labels are synthesized here.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path


def evaluate(research, returns, price_manifest=None):
    if not isinstance(research, dict) or not isinstance(returns, dict):
        raise ValueError('EXPECTED_RETURN_INVALID_INPUTS')
    for field in ('model', 'asof_price_date', 'estimate_vintage'):
        if not research.get(field) or research[field] != returns.get(field):
            raise ValueError('EXPECTED_RETURN_VINTAGE_MISMATCH:' + field)
    if research.get('strategy_variant') != 'current-information':
        raise ValueError('EXPECTED_RETURN_NOT_CURRENT_INFORMATION')
    reports = returns.get('horizon_reports')
    if not isinstance(reports, list) or not reports:
        raise ValueError('EXPECTED_RETURN_MISSING_HORIZON_REPORTS')
    horizons = []
    seen = set()
    for entry in reports:
        if not isinstance(entry, dict):
            raise ValueError('EXPECTED_RETURN_MALFORMED_HORIZON')
        horizon = entry.get('holding_sessions')
        verified = entry.get('verified_return_periods')
        walk = entry.get('walk_forward_test_periods')
        if not isinstance(horizon, int) or horizon <= 0 or horizon in seen:
            raise ValueError('EXPECTED_RETURN_INVALID_HORIZON')
        if (type(verified) is not int or verified < 0 or
                type(walk) is not int or walk < 0 or walk > verified):
            raise ValueError('EXPECTED_RETURN_INVALID_PERIOD_COUNTS')
        seen.add(horizon)
        horizons.append(dict(holding_sessions=horizon, verified_return_periods=verified,
                             walk_forward_test_periods=walk))
    latest_date = None
    if price_manifest is not None:
        if not isinstance(price_manifest, dict) or not isinstance(price_manifest.get('date'), str):
            raise ValueError('EXPECTED_RETURN_INVALID_PRICE_MANIFEST')
        try:
            latest_date = dt.date.fromisoformat(price_manifest['date']).isoformat()
            report_date = dt.date.fromisoformat(research['asof_price_date']).isoformat()
        except ValueError as exc:
            raise ValueError('EXPECTED_RETURN_INVALID_SOURCE_DATE') from exc
        if latest_date < report_date:
            raise ValueError('EXPECTED_RETURN_PRICE_MANIFEST_PRECEDES_RESEARCH')
    mismatches=[]
    if latest_date and latest_date != research['asof_price_date']:
        mismatches.append('RESEARCH_PRICE_DATE_OLDER_THAN_LATEST_ARCHIVED_OFFICIAL_CLOSE')
    blockers=['2027_SCENARIO_PROBABILITIES_NOT_VALIDATED',
              'ISSUER_LEVEL_COST_ADJUSTED_EXPECTED_RETURNS_NOT_CALIBRATED']
    if any(h['walk_forward_test_periods'] < 60 for h in horizons):
        blockers.append('INSUFFICIENT_PIT_COST_ADJUSTED_WALK_FORWARD_PERIODS')
    blockers.extend(mismatches)
    return dict(schema='EXPECTED_RETURN_READINESS_V1',
        status='NOT_ESTIMABLE_WITH_CURRENT_EVIDENCE',
        source_model=research['model'],
        source_estimate_vintage=research['estimate_vintage'],
        research_price_date=research['asof_price_date'],
        latest_archived_official_price_date=latest_date,
        horizon_evidence=horizons,
        blockers=blockers,
        expected_net_return_top10=None,
        calibrated_issuer_scenario_probabilities=None,
        base_price_upside_ranking_is_expected_return=False,
        formal_Aplus_status_unchanged=True,
        trading_orders_created=False)


def publish(root):
    root=Path(root)
    sources={
        'research':root/'rankings/latest_research.json',
        'return_search':root/'rankings/latest_return_model_search.json',
        'prices':root/'prices/latest_manifest.json',
    }
    docs={key:json.loads(path.read_bytes()) for key,path in sources.items()}
    record=evaluate(docs['research'],docs['return_search'],docs['prices'])
    record['source_sha256']={key:hashlib.sha256(path.read_bytes()).hexdigest()
                             for key,path in sources.items()}
    text=json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    lines=['# 2027 期望報酬率 TOP10：證據準備狀態', '',
           '**狀態：尚不能計算機率加權期望報酬率，沒有正式 TOP10。**', '',
           f"估值模型：{record['source_model']}；估值價格日：{record['research_price_date']}；",
           f"已封存最新官方行情日：{record['latest_archived_official_price_date']}。", '',
           '|持有交易日|驗證的報酬期數|Walk-Forward測試期數|',
           '|---:|---:|---:|']
    for h in record['horizon_evidence']:
        lines.append(f"|{h['holding_sessions']}|{h['verified_return_periods']}|{h['walk_forward_test_periods']}|")
    lines+=['', '## 尚未解除的阻礙', '']
    lines.extend('- '+b for b in record['blockers'])
    lines+=['', 'Base價差、Bear／Bull情境和雙降20%測試不是已校準期望值。',
             '不更改預測EPS／PE、13項品質認證、正式A+、原始報酬試驗、交易或排程。', '']
    for suffix,output in [('json',text),('md','\n'.join(lines))]:
        dest=root/'rankings'/('latest_expected_return_readiness.'+suffix)
        dest.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=dest.name+'.',dir=dest.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(output)
            os.replace(tmp,dest)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',default='tw-market-data')
    args=parser.parse_args()
    print(json.dumps(publish(args.data_root),ensure_ascii=False))
