#!/usr/bin/env python3
"""Recompute historical source readiness; never manufacture a PIT backtest.

Dated exchange quotes, issuer filing versions and pre-signal model vintages
are different evidence. Source capture today is not historical publication.
"""
import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

PACKAGE_ROOT=Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:sys.path.insert(0,str(PACKAGE_ROOT))
from scripts.history_archive import verify_original,canonical,digest
from scripts.tw_history_backfill import parse as parse_twse
from scripts.v893_tpex_daily_backfill import parse_daily as parse_tpex
from tw_model_v880.execution import COST_FIELDS
from tw_model_v880.portfolio import finite


def explicit_cost_policy(policy):
    return (isinstance(policy,dict) and
            all(finite(policy.get(name)) and 0<=policy[name]<1 for name in COST_FIELDS) and
            policy['sell_fee_rate']+policy['sell_tax_rate']<1)


def build(root,start_date='2025-01-01'):
    root=Path(root)
    dt.date.fromisoformat(start_date)
    manifest=json.loads((root/'prices/latest_manifest.json').read_text())
    end=manifest['date'];dt.date.fromisoformat(end)
    if start_date>end:raise ValueError('HISTORICAL_WINDOW_REVERSED')
    errors=[];sources={};parsed={};issuer_rows={};sessions=Counter()
    for path in sorted((root/'prices/originals/history').glob('*/*/*.json')):
        try:
            receipt=json.loads(path.read_text())
            ref=dict(receipt,receipt_path=path.relative_to(root).as_posix())
            raw=verify_original(root,ref)
            market,identity=receipt['market'],receipt['identity']
            if market=='TWSE':
                code,month=identity.split('-',1)
                rows=parse_twse(raw,code,month)
            else:
                rows=parse_tpex(raw,identity)
            if digest(canonical(rows))!=receipt['parsed_rows_sha256']:
                raise ValueError('HISTORICAL_PARSED_SOURCE_HASH_MISMATCH')
            parsed[ref['receipt_path']]=rows
            sources[ref['receipt_path']]=ref
        except (ValueError,KeyError,TypeError,OSError,EOFError,AttributeError) as exc:
            errors.append(dict(path=path.relative_to(root).as_posix(),reason=str(exc)))
    # Reparse original HTTP bytes, then compare each issuer's normalized rows;
    # merely possessing a SHA receipt cannot make a modified open executable.
    for market in ('TWSE','TPEX'):
        for path in sorted((root/'prices/issuer_history'/market).glob('*.json')):
            try:
                doc=json.loads(path.read_text());code=path.stem
                if doc.get('issuer')!=code or doc.get('market')!=market:
                    raise ValueError('HISTORICAL_ISSUER_IDENTITY_MISMATCH')
                rows={}
                records=doc.get('by_month',{}).items() if market=='TWSE' else doc.get('by_day',{}).items()
                for period,record in records:
                    ref=record.get('original_archive',{});key=ref.get('receipt_path')
                    if not key:continue
                    if key not in sources or sources[key]!=ref:
                        raise ValueError('HISTORICAL_ORIGINAL_NOT_VERIFIED')
                    identity=code+'-'+period if market=='TWSE' else period
                    if ref['market']!=market or ref['identity']!=identity:
                        raise ValueError('HISTORICAL_ORIGINAL_ISSUER_OR_PERIOD_MISMATCH')
                    if ref['original_response_sha256']!=record.get('original_response_sha256'):
                        raise ValueError('HISTORICAL_NORMALIZED_SOURCE_DIGEST_MISMATCH')
                    if market=='TWSE':
                        expected=[r for r in parsed[key] if r['date']<=doc['price_reference_asof']]
                        if record.get('rows')!=expected:
                            raise ValueError('HISTORICAL_NORMALIZED_ROWS_DIFFER_FROM_ORIGINAL')
                    else:
                        expected=[parsed[key][code]]
                        if record.get('row')!=expected[0] or record.get('date')!=period:
                            raise ValueError('HISTORICAL_NORMALIZED_ROWS_DIFFER_FROM_ORIGINAL')
                    for row in expected:
                        if start_date<=row['date']<=end:
                            if row['date'] in rows and rows[row['date']]!=row:
                                raise ValueError('HISTORICAL_CONFLICTING_SESSION_VERSIONS')
                            rows[row['date']]=row
                if rows:
                    sessions[market]+=len(rows)
                    issuer_rows[(market,code)]=dict(market=market,code=code,source_sessions=len(rows),
                        sessions_with_observed_open=sum(r.get('open') is not None for r in rows.values()),
                        first=min(rows),last=max(rows),fillability_verified=False)
            except (ValueError,KeyError,TypeError,OSError,EOFError,AttributeError) as exc:
                errors.append(dict(path=path.relative_to(root).as_posix(),reason=str(exc)))
    financial=[]
    for path in sorted((root/'fundamentals').glob('*/*_*.json')):
        if not path.name.endswith(('_income.json','_cashflow.json')):continue
        try:
            doc=json.loads(path.read_text())
            financial.append(dict(path=path.relative_to(root).as_posix(),period=doc['period'],
                market=doc['market'],kind=doc['kind'],captured_at=doc.get('capture_utc'),
                historical_publication_and_revision_proof_admitted=False,
                reason='NORMALIZED_MIRROR_IS_NOT_ORIGINAL_FILING_VERSION_OR_PUBLICATION_PROOF'))
        except (ValueError,KeyError,TypeError,OSError) as exc:
            errors.append(dict(path=path.relative_to(root).as_posix(),reason=str(exc)))
    config=json.loads((root/'config/institutional_research.json').read_text())
    policy=config.get('cost_policy')
    blockers=['ISSUER_ORIGINAL_PUBLICATION_AND_REVISION_VERSIONS_REQUIRED',
              'CONTEMPORANEOUS_LISTING_DELISTING_UNIVERSE_REQUIRED',
              'COMPLETE_DIVIDEND_SPLIT_RIGHTS_AND_DELISTING_ACTIONS_REQUIRED',
              'HISTORICAL_EXECUTION_CAPACITY_AND_NEXT_OPEN_REVIEW_REQUIRED',
              'TRAINING_ONLY_MODEL_FIT_AND_HELD_OUT_REPLAY_NOT_COMPLETED']
    policy_ready=explicit_cost_policy(policy)
    if not policy_ready:blockers.append('PROSPECTIVE_COST_POLICY_NOT_FIXED')
    return dict(schema='HISTORICAL_PIT_SOURCE_READINESS_V1',
        observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        historical_start=start_date,historical_end=end,
        verified_durable_original_receipts=len(sources),issuer_price_coverage=list(issuer_rows.values()),
        source_backed_price_sessions_by_market=dict(sessions),financial_mirrors=financial,
        admitted_historical_financial_pit_batches=0,source_rejections=errors,
        retrospective_replay_status='BLOCKED_MISSING_ORIGINAL_PIT_INPUTS',blockers=blockers,
        prospective_cost_policy_fixed=policy_ready,
        historical_reconstruction_is_not_a_prospective_frozen_model=True,
        certified_oos_returns=None,formal_out_of_sample_pass=False,
        formal_Aplus_added=0,existing_collector_schedules_reused=True)


def render(report):
    lines=['# 歷史PIT與樣本外回測：原件回補進度','',
        f"資料範圍：{report['historical_start']}至{report['historical_end']}。",'',
        f"已重新核對永久行情原件 {report['verified_durable_original_receipts']} 份；"
        f"有原件可重算行情的公司 {len(report['issuer_price_coverage'])} 家。",'',
        '歷史行情的實際擷取時間另行保留；它不能替代財報首次公開及修訂版本證據。',
        '目前歷史PIT財報驗收批次0；尚無可認證的歷史樣本外投資績效。','',
        '|股票|原件支持交易日|有開盤價|起日|迄日|', '|---|---:|---:|---|---|']
    for row in report['issuer_price_coverage']:
        lines.append(f"|{row['market']} {row['code']}|{row['source_sessions']}|{row['sessions_with_observed_open']}|{row['first']}|{row['last']}|")
    lines+=['','## 待補的驗證依據','',
        '- 個股原始公告時間、重編時間與對應的當時文件版本。',
        '- 當時上市、下市及停牌母體，避免僅採今天仍存在的公司。',
        '- 完整股利、分割、減資、現增及下市事件。',
        '- 下一開盤、價差、成交限制及清倉能力。',
        '- 只使用訓練期資料選參數，再執行未參與調參的保留期驗證。',
        '- 事前固定交易成本；目前'+('已有明示政策。' if report['prospective_cost_policy_fixed'] else '尚未固定。'),'',
        '歷史重建可用於回溯驗證，但不得回填成當時已封存的模型；本報告不升級正式A+。']
    if report['source_rejections']:
        lines+=['','## 已隔離來源問題','']
        lines += [f"- {row['path']}：{row['reason']}" for row in report['source_rejections']]
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',default='tw-market-data')
    parser.add_argument('--start-date',default='2025-01-01')
    args=parser.parse_args();root=Path(args.data_root)
    result=build(root,args.start_date)
    destination=root/'rankings';destination.mkdir(parents=True,exist_ok=True)
    (destination/'historical_pit_readiness.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (destination/'historical_pit_readiness.md').write_text(render(result))
    print(json.dumps(dict(originals=result['verified_durable_original_receipts'],
        issuers_with_source_backed_prices=len(result['issuer_price_coverage']),
        rejected_sources=len(result['source_rejections']),
        historical_financial_pit_admitted=0,formal_Aplus_added=0)))


if __name__=='__main__':main()
