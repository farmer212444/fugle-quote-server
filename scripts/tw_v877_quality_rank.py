#!/usr/bin/env python3
"""V8.7.7.1 quality-gated preliminary Taiwan earnings/valuation screen.

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

def earnings_quality(issuer):
    """Conservative review lane, not a determination of non-recurring gains.

    This compares consolidated operating profit with reported net income,
    which may include non-controlling interests; a low ratio is a *review
    trigger*, never proof of one-off gains or dishonest accounts.
    """
    fy, h1 = issuer['2025-Q4'], issuer['2026-Q2']
    reasons = []
    for label, row in (('FY2025', fy), ('2026H1', h1)):
        operating = numeric(row.get('operating_profit_ytd_k'))
        net = numeric(row.get('net_income_ytd_k'))
        if operating is None or net is None:
            reasons.append(label + ': operating/net income data absent')
            continue
        if operating <= 0:
            reasons.append(label + ': non-positive operating profit')
        if net > 0 and operating / net < 0.35:
            reasons.append(label + ': operating profit <35% of reported net income (audit earnings composition)')
    latest_eps = numeric(h1.get('basic_eps_ytd'))
    if latest_eps is None or latest_eps <= 0:
        reasons.append('2026H1 EPS non-positive or missing; 2027 extrapolation not promotable')
    return reasons


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
    quality_reasons = earnings_quality(issuer)
    # This is a provisional *routing* rule, not a claim about non-recurring income.
    # Exceptional upside itself needs independent price, split and P/E checks.
    if quality_reasons:
        flags.extend('QUALITY_AUDIT: ' + reason for reason in quality_reasons)
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
    exceptional_upside = upside > 150
    if exceptional_upside:
        flags.append('EXTREME_SCENARIO: >150% requires independent valuation, share basis and cycle audit')
    # High headline upside and weak operating earnings are routed to a separate audit ledger.
    research_lane = '獲利品質待查' if quality_reasons else ('高漲幅估值待查' if exceptional_upside else '品質優先研究')
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
        'research_lane':research_lane,'earnings_quality_review':quality_reasons,
        'operating_to_net_2025_ratio':rnd(ratio(b.get('operating_profit_ytd_k'), b.get('net_income_ytd_k')), 3),
        'operating_to_net_2026h1_ratio':rnd(ratio(c.get('operating_profit_ytd_k'), c.get('net_income_ytd_k')), 3),
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
    # Do not promote high EPS driven by unsupported operating economics.
    # Research is NOT investment certification. CAPEX, PIT and diluted shares
    # remain incomplete even for the quality-first lane.
    quality = [x for x in results if x['research_lane'] == '品質優先研究']
    audit = [x for x in results if x['research_lane'] != '品質優先研究']
    quality.sort(key=lambda r:(r['score'], r['scenario_upside_pct']),reverse=True)
    audit.sort(key=lambda r:(r['scenario_upside_pct'],r['score']),reverse=True)
    qualified=[x for x in quality if x['scenario_upside_pct']>=25]
    output={
       'model':'V8.7.7.1 quality-gated research scenario, NOT formal A+',
       'asof_price_date':pm['date'],'revenue_month':rm['period'],
       'financial_last_quarter':fm['last_eligible_quarter'],
       'financial_batches':fm['verified_batches'], 'financial_companies_full_8q':fm['companies_with_full_8Q_income'],
       'research_universe':len(results),'quality_priority_count':len(quality),
       'earnings_or_valuation_audit_count':len(audit),
       'quality_scenarios_ge25':len(qualified),
       'formal_Aplus_count':0,'formal_Aplusplus_count':0,
       'IMPORTANT':'Research scenarios only, not validated expected returns. Low operating-profit/net-income ratios only trigger an audit (net income may include minority interests or recurrent affiliates). External verification of issuer PIT, CAPEX/FCF, diluted shares and P/E is still required.',
       'top30_provisional':quality[:30],
       'top30_quality_priority':quality[:30],
       'top30_audit_required':audit[:30],
    }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'latest_research.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    header=['# V8.7.7.1 獲利品質優先研究排序（非正式 A+）','',
            '低營業利益／淨利比僅代表需要查核獲利來源，不代表認定業外收益皆為一次性。',
            '未驗證 PIT、資本支出、稀釋股數及產業 PE，本表不是買賣訊號，漲幅只是估值情境。','',
            '|研究序|代碼|10/16參考價|品質分數|2027 EPS 情境|PE 假設|情境漲幅|壓力情境|',
            '|---:|---|---:|---:|---:|---:|---:|---:|']
    for i,row in enumerate(quality[:20],1):
        header.append(f"|{i}|{row['code']} {row['name']}|{row['reference_close']}|{row['score']}|{row['eps_2027_base_scenario']}|{row['research_pe_assumption']}|{row['scenario_upside_pct']}%|{row['stress_return_pct']}%|")
    header += ['',f'需要獲利品質／異常估值查核：{len(audit)} 檔（JSON 提供前30檔詳細原因）。',
               '無任何股票通過正式 A+／A++ 全部條件。']
    (OUT/'latest_research.md').write_text('\n'.join(header)+'\n',encoding='utf-8')
    print(json.dumps({'result':'QUALITY_RESEARCH_ONLY','companies_scored':len(results),
      'quality_priority_count':len(quality),'audit_count':len(audit),
      'top_research_codes':[x['code'] for x in quality[:10]],
      'formal_Aplus_count':0},ensure_ascii=False))

def self_test():
    assert clamp(5,0,3)==3
    assert ratio(10,0) is None
    assert numeric('NA') is None
    assert rnd(3.14159)==3.14
    assert len(QUARTERS)==8
    good={q:{} for q in QUARTERS}
    good['2025-Q4']={'operating_profit_ytd_k':679467,'net_income_ytd_k':630121,'basic_eps_ytd':6.6}
    good['2026-Q2']={'operating_profit_ytd_k':742953,'net_income_ytd_k':493536,'basic_eps_ytd':5.16}
    assert earnings_quality(good)==[]
    bad={q:{} for q in QUARTERS}
    bad['2025-Q4']={'operating_profit_ytd_k':-101066,'net_income_ytd_k':1060413,'basic_eps_ytd':11.15}
    bad['2026-Q2']={'operating_profit_ytd_k':4507,'net_income_ytd_k':-22329,'basic_eps_ytd':-0.26}
    assert len(earnings_quality(bad))>=2
    print('SELF_TEST_OK: operating earnings quarantine and fail-closed formal A+')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    self_test() if args.self_test else run()
