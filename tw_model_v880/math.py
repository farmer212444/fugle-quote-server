"""Explicit units and missing-data semantics for research valuations."""
import datetime as dt,math

def number(v):
    try:
        x=float(str(v).replace(',',''));return x if math.isfinite(x) else None
    except (ValueError,TypeError):return None

def pct(values,q):
    xs=sorted(v for v in values if v is not None and math.isfinite(v))
    if not xs:return None
    p=(len(xs)-1)*q;i=int(p);return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(p-i)

def quarter_key(p):
    y,q=p.replace('-','').split('Q');q=int(q)
    if q not in range(1,5):raise ValueError('INVALID_QUARTER')
    return int(y),q

def previous_periods(p,n=8):
    y,q=quarter_key(p);last=y*4+q-1
    return [f'{i//4}-Q{i%4+1}' for i in range(last-n+1,last+1)]

def quarter_end(p):
    y,q=quarter_key(p);return dt.date(y,q*3,(31,30,30,31)[q-1])

def standalone(current,prior,quarter):
    if current is None or (quarter!=1 and prior is None):return None
    return current if quarter==1 else current-prior

def share_scenarios(issued,bonds,weighted_diluted=None):
    issued=number(issued)
    if issued is None or issued<=0:raise ValueError('INVALID_COMMON_SHARE_COUNT')
    additions=0.;missing=[];unresolved=[];detail=[]
    for b in bonds:
        face=number(b.get('face'));price=number(b.get('conversion_price'));fx=1 if b.get('currency')=='TWD' else number(b.get('fx_twd'))
        price_currency=b.get('conversion_price_currency','TWD')
        if price_currency==b.get('currency'):fx_for_shares=1
        elif price_currency=='TWD':fx_for_shares=fx
        else:fx_for_shares=None
        add=face*fx_for_shares/price if face is not None and face>=0 and fx_for_shares is not None and fx_for_shares>0 and price is not None and price>0 else None
        if b.get('underlying_share_identity_unresolved'):add=None
        if add is None:missing.append(b['code'])
        else:additions+=add
        if not b.get('current_terms_verified'):unresolved.append(b['code'])
        detail.append(dict(**b,additional_shares=add))
    weighted=number(weighted_diluted)
    base=max(issued+additions,weighted or issued)
    reset_stress=max(issued+additions/.9,weighted or issued) if not missing else None
    return dict(issued_common_shares=issued,cb_additional_shares=additions,disclosed_weighted_diluted_shares=weighted,
      base_shares=base,denominator_method='MAX_CURRENT_COMMON_PLUS_FULL_CB_AND_DISCLOSED_WEIGHTED_NOT_SUM',
      conversion_price_down_10pct_full_conversion_shares=reset_stress,conversion_price_stress_is_assumption_not_a_new_legal_term=True,
      missing_legal_conversion_inputs=missing,unresolved_terms=unresolved,bonds=detail,
      fully_diluted_shares_certified=False)

def liquidity(cash_k,ocf_k,ppe_signed_k,prepaid_signed_k,dividend_k=None,full_put_k=None):
    if ppe_signed_k is not None and ppe_signed_k>0:raise ValueError('PPE_PURCHASE_LINE_HAS_UNEXPECTED_POSITIVE_SIGN')
    if prepaid_signed_k is not None and prepaid_signed_k>0:raise ValueError('PREPAID_PURCHASE_LINE_HAS_UNEXPECTED_POSITIVE_SIGN')
    fcf=ocf_k+ppe_signed_k if None not in (ocf_k,ppe_signed_k) else None
    return dict(cash_k=cash_k,ocf_k=ocf_k,ppe_purchase_cash_signed_k=ppe_signed_k,fcf_after_ppe_k=fcf,
      equipment_prepaid_cash_signed_k=prepaid_signed_k,
      cash_after_separately_reported_prepaid_k=fcf+prepaid_signed_k if None not in (fcf,prepaid_signed_k) else None,
      indicative_dividend_k=dividend_k,full_cb_put_sensitivity_k=full_put_k,
      old_cash_less_dividend_and_full_put_k=cash_k-dividend_k-full_put_k if None not in (cash_k,dividend_k,full_put_k) else None,
      static_cash_sensitivity_is_actual_funding_gap=False,review_working_capital=ocf_k is not None and ocf_k<0,
      negative_ocf_automatic_failure=False)

def operating_scenario(revenue,gm,cost_ratio,nonop,tax,parent_fraction,shares,pe):
    if shares<=0 or revenue<=0 or not 0<=gm<=1 or cost_ratio<0 or not 0<=tax<=1:raise ValueError('INVALID_OPERATING_SCENARIO')
    gp=revenue*gm;cost=revenue*cost_ratio;op=gp-cost;pretax=op+nonop;ni=pretax*(1-tax)*parent_fraction;eps=ni*1000/shares
    return dict(revenue_k=revenue,gross_margin=gm,gross_profit_k=gp,opex_ratio=cost_ratio,opex_k=cost,
      operating_profit_k=op,nonoperating_k=nonop,pretax_k=pretax,tax_rate=tax,parent_fraction=parent_fraction,
      parent_profit_k=ni,shares=shares,eps=eps,pe=pe,target_price=eps*pe if eps>0 and pe is not None else None)

def returns(target,close,dividends,start,end):
    price=(target/close-1)*100 if target is not None else None
    cash=sum(d['per_share'] for d in dividends if start<d['ex_date']<=end) if dividends is not None else None
    return dict(price_upside_pct=price,future_dividends_per_share=cash,
      total_return_pct=(target+cash-close)/close*100 if None not in (target,cash) else None)
