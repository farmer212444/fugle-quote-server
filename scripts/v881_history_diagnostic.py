#!/usr/bin/env python3
"""Historical gross-margin signal diagnostic (NOT equity-return or true PIT backtest).

Observes 2025/2026 Q1 low-margin signals vs next quarter standalone gross margin.
Accounts for cumulative-YTD filings. Marks future-data/PIT/seasonality limitations.
No guessed investment performance and no automatic A+ promotion.
"""
import argparse,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880 import VERSION

PERIODS=('2024-Q4','2025-Q1','2025-Q2','2025-Q4','2026-Q1','2026-Q2')

def _ratio(row):
    rev=row.get('revenue_ytd_k');gp=row.get('gross_profit_ytd_k')
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (rev,gp)) or rev<=0:return None
    margin=gp/rev
    return margin if 0<=margin<=1 else None

def _standalone_gm(q1,h1):
    if not q1 or not h1:return None
    v=[q1.get('revenue_ytd_k'),q1.get('gross_profit_ytd_k'),
       h1.get('revenue_ytd_k'),h1.get('gross_profit_ytd_k')]
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v):
        return None
    rev=h1['revenue_ytd_k']-q1['revenue_ytd_k']
    gp=h1['gross_profit_ytd_k']-q1['gross_profit_ytd_k']
    if rev<=0:return None
    g=gp/rev
    return g if math.isfinite(g) and 0<=g<=1 else None

def load(root):
    items={}
    for period in PERIODS:
        for market in ('TWSE','TPEX'):
            path=root/'fundamentals'/period/f'{market}_income.json'
            if not path.exists():continue
            obj=json.loads(path.read_text(encoding='utf-8'))
            if obj.get('period')!=period or obj.get('market')!=market or obj.get('kind')!='income':
                raise ValueError('HISTORICAL_BATCH_MISMATCH:'+str(path))
            for row in obj['rows']:
                code=str(row['code'])
                if len(code)!=4 or not code.isascii() or not code.isdigit():continue
                key=(market,code);d=items.setdefault(key,dict(code=code,name=row.get('name',''),market=market,periods={}))
                if period in d['periods']:raise ValueError('DUPLICATE_HISTORICAL_ROW')
                d['periods'][period]=row
    return list(items.values())

def observe(item,year):
    r=item['periods']
    prev,q1,h1=(r.get(f'{year-1}-Q4'),r.get(f'{year}-Q1'),r.get(f'{year}-Q2'))
    if not prev or not q1 or not h1:return None
    fy=_ratio(prev);one=_ratio(q1);two=_standalone_gm(q1,h1)
    if None in (fy,one,two):return None
    oldq1=r.get(f'{year-1}-Q1');oldq2=r.get(f'{year-1}-Q2')
    yoy=None;sa=None
    prior_rev=oldq1.get('revenue_ytd_k') if oldq1 else None
    if isinstance(prior_rev,(int,float)) and math.isfinite(prior_rev) and prior_rev>0:
        yoy=q1['revenue_ytd_k']/prior_rev-1
    if oldq1 and oldq2 and _ratio(oldq1) is not None and _standalone_gm(oldq1,oldq2) is not None:
        sa=(two-one)-(_standalone_gm(oldq1,oldq2)-_ratio(oldq1))
    return dict(code=item['code'],name=item['name'],year=year,
                low_gm=(fy-one)>=.02,baseline_fy_gm=fy,q1_gm=one,q2_standalone_gm=two,
                q2_change_pp=(two-one)*100,
                q1_revenue_yoy_pct=yoy*100 if yoy is not None else None,
                seasonal_adjusted_q2_change_pp=sa*100 if sa is not None else None,
                issuer_PIT_verified=False)

def stats(rows,field='q2_change_pp'):
    vals=[r[field] for r in rows if r.get(field) is not None and math.isfinite(r[field])]
    if not vals:return dict(n=0,improved_n=0,improved_pct=None,median_change_pp=None)
    return dict(n=len(vals),improved_n=sum(x>0 for x in vals),
                improved_pct=round(100*sum(x>0 for x in vals)/len(vals),1),
                median_change_pp=round(statistics.median(vals),2))

def analyze(items):
    records={year:[v for item in items if (v:=observe(item,year)) is not None] for year in (2025,2026)}
    yearly={}
    for y,all_rows in records.items():
        low=[r for r in all_rows if r['low_gm'] and '*' not in r['name']]
        yearly[str(y)]=dict(all_valid=stats(all_rows),low_gm=stats(low),
                           signal='PREV_FY_GM_MINUS_CURRENT_Q1_GM_GE_2PP')
    cohort=[r for r in records[2026] if r['low_gm'] and '*' not in r['name'] and r['q1_revenue_yoy_pct'] is not None
        and r['seasonal_adjusted_q2_change_pp'] is not None]
    high=[r for r in cohort if r['q1_revenue_yoy_pct']>=10]
    low=[r for r in cohort if r['q1_revenue_yoy_pct']<10]
    result=dict(model=VERSION+' historical accounting diagnostic',asof_data='2026-10-19',
                exact_v881_margin_normalization_backtest=False,
                reason='The current V8.8.1 2027 normalization uses two completed FY plus 2026H1 and September 2026 revenue. '
                       'No later actual financial year exists. This is a prior-year/Q1-to-Q2 signal proxy.',
                earliest_available_full_year=2024,
                yearly=yearly,
                cohort_2026=dict(growth_10pct=stats(high),
                                 below_growth_10pct=stats(low),
                                 growth_10pct_season_adjusted=stats(high,'seasonal_adjusted_q2_change_pp'),
                                 below_growth_10pct_season_adjusted=stats(low,'seasonal_adjusted_q2_change_pp')),
                model_2023_to_2025_stock_returns=None,
                vs_taiex_alpha=None,
                historical_Aplus_pick_rate=None,
                formal_stock_return_backtest_passed=False,
                limitations=[
                   'Missing pre-2024-Q3 eight-quarter comparable operating histories',
                   'No issuer-specific historical original filing and revision timestamps',
                   'No pre-signal historical forecast vintages nor price/execution/corporate-action archive',
                   'Current normalized backfill can include historical revisions',
                   'Q1-to-Q2 margin proxy is not next-year FY gross-margin recovery',
                   'FY/Q1 earnings are available at different company-specific timestamps',
                   'Selection/regression-to-mean and sector composition not controlled',
                ])
    return result

def report(p):
    annual=p['yearly'];co=p['cohort_2026']
    txt=['# V8.8.1 歷史驗證：基本面訊號（非投資績效）','',
         '此表使用已保存的年度與季報重建，不能冒充個股公告當時的已凍結估值或實際交易績效。',
         '訊號：Q1 毛利率比上年度全年低至少 2 個百分點，觀察下一季單季毛利率是否高於 Q1。','',
         '| 觀察年 | 有效公司 | 低毛利公司 | 低毛利改善率 | 低毛利改善中位數 | 全體改善率 |',
         '|---|---:|---:|---:|---:|---:|']
    for y,d in annual.items():
        a,b=d['all_valid'],d['low_gm']
        txt.append(f"| {y} | {a['n']} | {b['n']} | {b['improved_pct']:.1f}% | {b['median_change_pp']:+.2f} pp | {a['improved_pct']:.1f}% |")
    txt+=['','## 2026 同期對照：Q1 營收年增率是否有辨識力','',
          '|低毛利樣本|單季毛利改善率|扣除去年同季變化後改善率|',
          '|---|---:|---:|']
    for label,key,adj in [('Q1營收年增≥10%','growth_10pct','growth_10pct_season_adjusted'),
                          ('Q1營收年增<10%','below_growth_10pct','below_growth_10pct_season_adjusted')]:
        a,b=co[key],co[adj]
        txt.append(f"|{label}（{a['n']}家）|{a['improved_pct']:.1f}%|{b['improved_pct']:.1f}%|")
    txt+=['','**解讀**：這是毛利率方向的回溯觀察，非股價勝率、非 A+ 命中率。',
         '在2026樣本中，單純加上營收成長門檻，對毛利率改善辨識力有限，不能憑此把毛利率恢復直接視為已證實的 Base。',
         '','**缺口**：2023/2024投資報酬回測仍欠8季前置財報、當時可用的公司財報公告時點、歷史價量與除權息、當時的模型估值快照。',
         '','檔案為 2026 年 10 月重建；不得回填聲稱2025已產生相同訊號。','']
    return '\n'.join(txt)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--data-dir',default='tw-market-data')
    ap.add_argument('--out-dir',default='tw-market-data/rankings')
    args=ap.parse_args()
    rows=load(Path(args.data_dir))
    p=analyze(rows)
    out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'v881_history_diagnostic.json').write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'v881_history_diagnostic.md').write_text(report(p),encoding='utf-8')
    print(json.dumps({'model':VERSION,'2025':p['yearly']['2025']['low_gm'],
      '2026':p['yearly']['2026']['low_gm'],'2026_growth':p['cohort_2026']['growth_10pct']},ensure_ascii=False))
if __name__=='__main__':main()
