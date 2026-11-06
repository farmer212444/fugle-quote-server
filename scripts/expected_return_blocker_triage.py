#!/usr/bin/env python3
"""Source-verified blocker triage; never grant PIT PASS or forecast probabilities."""
import argparse
import gzip
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path

def need(ok,why):
    if not ok:raise ValueError(why)

def load(root,name):
    raw=(root/name).read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()

def faults(row):
    values={};errors=[]
    for state in ('bear','base','bull'):
        v=(row.get(state) or {}).get('target_price')
        values[state]=v if type(v) in (int,float) and math.isfinite(v) else None
        if values[state] is None:errors.append('MISSING_OR_NONFINITE_'+state.upper()+'_TARGET')
        elif v<=0:errors.append('NONPOSITIVE_'+state.upper()+'_TARGET')
    if not errors and not values['bear']<values['base']<values['bull']:
        errors.append('BEAR_BASE_BULL_NOT_STRICTLY_ASCENDING')
    return values,errors

def build(root):
    root=Path(root).resolve()
    paths={'research':'rankings/latest_research.json',
           'returns':'rankings/latest_expected_returns.json',
           'history':'rankings/historical_pit_readiness.json'}
    docs={key:load(root,path) for key,path in paths.items()}
    model,returns,history=(docs[k][0] for k in ('research','returns','history'))
    need(model.get('asof_price_date')==returns.get('source_price_date')
         and model.get('estimate_vintage')==returns.get('source_estimate_vintage')
         and model.get('model')==returns.get('model'),'BLOCKER_TRIAGE_VINTAGE_MISMATCH')
    need(history.get('historical_end')==model.get('asof_price_date'),
         'BLOCKER_TRIAGE_HISTORY_DATE_MISMATCH')
    ref=model.get('full_results') or {}
    need(ref.get('path')=='v880_full_results.json.gz','BLOCKER_TRIAGE_REFERENCE_INVALID')
    packed=(root/'rankings'/ref['path']).read_bytes()
    need(hashlib.sha256(packed).hexdigest()==ref.get('sha256'),
         'BLOCKER_TRIAGE_GZIP_HASH_MISMATCH')
    raw=gzip.decompress(packed)
    need(hashlib.sha256(raw).hexdigest()==ref.get('json_sha256'),
         'BLOCKER_TRIAGE_JSON_HASH_MISMATCH')
    rows=json.loads(raw).get('all_model_rows')
    need(isinstance(rows,list) and len(rows)==returns.get('universe_rows'),
         'BLOCKER_TRIAGE_UNIVERSE_MISMATCH')
    keyed={(r['market'],r['code']):r for r in rows}
    need(len(keyed)==len(rows),'BLOCKER_TRIAGE_DUPLICATE_MODEL_ISSUER')
    statuses=returns.get('issuer_results')
    need(isinstance(statuses,list) and len(statuses)==len(rows),
         'BLOCKER_TRIAGE_STATUS_UNIVERSE_MISMATCH')
    need(len({(r['market'],r['code']) for r in statuses})==len(statuses),
         'BLOCKER_TRIAGE_DUPLICATE_STATUS_ISSUER')
    counts=dict(Counter(x['status'] for x in statuses))
    need(counts==returns.get('issuer_status_counts'),'BLOCKER_TRIAGE_STATUS_COUNT_MISMATCH')
    invalid=[]
    for result in statuses:
        if result['status']!='EXPECTED_RETURN_SCENARIOS_INVALID':continue
        k=(result['market'],result['code'])
        need(k in keyed and keyed[k].get('rankable'),'BLOCKER_TRIAGE_INVALID_ISSUER_IDENTITY')
        values,reasons=faults(keyed[k])
        invalid.append(dict(market=k[0],code=k[1],name=result.get('name'),
            target_prices=values,reasons=reasons or ['UNEXPLAINED_SCENARIO_REJECTION_NEEDS_REVIEW'],
            status='REVIEW_ONLY_NO_ESTIMATE'))
    admitted={(x.get('market'),x.get('period'),x.get('kind'))
              for x in history.get('historical_financial_pit_admissions',[])}
    mirrors=[];seen=set()
    for m in history.get('financial_mirrors',[]):
        k=(m.get('market'),m.get('period'),m.get('kind'))
        need(None not in k and k not in seen,'BLOCKER_TRIAGE_DUPLICATE_FINANCIAL_MIRROR')
        seen.add(k)
        if k in admitted:continue
        mirrors.append(dict(market=k[0],period=k[1],kind=k[2],path=m.get('path'),
            required_evidence='OFFICIAL_PUBLICATION_AND_REVISION_VERSION_WITH_NAMED_REVIEW',
            verified_pit=False))
    mirrors.sort(key=lambda x:(x['period'],x['market'],x['kind']))
    return dict(schema='EXPECTED_RETURN_BLOCKER_TRIAGE_V1',
        model=model['model'],asof_price_date=model['asof_price_date'],
        source_sha256={k:v[1] for k,v in docs.items()}|{
            'full_results_gzip':hashlib.sha256(packed).hexdigest()},
        issuer_count=len(rows),issuer_status_counts=counts,
        invalid_scenario_count=len(invalid),invalid_scenario_issuers=invalid,
        existing_historical_original_receipts=history.get('verified_durable_original_receipts'),
        admitted_historical_pit_batches=history.get('admitted_historical_financial_pit_batches'),
        unadmitted_financial_mirrors=mirrors,
        historical_replay_blockers=history.get('blockers',[]),
        verified_mature_returns=returns.get('verified_mature_observations'),
        expected_return_top10=None,formal_Aplus_added=0,orders_created=False)

def render(d):
    lines=['# 2027期望報酬：官方證據缺口與情境錯誤診斷','',
        f"版本：{d['model']}；收盤日：{d['asof_price_date']}。",'',
        f"情境無效：{d['invalid_scenario_count']} 檔；待正式PIT核驗財報鏡像：{len(d['unadmitted_financial_mirrors'])} 批。",'',
        '|股票|Bear|Base|Bull|待查事項|','|---|---:|---:|---:|---|']
    for x in d['invalid_scenario_issuers']:
        def fmt(k):
            v=x['target_prices'][k]
            return '待查' if v is None else f'{v:.2f}'
        lines.append(f"|{x['code']} {x['name']}|{fmt('bear')}|{fmt('base')}|{fmt('bull')}|{', '.join(x['reasons'])}|")
    lines+=['','## 原始公告PIT待辦','',
        '|市場|期別|類別|現有鏡像|','|---|---|---|---|']
    for x in d['unadmitted_financial_mirrors']:
        lines.append(f"|{x['market']}|{x['period']}|{x['kind']}|{x['path']}|")
    lines+=['','SHA收據不能取代歷史首次發布、修訂版本和具名審閱；缺件保持PENDING。',
        '不更改EPS、PE、正式A+認證、估值、期望值或下單。','','## 歷史回放阻礙']
    lines.extend('- '+s for s in d['historical_replay_blockers'])
    return '\n'.join(lines)+'\n'

def publish(root):
    root=Path(root)
    d=build(root)
    out=root/'rankings';out.mkdir(parents=True,exist_ok=True)
    for suffix,body in [('json',json.dumps(d,ensure_ascii=False,indent=2)+'\n'),
                        ('md',render(d))]:
        path=out/('latest_expected_return_blocker_triage.'+suffix)
        fd,temp=tempfile.mkstemp(prefix=path.name+'.',dir=out)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as handle:handle.write(body)
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return d

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',default='tw-market-data')
    r=publish(p.parse_args().data_root)
    print(json.dumps(dict(invalid=r['invalid_scenario_count'],
       pending_pit=len(r['unadmitted_financial_mirrors']),formal_Aplus_added=0)))
