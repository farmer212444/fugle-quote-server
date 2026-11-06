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
import sys

PACKAGE_ROOT=Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:sys.path.insert(0,str(PACKAGE_ROOT))
from tw_model_v880.expected_returns import POLICY
from tw_model_v880.historical_pit import calibration_feasibility


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
        if type(horizon) is not int or horizon <= 0 or horizon in seen:
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
    feasibility=(calibration_feasibility(research['asof_price_date'],research['target_date'],POLICY)
                 if research.get('target_date') else None)
    if feasibility and not feasibility['fixed_target_only_can_satisfy_policy']:
        blockers.append('FIXED_TARGET_ONLY_CANNOT_SUPPLY_INDEPENDENT_ANNUAL_CALIBRATION_COHORTS')
    return dict(schema='EXPECTED_RETURN_READINESS_V1',
        status='NOT_ESTIMABLE_WITH_CURRENT_EVIDENCE',
        source_model=research['model'],
        source_estimate_vintage=research['estimate_vintage'],
        research_price_date=research['asof_price_date'],
        latest_archived_official_price_date=latest_date,
        horizon_evidence=horizons,
        annual_calibration_feasibility=feasibility,
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
    annual_path=root/'rankings/latest_expected_returns.json'
    feasibility=record.get('annual_calibration_feasibility')
    if annual_path.exists() and feasibility:
        annual=json.loads(annual_path.read_bytes())
        context=(annual.get('schema')=='EXPECTED_RETURN_STATUS_V1'
            and annual.get('source_estimate_vintage')==record['source_estimate_vintage']
            and annual.get('source_price_date')==record['research_price_date']
            and annual.get('target_date')==docs['research']['target_date'])
        record['annual_engine_context_matches']=context
        if context:
            annual['annual_calibration_feasibility']=feasibility
            if annual.get('verified_mature_observations')==0 and not annual.get('source_errors'):
                annual['status']='BLOCKED_ANNUAL_CALIBRATION_DESIGN_REQUIRES_HISTORICAL_REPLAY'
            # Reporting-only annotation; do not alter the registered forecasting
            # code, its method identity, frozen cohorts, weights or estimates.
            from scripts.run_research_pipeline import atomic_json
            from scripts.expected_returns import render as render_annual
            atomic_json(annual_path,annual)
            annual_text=render_annual(annual)
            annual_text+='\n校準可行性：固定同一目標日期最多只有1個不重疊持有窗；目前政策要求24個。\n'
            annual_text+=f"原政策的歷史長度下限約 {feasibility['minimum_history_span_years_ignoring_embargo']} 年；此為該研究政策的要求，不是金融學通用門檻。\n"
            annual_text+='只等2027年底到期不能解決；須補歷史PIT重建與獨立時間外驗證協定，不能直接降低門檻湊出數字。\n'
            (root/'rankings/latest_expected_returns.md').write_text(annual_text,encoding='utf-8')
            record['annual_engine_status']=annual['status']
            record['annual_engine_report_sha256']=hashlib.sha256(annual_path.read_bytes()).hexdigest()
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
    feasibility=record.get('annual_calibration_feasibility')
    if feasibility:
        lines+=['## 年度校準可行性','',
            f"目前持有期 {feasibility['holding_calendar_days']} 日；原研究政策至少需要 {feasibility['minimum_total_nonoverlapping_cohorts']} 個不重疊批次。",
            f"固定同一到期日最多只有1個獨立持有窗。原政策的歷史長度下限約 {feasibility['minimum_history_span_years_ignoring_embargo']} 年，還未計隔離期與缺件。",
            '這是前版研究政策的樣本要求，不是金融學通用門檻。只等2027年到期也不能完成校準；需另立歷史PIT重建與時間外驗證協定，不能冒充當年已發出的預測。',
            '沒有降低現有門檻，也沒有將重疊公司／日期湊成獨立樣本。','']
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
