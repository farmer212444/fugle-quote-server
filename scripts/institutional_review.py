#!/usr/bin/env python3
"""Executable issuer review, reverse valuation, risk and forward-observation report."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from tw_model_v880.contracts import canonical_hash,review_work,valuation_diagnostics
from tw_model_v880.evidence import timestamp
from tw_model_v880.forward import forward_observations
from tw_model_v880.portfolio import constrained_portfolio,reverse_execution_capacity,finite
from tw_model_v880.experiments import compare_models,calibration_summary
from tw_model_v880.validation_io import collect_trials,source
from scripts.benchmark_validation import build as build_benchmark_validation


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class DailyTurnoverSnapshot:
    """Read each market session once, scoped to one report and its cutoff.

    No persistent cache: corrections are reread on the next report. Keep raw
    rows by issuer so an invalid date still rejects the affected issuer.
    """
    def __init__(self,root,asof,price_date):
        self.root=Path(root).resolve()
        self.asof=asof
        self.price_date=price_date
        self.rows={}
        self.daily_files_read=0
        self.error=None
        self.day_errors={}
        try:
            manifest=read(self.root/'prices/latest_manifest.json')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.error=str(exc)
            return
        for daily in sorted((self.root/'prices').glob('20??-??-??.json')):
            day=daily.stem
            if day>price_date or day>asof[:10]:
                continue
            try:
                raw=daily.read_bytes()
                self.daily_files_read+=1
                if day==manifest['date'] and hashlib.sha256(raw).hexdigest()!=manifest['normalized_sha256']:
                    raise ValueError('LATEST_LIQUIDITY_MARKET_SOURCE_HASH_MISMATCH')
                bars=json.loads(raw)
                if not isinstance(bars,list) or any(not isinstance(bar,dict) for bar in bars):
                    raise ValueError('LIQUIDITY_MARKET_SOURCE_NOT_A_ROW_LIST')
                for bar in bars:
                    key=(bar.get('market'),bar.get('code'))
                    self.rows.setdefault(key,[]).append((day,bar))
            except (OSError,ValueError,KeyError,TypeError) as exc:
                self.day_errors[day]=str(exc)

    def issuer_rows(self,root,row,asof):
        if (Path(root).resolve()!=self.root or asof!=self.asof
                or row['price_date']>self.price_date):
            raise ValueError('LIQUIDITY_SNAPSHOT_CONTEXT_MISMATCH')
        if self.error is not None:
            raise ValueError(self.error)
        for day,error in sorted(self.day_errors.items()):
            if day<=row['price_date']:
                raise ValueError(error)
        return [(day,bar) for day,bar in self.rows.get((row['market'],row['code']),[])
                if day<=row['price_date']]


def liquidity_history(root,row,asof,daily_snapshot=None):
    path=root/'prices/issuer_history'/row['market']/(row['code']+'.json')
    if not path.exists():
        return dict(status='MULTI_SESSION_TURNOVER_SOURCE_MISSING',median20_turnover_ntd=None)
    obj=read(path)
    if obj.get('issuer')!=row['code'] or obj.get('market')!=row['market']:
        raise ValueError('LIQUIDITY_HISTORY_IDENTITY_MISMATCH')
    observations={}
    for month in obj.get('by_month',{}).values():
        captured=month.get('captured_at_utc')
        if not captured or timestamp(captured)>timestamp(asof):
            continue
        for bar in month.get('rows',[]):
            day=bar['date']
            if day>asof[:10] or day>row['price_date']:
                continue
            turnover=bar.get('turnover_ntd')
            if not finite(turnover) or turnover<0:
                continue
            if day in observations and observations[day]!=turnover:
                raise ValueError('CONFLICTING_TURNOVER_REVISIONS')
            observations[day]=turnover
    # Merge subsequently archived whole-market sessions instead of silently
    # calling a 10/16 window the current 20-day window on 10/20.
    snapshot=daily_snapshot or DailyTurnoverSnapshot(root,asof,row['price_date'])
    for day,bar in snapshot.issuer_rows(root,row,asof):
        if bar.get('date')!=day:raise ValueError('DAILY_LIQUIDITY_DATE_MISMATCH')
        turnover=bar.get('turnover_ntd')
        if not finite(turnover) or turnover<0:continue
        if day in observations and observations[day]!=turnover:raise ValueError('CONFLICTING_MARKET_AND_ISSUER_TURNOVER')
        observations[day]=turnover
    trailing=sorted(observations)[-20:]
    return dict(status='TWENTY_SESSION_TURNOVER_PROXY_NOT_EXECUTION_REVIEW' if len(trailing)==20 else 'LESS_THAN_TWENTY_SESSIONS',
                sessions=len(trailing),first_date=trailing[0] if trailing else None,
                last_date=trailing[-1] if trailing else None,
                median20_turnover_ntd=statistics.median(observations[d] for d in trailing) if len(trailing)==20 else None,
                spread_and_exit_verified=False)


def risk_profile(root,row,asof):
    path=root/'evidence/v880/risk_profiles'/(row['code']+'.json')
    if not path.exists():
        return dict(status='REVIEWED_COMMON_RISK_AND_STRESS_PROFILE_MISSING')
    obj=read(path);cutoff=timestamp(asof)
    if (obj.get('code')!=row['code'] or obj.get('financial_period')!=row['financial_period']
            or obj.get('forecast_input_sha256')!=row.get('forecast_binding',{}).get('forecast_input_sha256')
            or obj.get('review_completed') is not True or not obj.get('reviewer_id')
            or not timestamp(obj['available_at'])<=timestamp(obj['checked_at'])<=cutoff<=timestamp(obj['expires_at'])
            or not obj.get('sources')):
        raise ValueError('RISK_PROFILE_STALE_UNREVIEWED_OR_WRONG_ECONOMIC_INPUTS')
    for original in obj['sources']:
        source(root,original,decode=False)
    return dict(status='REVIEWED_PROFILE_WITH_MATCHING_ORIGINAL_HASHES',
                common_risk_tags=obj.get('common_risk_tags'),
                reviewed_stress_loss_fraction=obj.get('reviewed_stress_loss_fraction'))


def build(root):
    root=Path(root).resolve()
    research=read(root/'rankings/latest_research.json')
    full_path=root/'rankings/v880_full_results.json.gz'
    packed=full_path.read_bytes()
    if hashlib.sha256(packed).hexdigest()!=research['full_results']['sha256']:
        raise ValueError('INSTITUTIONAL_FULL_RESULTS_HASH_MISMATCH')
    raw=gzip.decompress(packed)
    if hashlib.sha256(raw).hexdigest()!=research['full_results']['json_sha256']:
        raise ValueError('INSTITUTIONAL_FULL_RESULTS_JSON_HASH_MISMATCH')
    full=json.loads(raw)
    if full['estimate_vintage']!=research['estimate_vintage'] or full['model']!=research['model']:
        raise ValueError('INSTITUTIONAL_MODEL_VINTAGE_MISMATCH')
    config=read(root/'config/institutional_research.json')
    broad=full['all_market_research']
    focus=broad[:20]+[r for r in full['all_model_rows'] if r['code'] in ('6206','9802') and r not in broad[:20]]
    daily_snapshot=DailyTurnoverSnapshot(root,research['estimate_vintage'],research['asof_price_date'])
    output=[]
    for row in focus:
        try:
            liq=liquidity_history(root,row,research['estimate_vintage'],daily_snapshot)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            liq=dict(status='LIQUIDITY_SOURCE_REJECTED',reason=str(exc),median20_turnover_ntd=None)
        try:
            risk=risk_profile(root,row,research['estimate_vintage'])
        except (OSError,ValueError,KeyError,TypeError) as exc:
            risk=dict(status='RISK_PROFILE_REJECTED',reason=str(exc))
        liq['spread_and_exit_verified']=(row.get('gates',{}).get('tradability',{}).get('status')=='PASS'
                                        and 'tradability' in row.get('certification',{}).get('gates_passed',[]))
        output.append(dict(code=row['code'],market=row['market'],name=row.get('name'),industry=row.get('industry'),
                           base_upside_pct=row.get('scenario_upside_pct'),base=row.get('base'),
                           financial_period=row.get('financial_period'),cashflow_financial_period=row.get('cashflow_financial_period'),
                           valuation_diagnostics=valuation_diagnostics(row),review_work=review_work(row),
                           forecast_binding=row.get('forecast_binding'),fresh_earnings_update=row.get('fresh_earnings_update'),
                           liquidity=liq,capacity_weight_at_reference_capital=reverse_execution_capacity(
                               liq.get('median20_turnover_ntd'),config['reference_capital_ntd'],
                               config['risk_policy']['max_daily_participation'],config['risk_policy']['max_exit_sessions']),
                           formal_Aplus=row.get('formal_Aplus',False),risk_profile=risk,
                           common_risk_tags=risk.get('common_risk_tags'),
                           reviewed_stress_loss_fraction=risk.get('reviewed_stress_loss_fraction'),execution_review=liq))
    # This is a constrained, hypothetical portfolio; missing evidence yields
    # cash rather than an unreviewed stock position or an invented probability.
    portfolio=constrained_portfolio(output,config['reference_capital_ntd'],config['risk_policy'])
    observed_at=dt.datetime.now(dt.timezone.utc).isoformat()
    oos=forward_observations(root,observed_at)
    collected=collect_trials(root,observed_at)
    competitions=[]
    for trial in collected['trials']:
        try:
            comparison=compare_models(trial.get('pairs',[]),trials=max(1,collected['registered_trial_count']),
                                      block_size=config['experiment_policy']['block_size'],
                                      min_dates=config['experiment_policy']['minimum_nonoverlapping_oos_periods'])
            if trial.get('rejected_outcomes'):
                comparison.update(promotion_eligible=False,status='TRIAL_HAS_REJECTED_OUTCOMES_REVIEW_REQUIRED')
            competitions.append(dict(trial_id=trial['trial_id'],**comparison))
        except (ValueError,KeyError,TypeError) as exc:
            competitions.append(dict(trial_id=trial['trial_id'],status='COMPARISON_INPUT_REJECTED',reason=str(exc),promotion_eligible=False))
    return dict(schema='V810_INSTITUTIONAL_RESEARCH_CONTROLS',model=research['model'],
                estimate_vintage=research['estimate_vintage'],report_observed_at=observed_at,asof_price_date=research['asof_price_date'],
                source_model_sha256=research['model_code_sha256'],policy_sha256=canonical_hash(config),
                universe=research['data_scope'],formal_Aplus_count=research['formal_Aplus_count'],
                issuer_reviews=output,portfolio=portfolio,forward_observations=oos,
                model_competition=competitions,validation_inputs=collected,
                benchmark_validation=build_benchmark_validation(root,observed_at),
                probability_validation=calibration_summary(collected['probability_records']),
                scenario_probabilities=None,expected_net_return=None,
                implemented_controls_are_not_evidence_of_investment_outperformance=True,
                operations=dict(existing_schedule_reused=True,trade_orders_created=0,
                                liquidity_daily_files_read=daily_snapshot.daily_files_read,
                                liquidity_snapshot_scope='ONE_REPORT_NO_PERSISTENT_CACHE'))


def render(report):
    lines=[f"# {report['model']} 證據、估值、部位與樣本外觀察",'',
           f"估計：{report['estimate_vintage']}；收盤：{report['asof_price_date']}。",'',
           '逐家公司保留13項原始查核義務，並區分公司、來源、交易及策略層級。部分數值核對不會冒充整項通過。',
           '新自結資料以原始PDF表格重新擷取及勾稽後更新研究EPS；現金流和附註的期間另列。',
           '預測認證綁定經濟輸入與方法，行情每天重算；舊認證仍沿用原先較嚴格規則。','',
           '|股票|Base價差|EPS/PE各-20%|達30%漲幅所需毛利率|20日成交值中位數|',
           '|---|---:|---:|---:|---:|']
    def fmt(value,scale=1,suffix=''):
        return '待補' if value is None else f'{value*scale:.2f}'+suffix
    for row in report['issuer_reviews']:
        diagnostic=row['valuation_diagnostics']
        lines.append(f"|{row['code']} {row['name']}|{fmt(row['base_upside_pct'],suffix='%')}|"
                     f"{fmt(diagnostic.get('eps_pe_each_minus20_upside_pct'),suffix='%')}|"
                     f"{fmt(diagnostic.get('gross_margin_required_for_30pct_upside'),100,'%')}|"
                     f"{fmt(row['liquidity'].get('median20_turnover_ntd'),.0001,'萬元')}|")
    lines+=['','## 新資訊估值修訂','']
    for row in report['issuer_reviews']:
        update=row.get('fresh_earnings_update') or {}
        if update.get('applied'):
            baseline=update.get('baseline_without_new_event',{})
            lines.append(f"- {row['code']}：{row['financial_period']}公司自結原始表格已用於本次研究估值；"
                         f"同一價格／模型、不納入新事件的EPS {fmt(baseline.get('eps'))}、Base {fmt(baseline.get('target_price'))}；"
                         f"更新EPS {fmt(row['base'].get('eps'))}、Base {fmt(row['base'].get('target_price'))}。"
                         f"現金流仍為{row['cashflow_financial_period']}。")
    obs=report['forward_observations']
    lines+=['','## 驗證與部位','',
            f"已封存的獨立訊號日：{obs['distinct_signal_days']}；可認證扣成本總報酬觀測：{obs['verified_net_total_return_observations']}。",
            '同日重跑不增加獨立樣本；後續價格、公司行動、成本與成交證據完整後才可評估正式投資績效。',
            '模型競賽包含時間順序、重疊標籤排除、區塊重抽樣及多次試驗修正；目前樣本不足，不產生勝率或自動升級。',
            '部位引擎限制個股、產業、共同風險、壓力損失及成交參與率；設定為明示的研究假設。',
            f"本次假設資金{report['portfolio']['reference_capital_ntd']:,.0f}元，研究配置現金{report['portfolio']['cash_weight']:.0%}；不代表使用者持倉或實際交易。",'']
    benchmark=report['benchmark_validation']
    lines+=['## 模型與大盤含息基準','',
            f"已登錄大盤比較實驗{benchmark['registered_benchmark_trials']}組；已由原件重算期間{benchmark['verified_outcomes']}個。",
            'Top30等權、下一交易日收盤、21個交易日報酬區間；同期間加權報酬指數含股息，模型扣明示成本。',
            '完整明細見 latest_benchmark_validation.md；未成熟、缺原件或缺公司行動／成交審查均不列為勝過大盤證據。','']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',default='tw-market-data')
    args=parser.parse_args()
    root=Path(args.data_root)
    result=build(root)
    for suffix,content in [('json',json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'),('md',render(result))]:
        (root/'rankings'/('latest_institutional.'+suffix)).write_text(content,encoding='utf-8')
    print(json.dumps(dict(model=result['model'],issuer_reviews=len(result['issuer_reviews']),
                         formal_Aplus=result['formal_Aplus_count'],
                         observed_signal_days=result['forward_observations']['distinct_signal_days'],
                         orders=0),ensure_ascii=False))


if __name__=='__main__':
    main()
