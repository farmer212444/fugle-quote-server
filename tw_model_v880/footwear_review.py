"""Dated footwear sensitivities, independent of production forecasts and gates."""
import hashlib,json,math,re
from pathlib import Path
from .evidence import timestamp


def amounts(text,label,count):
    # Keep column whitespace: compacting the page joins amounts and percentages.
    marker=re.sub(r'\s+','',label)
    matches=list(re.finditer(r'\s*'.join(re.escape(c) for c in marker),text))
    if len(matches)!=1:raise ValueError('FOOTWEAR_LABEL_NOT_UNIQUE:'+label)
    tail=text[matches[0].end():]
    values=re.findall(r'(?<![\d,])\d{1,3}(?:,\d{3})+(?![\d,])',tail)
    if len(values)<count:raise ValueError('FOOTWEAR_COLUMNS_MISSING:'+label)
    return [float(v.replace(',','')) for v in values[:count]]


def original_facts(root,code,source,asof):
    import pymupdf
    root=Path(root).resolve()
    if timestamp(source['captured_at_utc'])>timestamp(asof):raise ValueError('FOOTWEAR_ORIGINAL_FROM_FUTURE')
    if source['period']!='2026-Q2':raise ValueError('FOOTWEAR_ORIGINAL_PERIOD_UNSUPPORTED')
    relative=Path(source['path']);path=(root/relative).resolve()
    if relative.is_absolute() or '..' in relative.parts or root not in path.parents:raise ValueError('FOOTWEAR_UNSAFE_PATH')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('FOOTWEAR_ORIGINAL_HASH_MISMATCH')
    with pymupdf.open(stream=raw,filetype='pdf') as doc:pages=[p.get_text() for p in doc]
    cover=re.sub(r'\s+','',pages[0])
    if code not in cover or '115' not in cover or not any(t in cover for t in ('第2季','第二季')):
        raise ValueError('FOOTWEAR_ORIGINAL_IDENTITY_OR_PERIOD_MISMATCH')
    if code=='6890':
        income=pages[10].split('8710')[0]
        labels={'revenue_k':'營業收入','gross_profit_k':'營業毛利','operating_profit_k':'營業利益',
                'pretax_profit_k':'稅前淨利','net_income_k':'本期淨利','parent_net_income_k':'母公司業主'}
        facts={key:amounts(income,label,4)[2] for key,label in labels.items()}
        facts.update(operating_cashflow_k=amounts(pages[12],'營業活動之淨現金流入',2)[0],
                     ppe_purchase_k=amounts(pages[12],'取得不動產、廠房及設備',2)[0],
                     intangibles_purchase_k=amounts(pages[12],'取得無形資產',2)[0],
                     nonoperating_k=amounts(income,'營業外收入及支出合計',4)[2],
                     fx_gain_k=amounts(pages[35],'外幣兌換利益',2)[0],
                     fv_loss_k=amounts(pages[35],'透過損益按公允價值衡量之金融資產損失',1)[0])
        other_h1=re.split(r'\(\s*十九\s*\)',pages[35])[0].rsplit('115年1月1日至6月30日',1)[1]
        disposal=re.search(r'處分不動產、廠房及設備利益\s+([\d,]+)',other_h1)
        if not disposal:raise ValueError('FOOTWEAR_DISPOSAL_ROW_MISSING')
        facts['disposal_gain_k']=float(disposal[1].replace(',',''))
        finance_h1=pages[35].rsplit('115年1月1日至6月30日',1)[1]
        facts['cb_interest_k']=amounts(finance_h1,'應付公司債',1)[0]
        facts['normalized_annual_nonoperating_full_conversion_k']=2*(facts['nonoperating_k']-facts['fx_gain_k']+
            facts['fv_loss_k']-facts['disposal_gain_k']+facts['cb_interest_k'])
        facts['ocf_to_parent_profit']=facts['operating_cashflow_k']/facts['parent_net_income_k']
        return facts
    if code=='9904':
        equity=amounts(pages[4],'本公司業主之權益總計',4)[0]
        yy=amounts(pages[26].split('營業收入')[0],'本公司業主',3)[0]
        ru=amounts(pages[27],'－潤成投資控股股份有限公司',3)[0]
        segment=amounts(pages[61],'部門損益',4)
        return dict(parent_equity_k=equity,yue_yuen_attributable_equity_k=yy,
                    ruen_chen_direct_carrying_k=ru,residual_parent_equity_k=equity-yy-ru,
                    manufacturing_segment_profit_k=segment[0],retail_segment_profit_k=segment[1],
                    unallocated_management_cost_k=amounts(pages[61],'管理成本與董事酬勞',1)[0])
    raise ValueError('FOOTWEAR_ORIGINAL_RECIPE_UNSUPPORTED')


def build_review(root,full,config):
    root=Path(root);asof=full['estimate_vintage']
    current=(timestamp(config['reviewed_at'])<=timestamp(asof) and
             config['financial_period']==full['financial_last_quarter'] and
             config['revenue_month']==full['revenue_month'] and config['target_date']==full['target_date'])
    sources=json.loads((root/'evidence/v880/footwear/originals.json').read_text())['sources']
    rows={r['code']:r for r in full['all_model_rows']};companies=[]
    for company in config['companies']:
        code=company['code'];row=rows.get(code,{})
        item=dict(code=code,name=company['name'],price_date=row.get('price_date'),reference_close=row.get('reference_close'),
                  formal_Aplus=row.get('formal_Aplus',False),formal_Aplusplus=row.get('formal_Aplusplus',False),
                  production_base_eps=row.get('base',{}).get('eps'),production_base_price=row.get('research_target_price_scenario'),
                  production_financial_period=row.get('financial_period'),
                  production_earnings_source_kind=row.get('fresh_earnings_update',{}).get('source_kind'),
                  production_point_available=row.get('point_valuation_available',False),quality_certification=row.get('certification'),
                  research_cases=None,original_fact_check=None,all_quality_gates_granted_by_this_review=False,scenario_probabilities=None)
        try:
            facts={}
            if code in sources:
                facts=original_facts(root,code,sources[code],asof)
                item['original_fact_check']=dict(status='SPECIFIED_CURRENT_FACTS_RECONCILED_NOT_EIGHT_QUARTER_CERTIFICATION',
                                                 source=sources[code],facts=facts)
                if code=='6890':
                    official=row.get('_official_current_values')
                    if official is None:raise ValueError('FOOTWEAR_OFFICIAL_CURRENT_FACTS_MISSING')
                    if any(official.get(k) is None or not math.isclose(official[k],facts[k],abs_tol=1,rel_tol=0)
                                                    for k in ('revenue_k','gross_profit_k','operating_profit_k','pretax_profit_k','net_income_k','parent_net_income_k')):
                        raise ValueError('FOOTWEAR_OFFICIAL_CURRENT_FACT_MISMATCH')
            if not current:raise ValueError('FOOTWEAR_ASSUMPTION_VINTAGE_EXPIRED_OR_FROM_FUTURE')
            if row.get('price_date')!=full['asof_price_date']:raise ValueError('FOOTWEAR_MIXED_PRICE_DATE')
            close=row.get('reference_close');shares=row.get('share_bridge',{}).get('base_shares')
            if not close or close<=0 or not shares or shares<=0:raise ValueError('FOOTWEAR_PRICE_OR_SHARES_MISSING')
            cases={}
            for name,scenario in company['scenarios'].items():
                if code=='9904':
                    value_k=sum(facts[k]*scenario[m] for k,m in (
                        ('yue_yuen_attributable_equity_k','yue_yuen_book_multiple'),
                        ('ruen_chen_direct_carrying_k','ruen_chen_book_multiple'),('residual_parent_equity_k','residual_book_multiple')))
                    price=value_k*1000/shares
                    eps=sum(scenario[k] for k in ('yue_yuen_parent_profit_e8','ruen_chen_parent_profit_e8','other_parent_profit_e8'))*1e8/shares
                    method='BOOK_COMPONENT_DISCOUNT_SENSITIVITY_NOT_VALIDATED_MARKET_NAV'
                else:
                    nonop=facts['normalized_annual_nonoperating_full_conversion_k']/100000 if code=='6890' else company['nonoperating_e8']
                    tax=scenario.get('tax',company['tax'])
                    eps=(scenario['revenue_e8']*(scenario['gross_margin']-scenario['opex_ratio'])+nonop)*(1-tax)*company['parent']*1e8/shares
                    price=eps*scenario['pe'];method='PE_RESEARCH_ASSUMPTIONS_NOT_CERTIFIED_FORECAST'
                if not all(math.isfinite(v) for v in (eps,price)):raise ValueError('FOOTWEAR_NONFINITE_SCENARIO')
                cases[name]=dict(eps=eps,target_price=price,price_upside_pct=(price/close-1)*100,method=method,
                                  input_assumptions=scenario,denominator_shares=shares,
                                  fully_diluted_terms_certified=row.get('share_bridge',{}).get('fully_diluted_shares_certified',False))
            item.update(status='RESEARCH_ONLY',research_cases=cases)
        except (ValueError,KeyError,OSError,TypeError,IndexError) as exc:
            item.update(status='INPUT_BLOCKED',error=str(exc),research_cases=None)
        companies.append(item)
    return dict(schema='V8106_FOOTWEAR_REVIEW_V1',model=full['model'],estimate_vintage=asof,
                asof_price_date=full['asof_price_date'],target_date=full['target_date'],research_only=True,
                replaces_production_forecasts=False,grants_quality_certification=False,config_basis_current=current,companies=companies)


def markdown(report):
    lines=['# 製鞋研究與原件核對','',f"模型 {report['model']}；價格日 {report['asof_price_date']}；情境日 {report['target_date']}。",'',
           '以下為未校準機率的研究假設，價格空間不含未確認配息與交易成本，也不是年化報酬。未授予任何品質門檻 PASS，未取代主模型預測。', '',
           '| 股票 | 研究 Base EPS | 研究 Base 價 | 價格空間 | 主模型研究 EPS | 狀態 |',
           '|---|---:|---:|---:|---:|---|']
    for row in report['companies']:
        case=(row.get('research_cases') or {}).get('Base')
        production=f"{row['production_base_eps']:.2f}" if row['production_point_available'] and row['production_base_eps'] is not None else '待核（舊診斷）'
        values=[f'{case["eps"]:.2f}',f'{case["target_price"]:.2f}',f'{case["price_upside_pct"]:+.1f}%'] if case else ['待核']*3
        lines.append(f"| {row['code']} {row['name']} | {' | '.join(values)} | {production} | {row['status']} |")
    lines.extend(['','來億研究業外以 H1 指定附註移除匯兌、評價與處分項目，並在全數轉換股數情境加回 CB 利息後年化；不是公司全年財測。',
                  '主模型若採用較新的公司自結，仍不代表已核閱季報；各公司實際採用的財務期與來源類型見 JSON。研究情境不覆寫主模型。',
                  '寶成按歸屬母公司之裕元、潤成及剩餘帳面權益施加假設折價，並非已驗證市場 NAV。裕元已含寶勝，母公司淨權益不重扣合併負債。',
                  '原件雜湊、核對數字、Bear/Base/Bull 輸入與股數見同名 JSON。只核對指定當期數字，尚未完成八季認證。新財務期或新營收月會使本組假設失效。',''])
    for row in report['companies']:
        if row.get('error'):lines.append(f"- {row['code']}：{row['error']}")
    return '\n'.join(lines)+'\n'
