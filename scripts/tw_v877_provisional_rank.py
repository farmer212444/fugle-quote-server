#!/usr/bin/env python3
"""V8.7.7 fail-closed preliminary Taiwan earnings/valuation screen.

Ranks research scenarios, NEVER certifies formal A+/A++ without independent
issuer PIT, CAPEX/FCF, share dilution, historical sector PE and other checks.
No external Python dependencies. Run from the repository root.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import pathlib

ROOT = pathlib.Path('tw-market-data')
OUT = ROOT / 'rankings'
QUARTERS = ['2024-Q3','2024-Q4','2025-Q1','2025-Q2','2025-Q3','2025-Q4','2026-Q1','2026-Q2']
CYCLICAL = ('航運', '鋼鐵', '電器電纜', '建材營造', '電子通路')
MEMORY_RELATED = {'2451','3135','3260','4967','5289','5386','8271','8299'}
SECTOR_PE = {
    '建材營造': 10, '航運業': 9, '鋼鐵工業': 12, '電子通路業': 11,
    '電器電纜': 12, '半導體業': 15, '電腦及週邊設備業': 16,
    '電子零組件業': 15, '綠能環保': 14, '食品工業': 15,
    '運動休閒': 15, '其他電子業': 15, '生技醫療業': 16,
    '數位雲端': 17, '金融保險業': 12, '紡織纖維': 12,
}

def get(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))

def verified_json(path, digest):
    raw = pathlib.Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('SHA256 mismatch: ' + str(path))
    return json.loads(raw)

def numeric(v):
    try:
        x = float(v)
        return x if -1e100 < x < 1e100 else None
    except (TypeError, ValueError):
        return None

def ratio(a,b):
    a, b = numeric(a), numeric(b)
    return a/b if a is not None and b is not None and b!=0 else None

def rnd(v, d=2):
    return round(v,d) if v is not None else None

def clamp(v,low,high):
    return max(low,min(high,v))

def collect():
    fm = get(ROOT/'fundamentals/latest_scan.json')
    if fm['verified_batches'] != 32 or fm['missing_batches'] != 0:
        raise ValueError('32 financial source batches not complete')
    pm = get(ROOT/'prices/latest_manifest.json')
    prices = verified_json(pm['path'],pm['normalized_sha256'])
    if any(p['date'] != pm['date'] for p in prices):
        raise ValueError('Mismatched price dates')
    if len(prices) < 1800:
        raise ValueError('Unusually small price snapshot')
    rm = get(ROOT/'latest_manifest.json')
    if rm.get('period','') > pm['date'][:7]:
        raise ValueError('Revenue publication month cannot be after price month')
    revenues = {}
    for shard in rm['shards']:
        for rec in verified_json(shard['path'],shard['sha256']):
            revenues[str(rec['code'])] = rec
    statements = {}
    for quarter in QUARTERS:
        for market in ('TWSE','TPEX'):
            f = ROOT/'fundamentals'/quarter/(market+'_income.json')
            if not f.exists():
                continue
            obj = get(f)
            if obj['period'] != quarter or obj['market'] != market:
                raise ValueError('Statement period/market mismatch: '+str(f))
            for row in obj['rows']:
                statements.setdefault((market,str(row['code'])),{})[quarter] = row
    cash = {}
    for market in ('TWSE','TPEX'):
        f = ROOT/'fundamentals'/'2026-Q2'/(market+'_cashflow.json')
        if f.exists():
            for row in get(f)['rows']:
                cash[(market,str(row['code']))] = row
    return fm,pm,rm,{(p['market'],str(p['code'])):p for p in prices},revenues,statements,cash

def grade(issuer, price, rev, ocf):
    if any(q not in issuer for q in QUARTERS):
        return None
    a,b,c = (issuer[q] for q in ('2025-Q2','2025-Q4','2026-Q2'))
    eps25,epsh1_25,epsh1_26 = (numeric(x['basic_eps_ytd']) for x in (b,a,c))
    if None in (eps25,epsh1_25,epsh1_26):
        return None
    eps26_raw=eps25-epsh1_25+epsh1_26
    px=numeric(price['close']);liq=px*numeric(price.get('volume_shares')) if px is not None and price.get('volume_shares') is not None else 0
    if not (eps25>0 and eps26_raw>0 and px and px>=8 and liq>=12_000_000):
        return None
    if '*' in (c.get('name') or ''):
        return None # split / altered par value: block until share-based price & EPS reconciled
    r25=numeric(a.get('revenue_ytd_k'));r26=numeric(c.get('revenue_ytd_k'))
    gp25=numeric(a.get('gross_profit_ytd_k'));gp26=numeric(c.get('gross_profit_ytd_k'))
    op25=numeric(a.get('operating_profit_ytd_k'));op26=numeric(c.get('operating_profit_ytd_k'))
    if any(v is None for v in [r25,r26,gp25,gp26,op25,op26]) or min(r25,r26)<=0 or op26<=0:
        return None
    industry=rev.get('industry') if rev else ''
    if industry=='金融保險業':
        return None # banks/insurers need a separate equity-capital and ROE model
    my=numeric(rev.get('monthly_yoy_pct')) if rev else None
    yy=numeric(rev.get('ytd_yoy_pct')) if rev else None
    if my is None or yy is None:
        return None
    gm25,g26=gp25/r25,gp26/r26
    om25,om26=op25/r25,op26/r26
    if not (g26>0 and om26>0):
        return None
    flags=[]
    if my<=0:flags.append('September revenue YoY nonpositive')
    if yy<=0:flags.append('Jan-Sep revenue YoY nonpositive')
    if om26<om25:flags.append('H1 operating margin declined')
    if g26<gm25:flags.append('H1 gross margin declined')
    o=numeric(ocf.get('operating_cashflow_ytd_k')) if ocf else None
    capex=numeric(ocf.get('capex_ytd_k')) if ocf else None
    if o is None:flags.append('operating cash flow unavailable')
    elif o<0:flags.append('negative OCF: examine inventory/capex/receivables; NOT automatic failure')
    if capex is None:flags.append('CAPEX/FCF not verifiable')
    if c.get('diluted_eps_ytd') is None:flags.append('diluted EPS not verifiable')
    if not c.get('company_PIT_verified',False):flags.append('company-specific PIT not verified')
    # Avoid interpreting construction deliveries and peak-cycle profits as permanent.
    cap=1.6 if any(k in industry for k in CYCLICAL) else 2.5
    if c['code'] in MEMORY_RELATED:cap=1.6
    normalized_eps=min(eps26_raw,eps25*cap)
    if normalized_eps!=eps26_raw:flags.append('peak/cyclical EPS normalization applied')
    growth=clamp((yy/100)*0.5,-0.15,0.20)
    if industry=='建材營造':growth=min(growth,0)
    base2027=normalized_eps*(1+growth)
    multiple=SECTOR_PE.get(industry,13)
    if c['code'] in MEMORY_RELATED:multiple=10
    target=base2027*multiple
    upside=(target/px-1)*100
    eps_bear=base2027*.8
    pe_bear=multiple*.8
    downside=(eps_bear*pe_bear/px-1)*100
    score=clamp((30-(px/normalized_eps-8)*2),0,30)
    score+=clamp((g26-gm25)*100*1.4+6,0,14)
    score+=clamp((om26-om25)*100*1.5+6,0,14)
    score+=clamp(my*.15+5,0,14)
    score+=clamp(yy*.14+5,0,14)
    score+=clamp((epsh1_26/epsh1_25-1)*7+4,0,14) if epsh1_25>0 else 0
    if o is not None and o<0:score-=5
    if normalized_eps != eps26_raw:score-=6
    if any(x in industry for x in ('建材營造','航運','鋼鐵')):score-=4
    return {
        'code':c['code'],'name':c['name'],'industry':industry,'reference_close':rnd(px),
        'eps_2025_reported':rnd(eps25),'eps_2026_linear_proxy':rnd(eps26_raw),
        'eps_2026_cycle_normalized':rnd(normalized_eps),'eps_2027_base_scenario':rnd(base2027),
        'research_pe_assumption':multiple,'research_2027_price_scenario':rnd(target),
        'scenario_upside_pct':rnd(upside,1),'stress_return_pct':rnd(downside,1),
        'sep_revenue_yoy_pct':rnd(my,1),'ytd_revenue_yoy_pct':rnd(yy,1),
        'gross_margin_25h1_pct':rnd(gm25*100,1),'gross_margin_26h1_pct':rnd(g26*100,1),
        'oper_margin_25h1_pct':rnd(om25*100,1),'oper_margin_26h1_pct':rnd(om26*100,1),
        'ocf_26h1_ntd_k':o,'capex_26h1_ntd_k':capex,'score':rnd(score,1),
        'warning_flags':flags,'formal_Aplus':False,'formal_Aplusplus':False,
        'rating': '估值待驗（研究情境，非正式 A+）'
    }

def run():
    fm,pm,rm,prices,revs,fin,cfo=collect()
    results=[]
    for key,record in fin.items():
        code=key[1];p=prices.get(key)
        if p:
            row=grade(record,p,revs.get(code),cfo.get(key))
            if row:results.append(row)
    results.sort(key=lambda r:(r['scenario_upside_pct'],r['score']),reverse=True)
    qualified=[x for x in results if x['scenario_upside_pct']>=25]
    output={
       'model':'V8.7.7 research scenario, NOT formal A+','asof_price_date':pm['date'],
       'revenue_month':rm['period'],'financial_last_quarter':fm['last_eligible_quarter'],
       'financial_batches':fm['verified_batches'], 'financial_companies_full_8q':fm['companies_with_full_8Q_income'],
       'research_universe':len(results),'discovery_scenarios_ge25':len(qualified),
       'formal_Aplus_count':0,'formal_Aplusplus_count':0,
       'IMPORTANT':'Estimated upside is NOT validated expected return. P/E is research assumption; EPS proxy has share-dilution and cycle limitations. PIT/capex/FCF checks blocked. Do not treat as trading signal.',
       'top30_provisional':results[:30],
    }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'latest_research.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    header=['# V8.7.7 潛在情境篩選（非正式 A+）','',
            '此為估值**研究假設**，未完成 PIT、股數稀釋、CAPEX/FCF 與產業 PE 驗證，不能當作正式預期報酬率。','',
            '|研究序|代碼|股價|2027 EPS 情境|PE 假設|2027 情境價|情境漲幅|壓力情境|','|---:|---|---:|---:|---:|---:|---:|---:|']
    for i,row in enumerate(results[:20],1):
        header.append(f"|{i}|{row['code']} {row['name']}|{row['reference_close']}|{row['eps_2027_base_scenario']}|{row['research_pe_assumption']}|{row['research_2027_price_scenario']}|{row['scenario_upside_pct']}%|{row['stress_return_pct']}%|")
    (OUT/'latest_research.md').write_text('\n'.join(header)+'\n',encoding='utf-8')
    print(json.dumps({'result':'RESEARCH_ONLY','companies_scored':len(results),'top_research_codes':[x['code'] for x in results[:10]],'formal_Aplus_count':0},ensure_ascii=False))

def self_test():
    assert clamp(5,0,3)==3
    assert ratio(10,0) is None
    assert numeric('NA') is None
    assert rnd(3.14159)==3.14
    assert len(QUARTERS)==8
    print('SELF_TEST_OK: never labels A+/A++ verified')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    self_test() if args.self_test else run()
