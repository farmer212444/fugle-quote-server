#!/usr/bin/env python3
"""Independent scenarios, dated earnings revisions and evidence-based certification."""
import argparse,collections,copy,datetime as dt,gzip,hashlib,json,os,pathlib,subprocess,sys,tempfile
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880 import VERSION
from tw_model_v880.data import MarketData
from tw_model_v880.calibration import fit_accounting
from tw_model_v880.model import estimate
from tw_model_v880.backtest import live_backtest_status
from tw_model_v880.evidence import POLICY
from tw_model_v880.provenance import code_fingerprint,runtime_dependencies
from tw_model_v880.freshness import assess_price_freshness
from tw_model_v880.contracts import canonical_hash
from tw_model_v880.governance import issuer_review,COVERAGE
from tw_model_v880.credibility import build_research_priority
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
      'specialist_model_requirements','base_scenario_role','early_recovery_watch','cycle_research','stress_eps90_pe90_upside_pct','original_current_issuer_numeric_checked','exclusion_reasons','margin_recovery','margin_bridge',
      'reviewed_financial_period','cashflow_financial_period','fresh_earnings_update','forecast_binding',
      'governance_review','recommendation_blocked','equity_offering_overlay']
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
def run(data_dir,asof,target_date,out_dir=None,variant='current-information'):
    target_year=dt.date.fromisoformat(target_date).year
    if variant not in ('current-information','without-earnings-events'):raise ValueError('UNKNOWN_MODEL_VARIANT')
    if variant!='current-information' and (out_dir is None or pathlib.Path(out_dir).resolve()==(pathlib.Path(data_dir)/'rankings').resolve()):raise ValueError('SHADOW_VARIANT_REQUIRES_SEPARATE_OUTPUT_DIRECTORY')
    data=MarketData(data_dir,asof);price_freshness=assess_price_freshness(asof,data.price_date);cal=fit_accounting(data.history,data.period,{c:r.get('industry','') for c,r in data.revenue.items()});rows=[];failures=[]
    data.strategy_variant=variant
    if variant=='without-earnings-events':data.earnings_events={};data.earnings_event_states={}
    universe=tracked_universe(data)
    for key in universe:
        history=data.history.get(key,{})
        if data.period not in history:
            master=data.evidence.get('master',{}).get(key[1],{})
            rows.append(dict(market=key[0],code=key[1],name=master.get('name'),status='CURRENT_FINANCIAL_STATEMENT_MISSING',rankable=False,exclusion_reasons=['CURRENT_FINANCIAL_STATEMENT_MISSING']));continue
        try:
            row=estimate(data,key,cal,asof,target_date)
            if row is None:row=dict(code=key[1],name=history[data.period].get('name'),status='NO_ESTIMATE_RETURNED',rankable=False)
            if row.get('fresh_earnings_update',{}).get('applied'):
                baseline_data=copy.copy(data);baseline_data.earnings_events={}
                baseline=estimate(baseline_data,key,cal,asof,target_date)
                row['fresh_earnings_update']['baseline_without_new_event']={k:baseline.get('base',{}).get(k) for k in ('eps','pe','target_price','price_upside_pct')}
                row['fresh_earnings_update']['baseline_same_model_price_and_vintage']=True
            row.setdefault('market',key[0]);row.setdefault('exclusion_reasons',[] if row.get('rankable') else [row['status']]);rows.append(row)
        except (ValueError,KeyError,TypeError,ZeroDivisionError,OverflowError) as exc:
            failed=dict(market=key[0],code=key[1],name=history[data.period].get('name'),status='ISSUER_INPUT_OR_MODEL_ERROR',error=str(exc),rankable=False,exclusion_reasons=['ISSUER_INPUT_OR_MODEL_ERROR'])
            failures.append(failed);rows.append(failed)
    for row in rows:
        row.setdefault('governance_review',issuer_review(getattr(data,'governance_reviews',{}),row['code'],row['market']))
        row.setdefault('recommendation_blocked',row['governance_review']['blocks_recommendation'])
    governance_watch=[dict(code=r['code'],market=r['market'],name=r.get('name'),
                           governance_review=r['governance_review']) for r in rows if r['recommendation_blocked']]
    broad=sorted([r for r in rows if r.get('rankable')],key=lambda r:(r['base']['price_upside_pct'],r['code']),reverse=True)
    primary=[r for r in broad if r.get('original_current_issuer_numeric_checked')]
    evidence_priority=build_research_priority(broad,cal)
    formal=sorted([r for r in rows if r.get('formal_Aplus')],key=lambda r:r['base']['price_upside_pct'],reverse=True)
    aq=[r for r in formal if r['formal_Aplusplus']];backtest=live_backtest_status(data.evidence)
    pending=[dict(code=r['code'],name=r.get('name'),status=r['status'],pending_gates=r.get('certification',{}).get('gates_pending',[])) for r in rows if not r.get('formal_Aplus')]
    dependencies=runtime_dependencies()
    result=dict(model=VERSION,model_code_sha256=code_fingerprint(),runtime_dependencies=dependencies,strategy_variant=variant,
      strategy_variant_sha256=canonical_hash(dict(runtime_code_sha256=code_fingerprint(),runtime_dependencies=dependencies,variant=variant)),estimate_vintage=asof,asof_price_date=data.price_date,
      price_freshness=price_freshness,model_source_state=getattr(data,'model_source_state',None),revenue_month=data.revenue_month,
      financial_last_quarter=data.period,required_quarters=data.required_periods,target_date=target_date,policy=POLICY,
      policy_notes=['Approved A+/A++ price-upside thresholds retain 30/35 pct','Research min one-day turnover 1m NTD; 1m-12m research requires multi-session liquidity/exit review for formal tradability','A++ stress assumes EPS and PE each -10%, CB conversion price -10%, and nonnegative upside; stress design is an explicit implementation assumption'],
      data_scope=dict(normalized_issuers=len(data.history),priced_issuers=len(data.prices),model_rows=len(rows),tracked_issuer_universe=len(universe),original_latest_issuer_numeric_coverage=len(data.evidence.get('primary',{})),
        official_current_bulk_issuers=sum(len(v['rows']) for k,v in data.evidence.get('official_current_bulk',{}).items() if k.endswith('_income')),
        primary_research_rankable=len(primary),market_research_rankable=len(broad),not_rankable=len(rows)-len(broad),broad_unverified_historical_detail_rankable=len(broad),source_errors=len(data.errors),issuer_failures=len(failures)),
      input_evidence_qa=data.evidence.get('qa'),input_receipts=getattr(data,'input_receipts',[]),earnings_event_states=getattr(data,'earnings_event_states',{}),
      governance_coverage=COVERAGE,governance_blocked_count=len(governance_watch),governance_watch=governance_watch,
      earnings_event_updates=sum(r.get('fresh_earnings_update',{}).get('applied',False) for r in rows),calibration=cal,backtest=backtest,formal_Aplus_count=len(formal),formal_Aplusplus_count=len(aq),
      formal_decisions_evaluated=sum('certification' in r for r in rows),zero_certified_explanation='No issuer currently satisfies every evidence gate; no assertion that the market contains no A+ opportunities',
      ranking_scope='ALL_TRACKED_ISSUERS; comparable research scenarios regardless of legacy primary cohort; source tiers disclosed; not certified investment returns',
      primary_selection_bias_unresolved=False,legacy_primary_cohort_restriction_removed=True,remaining_missing_input_selection_bias_unresolved=True,
      universe_accounted_for=len(rows)==len(universe),universe_status_counts=dict(collections.Counter(r['status'] for r in rows)),
      exclusion_reason_counts=dict(collections.Counter(reason for r in rows for reason in r.get('exclusion_reasons',[]))),
      return_definition='Price upside to target date; future dividends unknown remain null, not zero; expected total returns not claimed',
      top10_market_research=broad[:10],top10_primary_research=primary[:10],
      top10_evidence_first=evidence_priority['top10_evidence_first'],
      evidence_priority_summary={k:v for k,v in evidence_priority.items() if k not in ('all_ranked','original_current_audit_priority','top10_evidence_first','top10_original_numeric_priority','blocked_governance')},
      top10_formal_Aplus=formal[:10],top30_provisional=broad[:30],top30_quality_priority=primary[:30],top30_audit_required=broad[:30],all_market_research=broad,all_primary_research=primary,all_model_rows=rows,
      conditional_recovery_audit=[dict(code=r['code'],name=r.get('name'),source_tier=r.get('source_tier'),rankable=r.get('rankable'),margin_recovery=r['margin_recovery']) for r in rows if r.get('margin_recovery',{}).get('candidate')],
      specialist_operating_bridge_queue=[dict(code=r['code'],name=r['name'],requirements=r['specialist_model_requirements']) for r in rows if r.get('specialist_model_requirements')],
      early_recovery_watch=ordered_recovery_watch(rows),
      early_recovery_watch_selection='Original current issuer numerics first, then issuer code; review visibility only, full list retained in hashed results',
      pending_work=pending,source_failures=data.errors,issuer_failures=failures)
    out=pathlib.Path(out_dir) if out_dir else pathlib.Path(data_dir)/'rankings';out.mkdir(parents=True,exist_ok=True)
    fmt=lambda v:'待補' if v is None else f'{v:.2f}'
    report=[f'# {VERSION} 台股 {target_year} 營運情境與證據分級','',f'估計形成：{asof}；參考收盤：{data.price_date}；目標：{target_date}。',
      f"正式 A+ {len(formal)} 檔，A++ {len(aq)} 檔。未決證據不等於市場沒有機會。",'',
      f'追蹤母體 {len(universe)} 家，逐家保留結果或排除理由；可比較研究估值 {len(broad)} 家，其中原始當期數字核對 {len(primary)} 家。',
      '以下依 Base 價差排序，已移除既有66家名單限制。來源層級逐列標示；歷史明細與完整附註仍待驗，並非全市場正式 A+ 排名。未知未來股息及交易成本不列入價差，不附未校準的機率。','',
      '營收加速與歷史毛利恢復只產生觀察情境，不能自行提高Base；公司別營運推導另需原始證據。已核對的公司自結表可更新研究估計，來源與現金流期間分開標示。','',
      f'|序|公司|收盤|{target_year} EPS|PE|{target_year} Base價|潛在漲幅|Bear價|Bull價|當期來源|治理|','|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|']
    if price_freshness["equity_source_may_be_stale"]:
        report[3:3]=[
            "⚠️ **收盤參考價可能落後**：截至估計形成時間，尚有 "+
            "、".join(price_freshness["potentially_missing_weekdays"])+
            " 等可能完成的平日交易日未納入。交易所休市與官方資料延遲尚未獨立確認；"+
            "以下只能當歷史參考價，不可視為最新可成交買入價。",
            f"此警示不會自行編造新股價、改變{target_year} Base/EPS/PE或增加正式A+。",""]
    else:
        report[3:3]=["目前的參考日未發現潛在平日缺口，但仍非盤中即時報價。",""]
    for i,r in enumerate(broad[:10],1):
        b=r['base'];tier='公司自結暫估' if r.get('fresh_earnings_update',{}).get('applied') else '原始核對' if r['original_current_issuer_numeric_checked'] else '官方彙總'
        governance_label='**重大治理待查**' if r['recommendation_blocked'] else '未全面核查'
        report.append(f"|{i}|{r['code']} {r['name']}|{fmt(r['reference_close'])}|{fmt(b['eps'])}|{fmt(b['pe'])}|{fmt(b['target_price'])}|{b['price_upside_pct']:+.1f}%|{fmt(r['bear']['target_price'])}|{fmt(r['bull']['target_price'])}|{tier}|{governance_label}|")
    offering_rows=[r for r in rows if r.get('equity_offering_overlay')]
    if offering_rows:
        report+=['','## 已公告、尚未發行的股本事件：獨立壓力測試','',
          '以下不變更原Base EPS或研究排名；尚未收到募資現金及未核定最終發行價時，不能把機械稀釋結果直接當成可比較的除權後股價報酬率。','']
        for r in offering_rows:
            o=r['equity_offering_overlay']
            if o.get('status')=='ANNOUNCED_UNISSUED_DILUTION_SCENARIO_ONLY':
                report.append(f"- **{r['code']} {r['name']}**：計畫增發 {o['planned_new_common_shares']:,} 股；現有研究 Base EPS {fmt(r['base']['eps'])}，在淨利固定且股數增加情境下 EPS {fmt(o['issuance_eps_sensitivity'])}、機械式目標價 {fmt(o['issuance_target_price_sensitivity'])}。此非考慮募資現金、募資後投資收益與除權價格後之合理價；正式股數品質門檻仍待查。來源：{o['source_url']}")
            else:
                report.append(f"- **{r['code']} {r['name']}**：現增事件已登錄，但狀態 {o['status']}，需要重新核對股數及原始公告。")
    report+=['','## 2027 證據優先研究榜（非投資報酬排名）','',
      '研究優先順序：當期原始數字核對→無未完成現增→無CB條款未決→EPS、PE各降20%的敏感度→原Base價差。'
      '僅供決定先查哪家公司，不代表該公司更有機會上漲；所有未簽核品質門檻保持待查。','',
      '|研究序|公司|當期來源|Base漲幅|EPS/PE各-20%敏感度|優先待查事項|',
      '|---:|---|---|---:|---:|---|']
    for r in evidence_priority['top10_evidence_first']:
        review_issues=[]
        if r['qualified_auditor_review_needs_subsidiary_scope_reconciliation']:
            review_issues.append('會計師保留結論／子公司核閱範圍待查')
        if r['latest_month_reversal_warning']:review_issues.append('最新月營收轉弱')
        if r['latest_standalone_quarter_margin_compression_warning']:review_issues.append('單季毛利率季減≥3pp')
        if '2027_BASE_GM_GE3PP_ABOVE_LATEST_STANDALONE_QUARTER' in r['warning_flags']:
            review_issues.append('2027 Base毛利高於最新單季≥3pp')
        if r['reported_ytd_material_nonoperating_gap']:review_issues.append('業外比重較高')
        if r['reported_ytd_nonoperating_gap_exceeds_pretax']:review_issues.append('業外差額大於稅前淨利')
        if r['eps_runrate_near_zero_denominator']:review_issues.append('年化EPS分母過小')
        if r['requires_2027_eps_stepup_bridge']:review_issues.append('2027 EPS年化比較差距大')
        if r['pending_offering']:review_issues.append('現增')
        if r['cb_terms_or_shares_unresolved']:review_issues.append('CB/股數')
        if 'NEGATIVE_OCF_REQUIRES_WORKING_CAPITAL_BRIDGE_NOT_AUTOMATIC_FAIL' in r['warning_flags']:review_issues.append('OCF/營運資金')
        if r['latest_q2_standalone_ocf_recovered_after_q1']:review_issues.append('Q2單季OCF轉正（未認證）')
        if 'MARGIN_RECOVERY_NOT_ISSUER_CERTIFIED' in r['warning_flags']:review_issues.append('毛利恢復')
        review_issues+=['全年EPS/PE、13門檻']
        tier='原始當期數字' if r['original_current_numeric_reconciled'] else '官方彙總'
        report.append(f"|{r['review_rank']}|{r['code']} {r['name']}|{tier}|{r['base_upside_pct']:+.1f}%|"
                      f"{fmt(r['eps_pe_each_minus20_upside_pct'])}%|{'、'.join(review_issues)}|")
    qualified_watch=[x for x in evidence_priority['top10_evidence_first']
                     if x['qualified_auditor_review_needs_subsidiary_scope_reconciliation']]
    if qualified_watch:
        report+=['','### 公司原始財報會計師保留結論（待核閱範圍複核）','',
          '僅展示直接檢視發行人官網文件與當期官方標準化主表核對的觀察；'
          '網址存在與主要數字勾稽不等於已核完八季完整附註或原始MOPS公告PIT，更不等於會計師正式門檻通過。','']
        for x in qualified_watch:
            watch=x['auditor_scope_original_observation']
            scope=watch['qualified_scope_pct']
            prior=watch.get('preceding_q1_review') or {}
            report.append(
              f"- **{x['code']} {x['name']}**：2026-Q2會計師保留結論，涉及未經核閱的部分子公司；"
              f"其所占合併資產 {scope['assets_at_2026_06_30']:.2f}%、Q2綜合損益總額 "
              f"{scope['quarterly_consolidated_comprehensive_income']:.2f}%、上半年綜合損益總額 "
              f"{scope['half_year_consolidated_comprehensive_income']:.2f}%。"
              (f"上季2026-Q1亦為保留結論，未核閱子公司占第一季綜合損益 "
               f"{prior['subsidiaries_unreviewed_share_of_total_comprehensive_income_pct']:.2f}%。"
               if prior else '')
              "保留結論不等於已認定舞弊或財報重大錯誤；須覆核子公司範圍與重大性。"
              f"原始文件：{watch['source_pdf_url']}。"
              f"文件日期 {watch['document_dated']}，本次直接檢視日 "
              f"{watch['first_directly_inspected_on']}；非已核實之歷史可得時間。"
              + (f" 2026-Q1原始文件：{prior['issuer_original_source_url']}。" if prior else ''))
        report+=['','會計師核閱範圍原有13項品質門檻仍為PENDING，不據此調整Base EPS/PE或宣稱A+。','']
    ocf_recovery=[x for x in evidence_priority['top10_evidence_first']
                  if x['latest_q2_standalone_ocf_recovered_after_q1']]
    if ocf_recovery:
        report+=['','### 單季營業現金流（累計現金流量表相減）','',
            'Q2 單季OCF＝上半年累計OCF－第一季OCF。數字單位為億元新台幣；'
            '這是標準化官方累計資料之研究計算，尚非原始逐筆應收／存貨／應付及附註稽核。','',
            '|公司|Q1 OCF|Q2 單季OCF|上半年累計 OCF|現金流解讀|',
            '|---|---:|---:|---:|---|']
        for x in ocf_recovery:
            v=x['operating_cashflow_quarter_bridge']
            label='上半年仍負' if v['h1_or_current_ytd_ocf_still_negative'] else '上半年轉正'
            report.append(f"|{x['code']} {x['name']}|{v['previous_ytd_ocf_k']/100000:+.2f}|"
                          f"{v['latest_standalone_ocf_k']/100000:+.2f}|"
                          f"{v['latest_ytd_ocf_k']/100000:+.2f}|{label}；仍需營運資金及收款勾稽|")
        report+=['',
          '⚠️ 單季轉正不是現金品質PASS，亦不能據此認定應收回收良好或恢復長期自由現金流；'
          '上半年負OCF個股仍保留負OCF警示和待驗門檻。','']
    margin_watch=[x for x in evidence_priority['top10_evidence_first']
                  if x['latest_standalone_quarter_margin_compression_warning']]
    if margin_watch:
        report+=['','### 單季毛利率變化（累計財報相減）','',
            '以同一年度累計營收與毛利相減，還原單季毛利率，對比上一單季。'
            '這是營運品質研究警示，不代表全年毛利轉折已確立，也不直接調低2027 Base EPS、PE或A+。','']
        for x in margin_watch:
            report.append(f"- {x['code']} {x['name']}：前一單季毛利率 "
                          f"{x['prior_standalone_quarter_gm_pct']:.2f}% → 最新單季 "
                          f"{x['latest_standalone_quarter_gm_pct']:.2f}%（季差 "
                          f"{x['latest_quarter_gm_qoq_change_pp']:+.2f}百分點）；"
                          '需補公司各業務毛利、收入認列、成本分攤及存貨等原始附註。')
    margin_flat=[x for x in evidence_priority['top10_evidence_first']
                 if x['recent_quarter_gm_flat_2027_sensitivity']['status'] in
                 ('MECHANICAL_2027_LAST_STANDALONE_GM_FLAT_ONLY','SCENARIO_NONPOSITIVE_EPS_PE_VALUE_UNAVAILABLE')]
    if margin_flat:
        report+=['','### 2027 若最新單季毛利率維持不變：機械敏感度（非目標價）','',
            '以下僅替換2027 Base毛利率為最新單季觀察值，營收、費用率、業外、稅率、歸母比例、股數及PE全部維持原模型假設。'
            '這是單一變數壓力測試，不能當作最新單季毛利率必然延續或2027實際合理價。','',
            '|公司|2027 Base毛利率|最新單季毛利率|Base EPS|持平單季毛利EPS|情境價格|',
            '|---|---:|---:|---:|---:|---:|']
        for x in margin_flat:
            sensitivity=x['recent_quarter_gm_flat_2027_sensitivity']
            report.append(
                f"|{x['code']} {x['name']}|{sensitivity['base_gross_margin_pct']:.2f}%|"
                f"{sensitivity['latest_standalone_gross_margin_pct']:.2f}%|"
                f"{x['base_eps']:.2f}|{fmt(sensitivity['scenario_eps'])}|"
                f"{fmt(sensitivity['scenario_target_price'])} 元|")
        report+=['',
          '若敏感度情境EPS不大於零，不以負數本益比推算價格；全部價格仍沿用可能落後的參考收盤價。'
          '已公布的Base EPS／PE／價差、A+與排名完全不變。','']
    priority_eps_watch=[x for x in evidence_priority['top10_evidence_first']
                        if x['reported_ytd_material_nonoperating_gap'] or x['requires_2027_eps_stepup_bridge']]
    if priority_eps_watch:
        report+=['','### 當期業外與2027 EPS橋接風險','',
            '以下使用已公告累計歸母獲利依經過季數直接年化，再以模型稀釋股數計算EPS；'
            '不是2026全年度獲利預測，不含季節性；業外占比為本期稅前損益比例，不代表未來重複發生。','']
        for x in priority_eps_watch:
            other='待查' if x['reported_ytd_abs_nonoperating_gap_share_pretax_pct'] is None else f"{x['reported_ytd_abs_nonoperating_gap_share_pretax_pct']:.1f}%"
            eps='待查' if x['ytd_parent_eps_linear_annualized_reference'] is None else f"{x['ytd_parent_eps_linear_annualized_reference']:.2f}"
            gap='待查' if x['target_eps_vs_unseasonalized_ytd_run_rate_pct'] is None else f"{x['target_eps_vs_unseasonalized_ytd_run_rate_pct']:+.1f}%"
            delta=x['target_eps_minus_ytd_annualized_reference_ntd_per_share']
            difference='待查' if delta is None else f"{delta:+.2f}元"
            ratio_note=('⚠️ EPS年化參考值低於0.5元，百分比受微小分母放大，不可當風險大小或機率。'
                        if x['eps_runrate_near_zero_denominator'] else '')
            nonop_note=('⚠️ 業外差額絕對值大於稅前淨利，表示本期營業與業外損益有顯著抵銷，不能解讀成穩定業外獲利。'
                        if x['reported_ytd_nonoperating_gap_exceeds_pretax'] else '')
            report.append(f"- {x['code']} {x['name']}：累計業外差額/稅前淨利（絕對值）{other}；直接年化歸母EPS參考 {eps}；"
                          f"2027模型EPS相差 {difference}（{gap}）。{ratio_note}{nonop_note}"
                          "目前仍缺可簽核的經常性業外明細、產能／訂單／認列及稅後歸母橋接。")
    error_ref=evidence_priority['accounting_error_reference']
    report+=['',
      f"2026 Q2營收樣本外絕對誤差第90百分位 {fmt(error_ref['overall_p90_abs_revenue_error_pct'])}%；"
      f"高成長子群 {fmt(error_ref['high_growth_subgroup_p90_abs_revenue_error_pct'])}%。"
      '這些誤差不直接換算成2027 EPS或股價漲跌機率，也不直接用於調整已公告的Base EPS／PE。',
      '尚無足夠已驗證實際投資期報酬，故證據優先研究榜不代表能打敗0050／大盤。','',
      '## 司法與公司治理事件','',
             '事件登錄僅涵蓋已核對案件，沒有登錄不代表治理安全。重大未決事件重開既有管理承諾與會計師範圍審查，暫停推薦及正式A+/A++資格。起訴不等於定罪，所稱損害不直接當作本季損失，也不任意調降EPS或PE。','']
    for item in governance_watch:
        review=item['governance_review']
        report.append(f"- **{item['code']} {item.get('name') or ''}：重大治理待查／暫停推薦。**")
        if review.get('reason'):report.append('  來源待修復：'+review['reason'])
        for event in review.get('events',[]):
            if event['event_id'] not in review.get('material_open_event_ids',[]):continue
            report.append('  '+(event.get('summary') or event['event_id'])+'；起訴未定罪。')
            report.append('  事件首次收錄：'+event['first_recorded_at']+'；本次原文核對：'+event['checked_at']+'。不得回填為歷史事前已知訊號。')
            report.append('  待補：'+'；'.join(event.get('next_evidence',[]))+'。')
            for source in event['sources']:report.append('  原始來源：'+source['url'])
    updates=[r for r in rows if r.get('fresh_earnings_update',{}).get('applied')]
    if updates:
        report+=['','## 新資訊估值修訂','']
        for r in updates:
            old=r['fresh_earnings_update']['baseline_without_new_event'];b=r['base']
            report.append(f"- {r['code']} {r['name']}：納入{r['financial_period']}公司自結原始表格；同一價格及模型下，EPS {fmt(old['eps'])}→{fmt(b['eps'])}、Base {fmt(old['target_price'])}→{fmt(b['target_price'])}。現金流仍為{r['cashflow_financial_period']}，{target_year}營運橋接及正式認證仍待完成。")
    cm=cal.get('deployed_sector_or_global_holdout_metrics') or {};bm=cal.get('holdout_no_change_baseline') or {}
    tail=cal.get('holdout_error_tail') or {}
    if tail.get('status')=='DESCRIPTIVE_CROSS_PERIOD_HOLDOUT_ONLY':
        report+=['','### 保留期預測誤差尾部檢驗','',
          f"2026-Q2 已保留樣本 {tail['n']} 家；營收預測絕對誤差第90百分位 {fmt(tail['p90_absolute_pct_error'])}%、第95百分位 {fmt(tail['p95_absolute_pct_error'])}%；"
          f"其中預測優於前一年同期不變的公司比例 {100*tail['beats_prior_year_unchanged_share']:.1f}%、"
          f"誤差大於前一年同期不變的比例 {100*tail['worse_than_prior_year_unchanged_share']:.1f}%。",
          '這些是2026上半年會計營收預測的描述性誤差，不是2027年EPS的信賴區間、上漲機率、股票勝率或樣本外投資報酬。','']
        high=tail.get('groups',{}).get('HIGH_GROWTH_AT_LEAST_20PCT',{})
        if high.get('status')=='DESCRIPTIVE_ONLY':
            report.append(f"高成長子群（已知Q1營收年增至少20%，n={high['n']}）第90百分位絕對誤差 {fmt(high['p90_absolute_pct_error'])}%；僅供風險檢查，不用來擴大正式A+數量。")
    report+=['','## 跨期會計預測驗證','',f"訓練 {cal.get('train_target')}：{cal['train_count']} 家；保留 {cal.get('holdout_target')}：{cal.get('holdout_count',0)} 家。係數只用訓練期選定。",'',
      '|保留期指標|新模型|去年同期不變基準|','|---|---:|---:|',
      f"|營收中位絕對百分比誤差|{fmt(cm.get('revenue_median_absolute_pct_error'))}%|{fmt(bm.get('revenue_median_absolute_pct_error'))}%|",
      f"|營收 WAPE|{fmt(cm.get('revenue_wape_pct'))}%|{fmt(bm.get('revenue_wape_pct'))}%|",
      f"|毛利率中位絕對誤差|{fmt(cm.get('gross_margin_median_abs_pp'))} 百分點|{fmt(bm.get('gross_margin_median_abs_pp'))} 百分點|",
      f"|費用率中位絕對誤差|{fmt(cm.get('opex_ratio_median_abs_pp'))} 百分點|{fmt(bm.get('opex_ratio_median_abs_pp'))} 百分點|",'',
      f'營收係數改以未發生的單季校準，保留期採已知Q1加預測Q2。{target_year}全年仍屬此外推情境，尚未完成全年成長／訂單／產能驗證。',
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
    compact['all_model_row_summary']=[{k:r[k] for k in ['market','code','name','status','rankable','scenario_upside_pct','source_tier','exclusion_reasons','recommendation_blocked'] if k in r} for r in rows]
    compact['top48_primary_research']=[public_row(r) for r in primary[:48]]
    compact['conditional_recovery_audit']=result['conditional_recovery_audit']
    compact['conditional_recovery_applied_count']=sum(r.get('margin_recovery',{}).get('applied',False) for r in rows)
    compact['conditional_recovery_candidate_count']=len(result['conditional_recovery_audit'])
    compact['early_recovery_watch']=[public_row(r) for r in result['early_recovery_watch'][:30]];compact['early_recovery_watch_count']=len(result['early_recovery_watch'])
    compact['pending_work_path']='v880_pending_work.json';compact['full_results']=dict(path='v880_full_results.json.gz',sha256=hashlib.sha256(packed).hexdigest(),json_sha256=hashlib.sha256(full).hexdigest())
    compact['research_universe']=len(rows);compact['quality_priority_count']=len(primary)
    atomic(out/'latest_research.json',json.dumps(compact,ensure_ascii=False,indent=2)+'\n');atomic(out/'latest_research.md','\n'.join(report))
    atomic(out/'latest_evidence_priority.json',json.dumps(evidence_priority,ensure_ascii=False,indent=2)+'\n')
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
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',default='tw-market-data');ap.add_argument('--asof');ap.add_argument('--target-date');ap.add_argument('--out-dir');ap.add_argument('--variant',choices=('current-information','without-earnings-events'),default='current-information');ap.add_argument('--self-test',action='store_true');args=ap.parse_args()
    if args.self_test:return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-v'],cwd=ROOT)
    now=dt.datetime.now(ZoneInfo('Asia/Taipei'));asof=resolve_asof(args.asof,now)
    target=args.target_date or f'{int(asof[:4])+1}-12-31';run(args.data_dir,asof,target,args.out_dir,args.variant);return 0
if __name__=='__main__':raise SystemExit(main())
