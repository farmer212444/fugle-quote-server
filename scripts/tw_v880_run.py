#!/usr/bin/env python3
"""V8.8.2: independently estimated scenarios and evidence-based certification."""
import argparse,collections,datetime as dt,gzip,hashlib,json,os,pathlib,subprocess,sys,tempfile
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880 import VERSION
from tw_model_v880.data import MarketData
from tw_model_v880.calibration import fit_accounting
from tw_model_v880.model import estimate
from tw_model_v880.backtest import live_backtest_status
from tw_model_v880.evidence import POLICY
from tw_model_v880.provenance import code_fingerprint
def atomic(path,content):
    path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(content.encode() if isinstance(content,str) else content)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def public_row(r):
    keys=['code','name','market','industry','financial_period','reference_close','price_date','estimate_vintage','target_date','source_tier','rankable',
      'point_valuation_available','single_day_turnover_ntd','liquidity_research_band','base','bear','bull','status','warning_flags','formal_Aplus','formal_Aplusplus','scenario_upside_pct','research_target_price_scenario',
      'target_year_eps_scenario','research_2027_price_scenario','eps_2027_base_scenario','research_pe_assumption','research_lane','rating','score',
      'specialist_model_requirements','base_scenario_role','early_recovery_watch','stress_eps90_pe90_upside_pct','original_current_issuer_numeric_checked','exclusion_reasons','margin_recovery','margin_bridge']
    out={k:r[k] for k in keys if k in r}
    for name in ('base','bear','bull'):
        if name in out:out[name]={k:r[name][k] for k in ('eps','pe','target_price','price_upside_pct','total_return_pct') if k in r[name]}
    if 'certification' in r:out['pending_gates']=r['certification']['gates_pending']
    return out
def ordered_recovery_watch(rows):
    """Prefer original current numerics before truncating the public watchlist.

    The prior issuer-code order hid late-code issuers such as 9802. This only
    controls evidence-review visibility; it does not change prices or ratings.
    """
    return sorted([r for r in rows if r.get('early_recovery_watch')],
      key=lambda r:(r.get('source_tier')!='ORIGINAL_CURRENT_ISSUER_NUMERICS',r['code']))
def tracked_universe(data):
    """Every observed issuer is accounted for, including missing/filtered inputs."""
    keys=set(data.history)|set(data.prices)
    for code,row in data.evidence.get('master',{}).items():
        if row.get('market'):keys.add((row['market'],code))
    return sorted(keys)
def run(data_dir,asof,target_date,out_dir=None):
    data=MarketData(data_dir,asof);cal=fit_accounting(data.history,data.period,{c:r.get('industry','') for c,r in data.revenue.items()});rows=[];failures=[]
    universe=tracked_universe(data)
    for key in universe:
        history=data.history.get(key,{})
        if data.period not in history:
            master=data.evidence.get('master',{}).get(key[1],{})
            rows.append(dict(market=key[0],code=key[1],name=master.get('name'),status='CURRENT_FINANCIAL_STATEMENT_MISSING',rankable=False,exclusion_reasons=['CURRENT_FINANCIAL_STATEMENT_MISSING']));continue
        try:
            row=estimate(data,key,cal,asof,target_date)
            if row is None:row=dict(code=key[1],name=history[data.period].get('name'),status='NO_ESTIMATE_RETURNED',rankable=False)
            row.setdefault('market',key[0]);row.setdefault('exclusion_reasons',[] if row.get('rankable') else [row['status']]);rows.append(row)
        except (ValueError,KeyError,TypeError,ZeroDivisionError,OverflowError) as exc:
            failed=dict(market=key[0],code=key[1],name=history[data.period].get('name'),status='ISSUER_INPUT_OR_MODEL_ERROR',error=str(exc),rankable=False,exclusion_reasons=['ISSUER_INPUT_OR_MODEL_ERROR'])
            failures.append(failed);rows.append(failed)
    broad=sorted([r for r in rows if r.get('rankable')],key=lambda r:(r['base']['price_upside_pct'],r['code']),reverse=True)
    primary=[r for r in broad if r.get('original_current_issuer_numeric_checked')]
    formal=sorted([r for r in rows if r.get('formal_Aplus')],key=lambda r:r['base']['price_upside_pct'],reverse=True)
    aq=[r for r in formal if r['formal_Aplusplus']];backtest=live_backtest_status(data.evidence)
    pending=[dict(code=r['code'],name=r.get('name'),status=r['status'],pending_gates=r.get('certification',{}).get('gates_pending',[])) for r in rows if not r.get('formal_Aplus')]
    result=dict(model=VERSION,model_code_sha256=code_fingerprint(),estimate_vintage=asof,asof_price_date=data.price_date,revenue_month=data.revenue_month,
      financial_last_quarter=data.period,required_quarters=data.required_periods,target_date=target_date,policy=POLICY,
      policy_notes=['Approved A+/A++ price-upside thresholds retain 30/35 pct','Research min one-day turnover 1m NTD; 1m-12m research requires multi-session liquidity/exit review for formal tradability','A++ stress assumes EPS and PE each -10%, CB conversion price -10%, and nonnegative upside; stress design is an explicit implementation assumption'],
      data_scope=dict(normalized_issuers=len(data.history),priced_issuers=len(data.prices),model_rows=len(rows),tracked_issuer_universe=len(universe),original_latest_issuer_numeric_coverage=len(data.evidence.get('primary',{})),
        official_current_bulk_issuers=sum(len(v['rows']) for k,v in data.evidence.get('official_current_bulk',{}).items() if k.endswith('_income')),
        primary_research_rankable=len(primary),market_research_rankable=len(broad),not_rankable=len(rows)-len(broad),broad_unverified_historical_detail_rankable=len(broad),source_errors=len(data.errors),issuer_failures=len(failures)),
      input_evidence_qa=data.evidence.get('qa'),input_receipts=getattr(data,'input_receipts',[]),calibration=cal,backtest=backtest,formal_Aplus_count=len(formal),formal_Aplusplus_count=len(aq),
      formal_decisions_evaluated=sum('certification' in r for r in rows),zero_certified_explanation='No issuer currently satisfies every evidence gate; no assertion that the market contains no A+ opportunities',
      ranking_scope='ALL_TRACKED_ISSUERS; comparable research scenarios regardless of legacy primary cohort; source tiers disclosed; not certified investment returns',
      primary_selection_bias_unresolved=False,legacy_primary_cohort_restriction_removed=True,remaining_missing_input_selection_bias_unresolved=True,
      universe_accounted_for=len(rows)==len(universe),universe_status_counts=dict(collections.Counter(r['status'] for r in rows)),
      exclusion_reason_counts=dict(collections.Counter(reason for r in rows for reason in r.get('exclusion_reasons',[]))),
      return_definition='Price upside to target date; future dividends unknown remain null, not zero; expected total returns not claimed',
      top10_market_research=broad[:10],top10_primary_research=primary[:10],top10_formal_Aplus=formal[:10],top30_provisional=broad[:30],top30_quality_priority=primary[:30],top30_audit_required=broad[:30],all_market_research=broad,all_primary_research=primary,all_model_rows=rows,
      conditional_recovery_audit=[dict(code=r['code'],name=r.get('name'),source_tier=r.get('source_tier'),rankable=r.get('rankable'),margin_recovery=r['margin_recovery']) for r in rows if r.get('margin_recovery',{}).get('candidate')],
      specialist_operating_bridge_queue=[dict(code=r['code'],name=r['name'],requirements=r['specialist_model_requirements']) for r in rows if r.get('specialist_model_requirements')],
      early_recovery_watch=ordered_recovery_watch(rows),
      early_recovery_watch_selection='Original current issuer numerics first, then issuer code; review visibility only, full list retained in hashed results',
      pending_work=pending,source_failures=data.errors,issuer_failures=failures)
    out=pathlib.Path(out_dir) if out_dir else pathlib.Path(data_dir)/'rankings';out.mkdir(parents=True,exist_ok=True)
    fmt=lambda v:'待補' if v is None else f'{v:.2f}'
    report=[f'# {VERSION} 台股 2027 營運情境與證據分級','',f'估計形成：{asof}；參考收盤：{data.price_date}；目標：{target_date}。',
      f"正式 A+ {len(formal)} 檔，A++ {len(aq)} 檔。未決證據不等於市場沒有機會。",'',
      f'追蹤母體 {len(universe)} 家，逐家保留結果或排除理由；可比較研究估值 {len(broad)} 家，其中原始當期數字核對 {len(primary)} 家。',
      '以下依 Base 價差排序，已移除既有66家名單限制。來源層級逐列標示；歷史明細與完整附註仍待驗，並非全市場正式 A+ 排名。未知未來股息及交易成本不列入價差，不附未校準的機率。','',
      '毛利率恢復沿用既有條件式研究假設，Base最多加3.5個百分點；Bear保留未恢復毛利率，仍須營運歸因及樣本外驗證。','',
      '|序|公司|收盤|2027 EPS|PE|2027 Base價|潛在漲幅|Bear價|Bull價|當期來源|','|---:|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for i,r in enumerate(broad[:10],1):
        b=r['base'];tier='原始核對' if r['original_current_issuer_numeric_checked'] else '官方彙總'
        report.append(f"|{i}|{r['code']} {r['name']}|{fmt(r['reference_close'])}|{fmt(b['eps'])}|{fmt(b['pe'])}|{fmt(b['target_price'])}|{b['price_upside_pct']:+.1f}%|{fmt(r['bear']['target_price'])}|{fmt(r['bull']['target_price'])}|{tier}|")
    cm=cal.get('deployed_sector_or_global_holdout_metrics') or {};bm=cal.get('holdout_no_change_baseline') or {}
    report+=['','## 跨期會計預測驗證','',f"訓練 {cal.get('train_target')}：{cal['train_count']} 家；保留 {cal.get('holdout_target')}：{cal.get('holdout_count',0)} 家。係數只用訓練期選定。",'',
      '|保留期指標|新模型|去年同期不變基準|','|---|---:|---:|',
      f"|營收中位絕對百分比誤差|{fmt(cm.get('revenue_median_absolute_pct_error'))}%|{fmt(bm.get('revenue_median_absolute_pct_error'))}%|",
      f"|營收 WAPE|{fmt(cm.get('revenue_wape_pct'))}%|{fmt(bm.get('revenue_wape_pct'))}%|",
      f"|毛利率中位絕對誤差|{fmt(cm.get('gross_margin_median_abs_pp'))} 百分點|{fmt(bm.get('gross_margin_median_abs_pp'))} 百分點|",
      f"|費用率中位絕對誤差|{fmt(cm.get('opex_ratio_median_abs_pp'))} 百分點|{fmt(bm.get('opex_ratio_median_abs_pp'))} 百分點|",'',
      '營收係數改以未發生的單季校準，保留期採已知Q1加預測Q2。2027全年仍屬此外推情境，尚未完成全年成長／訂單／產能驗證。',
      '這是會計預測跨期驗證。原始公告時間與當時股票母體未全部驗證，不能稱為 PIT 投資回測或股價準確率。','',
      '## 決策與未完成事項','', '13項證據門檻逐檔判定，未知與失敗分開；完整合成測試不計入真實股票。',
      '八季主要欄位和總額勾稽不等於完整四表及附註簽核；保留核閱須評估重要性。',
      '缺工程認列／通路單位價差或有極端估值，先列專用推導待補。負 OCF 不自動淘汰，PPE與設備預付款分列。',
      'CB未確認後續轉換條件、完整公告PIT／歷史母體、管理承諾與內部人資料仍須補齊。',
      'A++ 壓測採EPS/PE各下修10%、CB轉換價下修10%增加稀釋股數，並要求潛在漲幅非負；壓測設計屬明列的實作假設。',
      '未校準情境機率，未知明年股息留空；不產生交易委託或自動Exit。','']
    full=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode();packed=gzip.compress(full,mtime=0);atomic(out/'v880_full_results.json.gz',packed)
    compact={k:v for k,v in result.items() if k not in ['all_model_rows','all_primary_research','all_market_research','early_recovery_watch','pending_work']}
    for k in ['top10_market_research','top10_primary_research','top30_provisional','top30_quality_priority','top30_audit_required']:compact[k]=[public_row(r) for r in result[k]]
    compact['all_model_row_summary']=[{k:r[k] for k in ['market','code','name','status','rankable','scenario_upside_pct','source_tier','exclusion_reasons'] if k in r} for r in rows]
    compact['top48_primary_research']=[public_row(r) for r in primary[:48]]
    compact['conditional_recovery_audit']=result['conditional_recovery_audit']
    compact['conditional_recovery_applied_count']=sum(r.get('margin_recovery',{}).get('applied',False) for r in rows)
    compact['conditional_recovery_candidate_count']=len(result['conditional_recovery_audit'])
    compact['early_recovery_watch']=[public_row(r) for r in result['early_recovery_watch'][:30]];compact['early_recovery_watch_count']=len(result['early_recovery_watch'])
    compact['pending_work_path']='v880_pending_work.json';compact['full_results']=dict(path='v880_full_results.json.gz',sha256=hashlib.sha256(packed).hexdigest(),json_sha256=hashlib.sha256(full).hexdigest())
    compact['research_universe']=len(rows);compact['quality_priority_count']=len(primary)
    atomic(out/'latest_research.json',json.dumps(compact,ensure_ascii=False,indent=2)+'\n');atomic(out/'latest_research.md','\n'.join(report))
    atomic(out/'v880_pending_work.json',json.dumps(dict(model=VERSION,asof=asof,rows=pending,source_failures=data.errors,issuer_failures=failures),ensure_ascii=False,indent=2)+'\n')
    atomic(out/'v880_validation.json',json.dumps(dict(model=VERSION,calibration=cal,backtest=backtest),ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(model=VERSION,**result['data_scope'],formal_Aplus=len(formal),formal_Aplusplus=len(aq),
      market_top10=[dict(code=r['code'],name=r['name'],target=round(r['base']['target_price'],2),upside=round(r['base']['price_upside_pct'],1)) for r in broad[:10]],
      holdout=cal.get('deployed_sector_or_global_holdout_metrics')),ensure_ascii=False))
    return result
def resolve_asof(raw,now):
    """Preserve real subsecond precision; explicit old cutoffs stay strict."""
    if now.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    if raw is None:cut=now
    elif len(raw)==10:
        day=dt.date.fromisoformat(raw)
        if day>now.date():raise ValueError('FUTURE_ESTIMATE_VINTAGE')
        cut=min(dt.datetime.combine(day,dt.time.max,tzinfo=now.tzinfo),now)
    else:cut=dt.datetime.fromisoformat(raw.replace('Z','+00:00'))
    if cut.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    if cut>now:raise ValueError('FUTURE_ESTIMATE_VINTAGE')
    return cut.isoformat(timespec='microseconds')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',default='tw-market-data');ap.add_argument('--asof');ap.add_argument('--target-date');ap.add_argument('--out-dir');ap.add_argument('--self-test',action='store_true');args=ap.parse_args()
    if args.self_test:return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-v'],cwd=ROOT)
    now=dt.datetime.now(ZoneInfo('Asia/Taipei'));asof=resolve_asof(args.asof,now)
    target=args.target_date or f'{int(asof[:4])+1}-12-31';run(args.data_dir,asof,target,args.out_dir);return 0
if __name__=='__main__':raise SystemExit(main())
