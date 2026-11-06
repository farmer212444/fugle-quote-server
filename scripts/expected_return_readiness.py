#!/usr/bin/env python3
"""Fail-closed readiness audit for a 2027 expected-return TOP10.

The existing Base-upside research ranking is not an expected-return ranking.
No probabilities, outcomes or certified labels are synthesized here.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
import sys

PACKAGE_ROOT=Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:sys.path.insert(0,str(PACKAGE_ROOT))
from tw_model_v880.expected_returns import POLICY,RETURN_DEFINITION,STATES
from tw_model_v880.contracts import canonical_hash
from tw_model_v880.portfolio import finite
from tw_model_v880.historical_pit import calibration_feasibility


def annual_context_matches(annual,research):
    return (isinstance(annual,dict) and annual.get('schema')=='EXPECTED_RETURN_STATUS_V1'
        and annual.get('model')==research['model']
        and annual.get('source_estimate_vintage')==research['estimate_vintage']
        and annual.get('source_price_date')==research['asof_price_date']
        and annual.get('target_date')==research.get('target_date'))


def validated_annual_ranking(annual,research):
    """Check the engine's output boundary, never infer probabilities from Base.

    The annual engine remains responsible for original-byte outcome validation,
    frozen cohorts and OOS estimation. This report consumes its matching result
    without rewriting it or changing the registered method identity.
    """
    if not annual_context_matches(annual,research) or annual.get('source_errors'):
        return []
    ranking=annual.get('research_expected_return_ranking')
    if not ranking:return []
    def require(ok):
        if not ok:raise ValueError('EXPECTED_RETURN_ANNUAL_RESULT_NOT_VERIFIABLE')
    require(annual.get('status')=='RESEARCH_ESTIMATES_AFTER_OOS_CHECKS'
        and annual.get('policy')==POLICY and annual.get('return_definition')==RETURN_DEFINITION
        and annual.get('formal_Aplus_added')==0 and annual.get('trade_orders_created')==0)
    require(type(annual.get('verified_mature_observations')) is int
        and annual['verified_mature_observations']>=POLICY['minimum_train_rows']+POLICY['minimum_oos_rows'])
    rows=annual.get('issuer_results');require(isinstance(rows,list))
    lookup={(r.get('market'),r.get('code')):r for r in rows}
    require(len(lookup)==len(rows)==annual.get('universe_rows')==research['data_scope']['model_rows'])
    eligible=[r for r in rows if r.get('expected_net_total_return') is not None]
    require(isinstance(ranking,list) and len(ranking)==len(eligible)
        and len({(r.get('market'),r.get('code')) for r in ranking})==len(ranking))
    for r in ranking:
        require(lookup.get((r.get('market'),r.get('code')))==r
            and r.get('status')=='EMPIRICAL_EXPECTATION_AFTER_OOS_CHECKS_RESEARCH_ONLY'
            and r.get('automatic_deployment') is False and r.get('formal_Aplus_added')==0
            and r.get('research_policy_sha256')==canonical_hash(POLICY)
            and r.get('holding_calendar_days')==(dt.date.fromisoformat(research['target_date'])-dt.date.fromisoformat(research['asof_price_date'])).days)
        diagnostics=r.get('diagnostics',{})
        require(diagnostics.get('diagnostics_passed') is True
            and diagnostics.get('status')=='OOS_DIAGNOSTICS_WITHIN_RESEARCH_POLICY')
        for key,floor in (('oos_cohorts',POLICY['minimum_oos_cohorts']),('oos_rows',POLICY['minimum_oos_rows']),('market_regimes',POLICY['minimum_market_regimes'])):
            require(type(diagnostics.get(key)) is int and diagnostics[key]>=floor)
        for key,reference in (('multiclass_brier','uniform_baseline_brier'),('expected_return_mae','price_only_base_mae')):
            require(finite(diagnostics.get(key)) and finite(diagnostics.get(reference))
                and diagnostics[key]<=diagnostics[reference])
        gap=diagnostics.get('maximum_reliability_gap')
        require(finite(gap) and 0<=gap<=POLICY['maximum_reliability_gap'])
        probabilities=r.get('scenario_probabilities');conditional=r.get('conditional_scenario_means')
        require(isinstance(probabilities,dict) and set(probabilities)==set(STATES)
            and isinstance(conditional,dict) and set(conditional)==set(STATES))
        total=0.
        for state in STATES:
            p=probabilities[state];mean=conditional[state]
            require(finite(p) and 0<=p<=1)
            if p:
                require(isinstance(mean,dict) and finite(mean.get('net_return')))
                total+=p*mean['net_return']
            else:require(mean is None)
        require(math.isclose(sum(probabilities.values()),1.,abs_tol=1e-9)
            and finite(r.get('expected_net_total_return'))
            and math.isclose(total,r['expected_net_total_return'],rel_tol=1e-9,abs_tol=1e-9))
    return sorted(ranking,key=lambda r:(-r['expected_net_total_return'],r['market'],r['code']))


def evaluate(research, returns, price_manifest=None, annual=None):
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
    ranking=validated_annual_ranking(annual,research)
    if ranking:
        # Short-horizon searches are diagnostic evidence, not an extra gate for
        # an annual engine that has passed its own exact-horizon OOS policy.
        blockers=mismatches
    elif annual is not None:
        if not annual_context_matches(annual,research):blockers.append('ANNUAL_ENGINE_REPORT_CONTEXT_MISMATCH')
        elif annual.get('source_errors'):blockers.append('ANNUAL_ENGINE_SOURCE_REJECTIONS_REQUIRE_REPAIR')
    ready=bool(ranking) and not blockers
    return dict(schema='EXPECTED_RETURN_READINESS_V1',
        status='RESEARCH_EXPECTED_RETURN_AVAILABLE' if ready else 'NOT_ESTIMABLE_WITH_CURRENT_EVIDENCE',
        source_model=research['model'],
        source_estimate_vintage=research['estimate_vintage'],
        research_price_date=research['asof_price_date'],
        latest_archived_official_price_date=latest_date,
        horizon_evidence=horizons,
        annual_calibration_feasibility=feasibility,
        blockers=blockers,
        expected_net_return_top10=ranking[:10] if ready else None,
        calibrated_issuer_scenario_probabilities={r['market']+':'+r['code']:r['scenario_probabilities'] for r in ranking[:10]} if ready else None,
        annual_engine_context_matches=annual_context_matches(annual,research),
        annual_engine_status=annual.get('status') if isinstance(annual,dict) else None,
        expected_return_scope='RESEARCH_ONLY_SEPARATE_FROM_FORMAL_APLUS',
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
    annual_path=root/'rankings/latest_expected_returns.json'
    annual=json.loads(annual_path.read_bytes()) if annual_path.exists() else None
    record=evaluate(docs['research'],docs['return_search'],docs['prices'],annual)
    if annual_path.exists():
        sources['annual_engine']=annual_path
        record['annual_engine_report_sha256']=hashlib.sha256(annual_path.read_bytes()).hexdigest()
    record['source_sha256']={key:hashlib.sha256(path.read_bytes()).hexdigest()
                             for key,path in sources.items()}
    text=json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    headline=('**狀態：年度模型已產生通過內部OOS檢查的研究期望淨報酬；正式A+另行認證。**'
              if record['expected_net_return_top10'] else '**狀態：尚不能計算機率加權期望報酬率，沒有正式 TOP10。**')
    lines=['# 2027 期望報酬率 TOP10：證據準備狀態', '',headline, '',
           f"估值模型：{record['source_model']}；估值價格日：{record['research_price_date']}；",
           f"已封存最新官方行情日：{record['latest_archived_official_price_date']}。", '',
           '|持有交易日|驗證的報酬期數|Walk-Forward測試期數|',
           '|---:|---:|---:|']
    for h in record['horizon_evidence']:
        lines.append(f"|{h['holding_sessions']}|{h['verified_return_periods']}|{h['walk_forward_test_periods']}|")
    lines+=['', '## 尚未解除的阻礙', '']
    lines.extend('- '+b for b in record['blockers'])
    if not record['blockers']:lines.append('年度研究政策檢查已通過；不代表正式投資績效或A+認證。')
    if record['expected_net_return_top10']:
        lines+=['','|股票|研究期望淨報酬|','|---|---:|']
        lines += [f"|{r['code']} {r.get('name','')}|{r['expected_net_total_return']:.2%}|" for r in record['expected_net_return_top10']]
    lines+=['', 'Base價差、Bear／Bull情境和EPS／PE壓力測試不是已校準期望值。',
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
