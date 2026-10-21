"""Issuer operating ledgers: revenue/cost inputs, never a desired EPS/price."""
import math,re
from .evidence import timestamp
def nonnegative(v,name):
    if v is None or not math.isfinite(v) or v<0:raise ValueError('INVALID_'+name)
    return v
def segment(s):
    kind=s['kind']
    if kind=='project':
        revenue=cost=0.
        for p in s['projects']:
            remaining=nonnegative(p.get('remaining_contract_revenue_k'),'REMAINING_CONTRACT_REVENUE')
            fraction=p['recognition_fraction'];gm=p['project_gross_margin']
            if not 0<=fraction<=1 or not 0<=gm<=1:raise ValueError('INVALID_PROJECT_RECOGNITION_OR_MARGIN')
            revenue+=remaining*fraction;cost+=remaining*fraction*(1-gm)
    elif kind in ('distributor','manufacturing'):
        if kind=='manufacturing':
            if 'quarterly_capacity_schedule' in s:
                schedule=s['quarterly_capacity_schedule']
                if not isinstance(schedule,list) or len(schedule)!=4 or sorted(p['quarter'] for p in schedule)!=[1,2,3,4]:raise ValueError('FULL_FOUR_QUARTER_CAPACITY_SCHEDULE_REQUIRED')
                units=0.
                for period in schedule:
                    capacity=nonnegative(period['capacity_units_for_quarter'],'QUARTERLY_CAPACITY');util=period['utilization']
                    if not isinstance(util,(int,float)) or isinstance(util,bool) or not math.isfinite(util) or not 0<=util<=1:raise ValueError('INVALID_UTILIZATION')
                    units+=capacity*util
            else:
                capacity=nonnegative(s['capacity_units'],'CAPACITY');util=s['utilization']
                if not 0<=util<=1:raise ValueError('INVALID_UTILIZATION')
                units=capacity*util
        else:units=nonnegative(s['units_sold'],'UNITS_SOLD')
        revenue=units*nonnegative(s['asp_twd'],'ASP')/1000;cost=units*nonnegative(s['unit_cost_twd'],'UNIT_COST')/1000
        cost+=nonnegative(s.get('fixed_factory_cost_k',0),'FIXED_FACTORY_COST')+nonnegative(s.get('inventory_provision_k',0),'INVENTORY_PROVISION')
        if 'depreciation_k' in s:
            if 'fixed_factory_cost_ex_depreciation_k' not in s or s.get('fixed_factory_cost_k',0)!=0:raise ValueError('DEPRECIATION_MUST_NOT_BE_DOUBLE_COUNTED')
            cost+=nonnegative(s['fixed_factory_cost_ex_depreciation_k'],'FACTORY_COST_EX_DEPRECIATION')+nonnegative(s['depreciation_k'],'DEPRECIATION')
    else:raise ValueError('UNSUPPORTED_OPERATING_SEGMENT')
    opex=nonnegative(s['opex_fixed_k'],'FIXED_OPEX')+revenue*nonnegative(s['opex_rate'],'VARIABLE_OPEX_RATE')
    return dict(revenue_k=revenue,gross_profit_k=revenue-cost,opex_k=opex,operating_profit_k=revenue-cost-opex)
def issuer_case(ledger,code,period,asof,target_date,shares,pe_cases):
    if ledger.get('code')!=code or ledger.get('financial_period')!=period or ledger.get('target_date')!=target_date:raise ValueError('ISSUER_BRIDGE_IDENTITY_MISMATCH')
    cut=timestamp(asof)
    if timestamp(ledger['estimate_created_at'])>cut or timestamp(ledger['expires_at'])<cut:raise ValueError('ISSUER_BRIDGE_FUTURE_OR_EXPIRED')
    if not ledger.get('sources'):raise ValueError('ISSUER_BRIDGE_SOURCES_REQUIRED')
    for src in ledger['sources']:
        if not re.fullmatch('[0-9a-f]{64}',src.get('sha256','')) or not src.get('url') or timestamp(src['available_at'])>cut:raise ValueError('ISSUER_BRIDGE_SOURCE_UNVERIFIED')
    cases={}
    for name in ('base','bear','bull'):
        c=ledger['cases'][name];parts=[segment(s) for s in c['segments']];revenue=sum(p['revenue_k'] for p in parts);gp=sum(p['gross_profit_k'] for p in parts);opex=sum(p['opex_k'] for p in parts)
        pre=gp-opex+c['nonoperating_k'];tax=c['tax_rate'];fraction=c['parent_fraction']
        if revenue<=0 or not 0<=tax<=1 or not 0<fraction<=1.2:raise ValueError('INVALID_ISSUER_BRIDGE_TAX_OR_REVENUE')
        parent=pre*(1-tax)*fraction;eps=parent*1000/shares;method=c['valuation']['method']
        if method=='NAV':
            v=c['valuation'];price=(nonnegative(v['asset_value_k'],'ASSET_VALUE')-nonnegative(v['liabilities_k'],'LIABILITIES'))*1000/shares
        elif method=='PE':price=eps*pe_cases[name] if pe_cases[name] is not None and eps>0 else None
        else:raise ValueError('UNSUPPORTED_SPECIALIST_VALUATION_METHOD')
        cases[name]=dict(revenue_k=revenue,gross_margin=gp/revenue,gross_profit_k=gp,opex_k=opex,opex_ratio=opex/revenue,
          operating_profit_k=gp-opex,nonoperating_k=c['nonoperating_k'],pretax_k=pre,tax_rate=tax,parent_fraction=fraction,
          parent_profit_k=parent,shares=shares,eps=eps,pe=pe_cases[name] if method=='PE' else None,target_price=price,
          valuation_method=method,issuer_specific_operating_inputs=True)
    return cases
