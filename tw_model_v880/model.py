"""Independent operating forecasts with consistently applied evidence gates."""
import math,statistics,re
from .math import number,pct,quarter_key,quarter_end,share_scenarios,liquidity,operating_scenario,returns
from .evidence import GATES,POLICY,certify,gate,timestamp
from .specialists import issuer_case
from .provenance import code_fingerprint
from .margin_recovery import assess_margin_recovery
from .margin_velocity import recent_quarter_gm_velocity
from .revenue_leading import revenue_leading_signal
from .cycle_alpha import is_cyclical
from .contracts import forecast_binding,matches_forecast
from .peers import matched_multiples
from .governance import issuer_review,reopen_quality_reviews
from .offering import equity_offering_overlay

# A low-turnover issuer can be researched without passing the execution gate.
RESEARCH_MIN_TURNOVER_NTD = 1_000_000
TRADABILITY_REVIEW_TURNOVER_NTD = 12_000_000

def finite_values(d,keys):return all(d.get(k) is not None and math.isfinite(d[k]) for k in keys)
def research_gates(primary,code,period,cash,coverage):
    gates={k:gate('PENDING','SOURCE_CHECK_OR_ISSUER_RECONCILIATION_REQUIRED') for k in GATES}
    if primary:
        gates['original_eight_quarter_statements']=gate('PENDING','KEY_VALUES_RECONCILED_NOT_FULL_NOTES_AUDIT' if coverage else 'ORIGINAL_PERIODS_OR_RECONCILIATION_MISSING')
        gates['auditor_scope']=gate('PENDING','QUALIFIED_REVIEW_MATERIALITY_REQUIRED' if primary['qualified_review'] else 'HISTORICAL_SCOPE_AND_NOTES_SIGNOFF_REQUIRED')
    gates['cash_and_working_capital']=gate('PENDING','NEGATIVE_OCF_REQUIRES_CYCLE_AND_FUNDING_REVIEW' if cash['review_working_capital'] else 'MULTI_PERIOD_WORKING_CAPITAL_AND_LIQUIDITY_REVIEW_REQUIRED')
    gates['tradability']=gate('PENDING','SINGLE_DAY_QUOTE_IS_NOT_CONTINUOUS_TRADABILITY_CERTIFICATION')
    return gates

def estimate(data,key,calibration,asof,target_date,shadow_thin=False):
    market,code=key;p=data.prices.get(key)
    # Training/backfill may retain older observations; forecast statistics use
    # the declared eight-quarter window, never an expanding or future window.
    rs={period:row for period,row in data.history[key].items() if period in data.required_periods}
    latest=rs[data.period]
    rev=data.revenue.get(code);e=data.evidence;master=e.get('master',{}).get(code)
    event=getattr(data,'earnings_events',{}).get(code)
    valuation_period=event['financial_period'] if event else data.period
    def unavailable(reason):return dict(code=code,name=latest.get('name'),market=market,status=reason,rankable=False,exclusion_reasons=[reason])
    if not p:return unavailable('REFERENCE_PRICE_MISSING')
    if not rev:return unavailable('MONTHLY_REVENUE_MISSING')
    if not master:return unavailable('ISSUED_SHARE_MASTER_MISSING')
    calibration=calibration.get('sector_parameters',{}).get(rev.get('industry'),calibration)
    close=number(p['close']);volume=number(p.get('volume_shares'))
    if close is None or volume is None or close<=0 or volume<0:return unavailable('REFERENCE_PRICE_OR_VOLUME_INVALID')
    turnover=close*volume
    thin=close<8 or turnover<RESEARCH_MIN_TURNOVER_NTD
    low_turnover_review=turnover<TRADABILITY_REVIEW_TURNOVER_NTD
    if close<8 and not shadow_thin:return unavailable('PRICE_FILTER_BELOW_8_TWD')
    if turnover<RESEARCH_MIN_TURNOVER_NTD and not shadow_thin:return unavailable('TURNOVER_FILTER_BELOW_1M_TWD')
    y,q=quarter_key(valuation_period);fy_period=f'{y if q==4 else y-1}-Q4';prior_period=f'{y-1}-Q{q}'
    if any(k not in rs for k in data.required_periods):return dict(code=code,name=latest.get('name'),status='MISSING_NORMALIZED_EIGHT_QUARTERS',rankable=False)
    if rev.get('industry')=='金融保險業':return dict(code=code,name=latest.get('name'),status='FINANCIAL_SECTOR_REQUIRES_ROE_PB_MODEL',rankable=False)
    # Profit / actual issued shares does not assume a NT$10 par value. A star in
    # the name alone must not exclude a company with a real share denominator.
    primary=None if event else data.primary(code)
    cur=event['current'] if event else primary['values'] if primary else data.detailed_values(key,data.period)
    fy=(cur if q==4 else (primary.get('prior_full_year') if primary else None)) or data.detailed_values(key,fy_period)
    fyop=rs[fy_period];pr=dict(rs[prior_period])
    if event:
        if timestamp(event['available_at'])>timestamp(asof):raise ValueError('FUTURE_EARNINGS_EVENT_SOURCE')
        if event['prior_period']!=prior_period:raise ValueError('EARNINGS_EVENT_PRIOR_PERIOD_MISMATCH')
        if quarter_end(valuation_period)>timestamp(asof).date():raise ValueError('FUTURE_EARNINGS_EVENT_PERIOD')
        old_year,old_q=quarter_key(data.period)
        if y!=old_year or q!=old_q+1:raise ValueError('EARNINGS_EVENT_REQUIRES_ADJACENT_COMPARABLE_QUARTER')
        old_primary=data.primary(code)
        old_values=old_primary['values'] if old_primary else data.detailed_values(key,data.period)
        for field in ('revenue_k','gross_profit_k','operating_profit_k','pretax_profit_k','net_income_k','parent_net_income_k'):
            old_value=number((old_values or {}).get(field))
            if old_value is None or abs(event['current'][field]-event['single_quarter'][field]-old_value)>1:
                raise ValueError('EARNINGS_EVENT_PRIOR_YTD_OR_RESTATEMENT_NOT_RECONCILED_'+field)
        for a,b in [('revenue_k','revenue_ytd_k'),('gross_profit_k','gross_profit_ytd_k'),('operating_profit_k','operating_profit_ytd_k')]:
            if abs(event['prior'][a]-number(pr[b]))>1:raise ValueError('EARNINGS_EVENT_PRIOR_YEAR_RESTATEMENT_NOT_RECONCILED_'+a)
            pr[b]=event['prior'][a]
    current={'revenue_k':number(latest['revenue_ytd_k']),'gross_profit_k':number(latest['gross_profit_ytd_k']),'operating_profit_k':number(latest['operating_profit_ytd_k'])}
    if cur:current.update({k:v for k,v in cur.items() if v is not None})
    fyvals={'revenue_k':number(fyop['revenue_ytd_k']),'gross_profit_k':number(fyop['gross_profit_ytd_k']),'operating_profit_k':number(fyop['operating_profit_ytd_k'])}
    if fy:fyvals.update({k:v for k,v in fy.items() if v is not None})
    if not finite_values(current,['revenue_k','gross_profit_k','operating_profit_k','pretax_profit_k','net_income_k','parent_net_income_k']):
        return dict(code=code,name=latest.get('name'),status='TAX_PARENT_EARNINGS_COMPONENTS_MISSING',rankable=False)
    r=current['revenue_k'];rfy=fyvals['revenue_k'];prior_r=number(pr['revenue_ytd_k'])
    if min(r,rfy,prior_r)<=0:return dict(code=code,name=latest.get('name'),status='NONPOSITIVE_REVENUE_SPECIAL_MODEL_REQUIRED',rankable=False)
    warnings=[]
    if thin:warnings.append('LOW_LIQUIDITY_OR_PRICE_SHADOW_ONLY_NO_PRIMARY_RANKING')
    elif low_turnover_review:warnings.append('BELOW_12M_SINGLE_DAY_TURNOVER_RESEARCH_ONLY_REQUIRES_EXIT_CAPACITY_REVIEW')
    if primary:
        for a,b in [('revenue_k','revenue_ytd_k'),('gross_profit_k','gross_profit_ytd_k'),('operating_profit_k','operating_profit_ytd_k')]:
            if abs(current[a]-number(latest[b]))>1:raise ValueError('PRIMARY_MIRROR_'+a+'_MISMATCH')
    elif event:warnings.append('LATEST_EARNINGS_IS_ISSUER_SELF_REPORT_NOT_REVIEWED_FULL_STATEMENTS')
    else:warnings.append('CURRENT_DETAIL_IS_OFFICIAL_BATCH_SUMMARY_NOT_ORIGINAL_ISSUER_NOTES')
    if not event:
        for a,b in [('revenue_k','revenue_ytd_k'),('gross_profit_k','gross_profit_ytd_k'),('operating_profit_k','operating_profit_ytd_k')]:
            if abs(current[a]-number(latest[b]))>1:return unavailable('CURRENT_OFFICIAL_AND_HISTORY_BASIS_MISMATCH')
    month_year,month=map(int,data.revenue_month.split('-'))
    if month_year<y or month_year>y+1:return dict(code=code,name=latest.get('name'),status='MONTHLY_FINANCIAL_YEAR_BRIDGE_NOT_ALIGNED',rankable=False)
    if event and (month_year,month)<(y,q*3):return unavailable('EARNINGS_EVENT_AHEAD_OF_MONTHLY_REVENUE_BASIS')
    ytd=number(rev.get('ytd_revenue_k'));oldytd=number(rev.get('last_year_ytd_revenue_k'));my=number(rev.get('monthly_yoy_pct'));yy=number(rev.get('ytd_yoy_pct'))
    monthly_prior_annual=rfy
    if month_year==y+1 and q!=4:
        monthly_prior_annual=getattr(data,'annual_monthly',{}).get((code,month_year-1))
        if monthly_prior_annual is None:return dict(code=code,name=latest.get('name'),status='YEAR_ROLLOVER_DECEMBER_REVENUE_REQUIRED',rankable=False)
        warnings.append('PRIOR_ANNUAL_REVENUE_FROM_DECEMBER_MONTHLY_NOT_AUDITED_ANNUAL')
    if None in (ytd,oldytd,my,yy) or oldytd<=0 or monthly_prior_annual<oldytd:
        return dict(code=code,name=latest.get('name'),status='MONTHLY_FINANCIAL_REVENUE_BASIS_RECONCILIATION_PENDING',rankable=False)
    gh=r/prior_r-1;trend=statistics.median([gh,yy/100,my/100]);observed=[]
    for period,row in rs.items():
        py,pq=quarter_key(period);comp=rs.get(f'{py-1}-Q{pq}')
        if comp and number(comp.get('revenue_ytd_k')) and number(row.get('revenue_ytd_k')):observed.append(number(row['revenue_ytd_k'])/number(comp['revenue_ytd_k'])-1)
    g=calibration['revenue_persistence']*trend;spread=max(.03,(pct(observed,.75) or 0)-(pct(observed,.25) or 0));g_bear=max(-.95,g-spread);g_bull=g+spread
    r_current_year=ytd+(monthly_prior_annual-oldytd)*max(0,1+g);target_year=int(target_date[:4]);years=target_year-month_year
    if years<0 or years>3:raise ValueError('FORECAST_HORIZON_OUTSIDE_SUPPORTED_RANGE')
    r_base=r_current_year*max(.05,1+g)**years
    gm_fy=fyvals['gross_profit_k']/rfy;gm_now=current['gross_profit_k']/r;gm_prior=number(pr['gross_profit_ytd_k'])/prior_r
    quarter_margin_velocity=recent_quarter_gm_velocity(rs,valuation_period)
    cost_fy=(fyvals['gross_profit_k']-fyvals['operating_profit_k'])/rfy;cost_now=(current['gross_profit_k']-current['operating_profit_k'])/r
    cost_prior=(number(pr['gross_profit_ytd_k'])-number(pr['operating_profit_ytd_k']))/prior_r
    if min(cost_fy,cost_now,cost_prior)<0:return dict(code=code,name=latest.get('name'),status='OPERATING_OTHER_GAINS_OR_SEGMENT_MODEL_REQUIRED',rankable=False)
    gm=max(0,min(1,gm_fy+calibration['margin_persistence']*(gm_now-gm_prior)));raw_cost=cost_fy+calibration['cost_persistence']*(cost_now-cost_prior);cost=max(0,raw_cost)
    historical_gm=[number(v['gross_profit_ytd_k'])/number(v['revenue_ytd_k']) for v in rs.values() if number(v.get('revenue_ytd_k')) and number(v.get('gross_profit_ytd_k')) is not None]
    gm_spread=max(.01,(pct(historical_gm,.75)-pct(historical_gm,.25))/2)
    raw_base_gm=gm
    recovery=assess_margin_recovery(rs,valuation_period,raw_base_gm,gm_now,my,yy,rev.get('industry',''))
    if recovery['applied']:
        gm=recovery['provisional_base_gm'];warnings.append('CONDITIONAL_GM_RECOVERY_RESEARCH_ASSUMPTION_NOT_CERTIFIED')
    elif recovery['candidate']:
        warnings.append('MARGIN_NORMALIZATION_NEEDS_ISSUER_DRIVER_REVIEW')
    nonop=current['pretax_profit_k']-current['operating_profit_k'];nonop_status='REPORTED_GAP_COMPOSITION_UNRESOLVED'
    if primary:
        no=primary['nonop_current'];nopr=primary['nonop_prior_ytd'];nofy=primary.get('nonop_prior_fy')
        if nofy and None not in (nofy['sensitivity_gap_ex_volatile_k'],no['sensitivity_gap_ex_volatile_k'],nopr['sensitivity_gap_ex_volatile_k']):
            nonop=nofy['sensitivity_gap_ex_volatile_k']+no['sensitivity_gap_ex_volatile_k']-nopr['sensitivity_gap_ex_volatile_k'];nonop_status='OBSERVED_COMPONENT_ZERO_FX_FV_DISPOSAL_SENSITIVITY_IMPAIRMENT_RETAINED'
        elif no['sensitivity_gap_ex_volatile_k'] is not None:
            nonop=no['sensitivity_gap_ex_volatile_k']*4/q;nonop_status='YTD_COMPONENT_SENSITIVITY_ANNUAL_SEASONALITY_UNVERIFIED'
    elif event and fyvals.get('pretax_profit_k') is not None:
        nonop=(fyvals['pretax_profit_k']-fyvals['operating_profit_k']+event['current']['nonoperating_k']-event['prior']['nonoperating_k'])
        nonop_status='ISSUER_SELF_REPORT_YTD_NONOPERATING_DELTA_WITH_PRIOR_FY_COMPONENTS_UNRESOLVED'
    elif fyvals.get('pretax_profit_k') is not None:nonop=fyvals['pretax_profit_k']-fyvals['operating_profit_k']
    tax=(current['pretax_profit_k']-current['net_income_k'])/current['pretax_profit_k'] if current['pretax_profit_k']>0 else None
    if tax is None or not 0<=tax<=.5:tax=.2;warnings.append('TAX_RATE_20PCT_SENSITIVITY_NOT_VERIFIED')
    fraction=current['parent_net_income_k']/current['net_income_k'] if current['net_income_k']>0 else None
    if fraction is None or not 0<fraction<=1.2:fraction=1.;warnings.append('PARENT_PROFIT_FRACTION_ASSUMED_NOT_VERIFIED')
    weighted=e.get('weighted_diluted_disclosed',{}).get(code) if primary else None
    share=share_scenarios(master['issued_shares'],e.get('bonds',{}).get(code,[]),weighted)
    if share['unresolved_terms']:warnings.append('POST_SNAPSHOT_CB_TERMS_UNVERIFIED')
    own=[v['pe'] for v in e.get('pe_history',{}).get(code,[])];peers=[v['pe'] for v in e.get('peers',{}).get(master['industry_code'],[]) if v['code']!=code]
    pe=min(pct(own,.5),pct(peers,.5)) if len(own)>=8 and len(peers)>=5 else None
    pe_bear=min(pct(own,.25),pct(peers,.25)) if pe else None;pe_bull=min(pct(own,.75),pct(peers,.75)) if pe else None
    if pe is None:warnings.append('HISTORICAL_OR_PEER_PE_SAMPLE_INSUFFICIENT')
    industry=rev.get('industry','')
    cyclical=is_cyclical(industry)
    matched_peer_review=None
    if e.get('matched_peers',{}).get(code):
        matched_peer_review=matched_multiples(e['matched_peers'][code],data,code,valuation_period,target_date,asof,cyclical)
        pe,pe_bear,pe_bull=(matched_peer_review[k] for k in ('base','bear','bull'))
    # Retain legacy valuation caps. Recognizing a new cyclical sector must not
    # silently lower its Base PE before a sector-specific holdout evaluation.
    legacy_cycle_pe_cap=any(x in industry for x in ('鋼鐵','航運','建材營造','電子通路','電器電纜'))
    if legacy_cycle_pe_cap and not matched_peer_review:
        warnings.append('CYCLICAL_OR_PROJECT_DELIVERY_REQUIRES_COMPANY_BRIDGE')
        if pe is not None:pe=min(pe,pe_bear)
    elif cyclical:
        warnings.append('CYCLICAL_SECTOR_RESEARCH_ONLY_PE_UNCHANGED_PENDING_BACKTEST')
    base=operating_scenario(r_base,gm,cost,nonop,tax,fraction,share['base_shares'],pe)
    bear=operating_scenario(r_current_year*max(.05,1+g_bear)**years,max(0,raw_base_gm-gm_spread),cost+gm_spread/2,nonop,min(.5,tax+.02),fraction,share['base_shares'],pe_bear)
    recovery_gm=min(1,max(gm+gm_spread,pct(historical_gm,.75)))
    bull=operating_scenario(r_current_year*max(.05,1+g_bull)**years,recovery_gm,max(0,cost-gm_spread/2),nonop,tax,fraction,share['base_shares'],pe_bull)
    bull['gross_margin_case']='CONDITIONAL_RECOVERY_TO_PRIOR_UPPER_QUARTILE_NOT_A_PROBABILITY'
    for sc in (base,bear,bull):sc.update(returns(sc['target_price'],close,None,asof[:10],target_date))
    cf=data.cash.get(key,{}).get(data.period,{});ocf=number(cf.get('operating_cashflow_ytd_k'));ppe=prepaid=cash_k=None
    cash_primary=data.primary(code)
    if cash_primary:
        cash_values=cash_primary['values'];ocf=cash_values.get('ocf_k');ppe=cash_values.get('ppe_cash_flow_signed_k');prepaid=cash_primary.get('equipment_prepaid_signed_k');cash_k=cash_values.get('cash_k')
    if event:warnings.append('CASHFLOW_AND_NOTES_STILL_REFER_TO_PRIOR_REVIEWED_PERIOD')
    capital_event=e.get('issuer_events',{}).get(code);div=put=None
    if capital_event:
        div=capital_event['dividend']['indicative_cash_twd']/1000;put=capital_event['convertible_put']['full_exercise_sensitivity_twd']/1000;warnings.append('OLD_CASH_DIVIDEND_AND_CB_PUT_STATIC_SENSITIVITY_ONLY')
    flow=liquidity(cash_k,ocf,ppe,prepaid,div,put)
    if ocf is not None and ocf<0:warnings.append('NEGATIVE_OCF_CYCLE_AND_COLLECTION_REVIEW')
    if gm_now<gm_prior:warnings.append('YTD_GROSS_MARGIN_DECLINED')
    leading_signal=revenue_leading_signal(my,yy,gh,gm_now,gm_prior)
    if my<=0 or yy<=0:warnings.append('MONTHLY_OR_YTD_REVENUE_GROWTH_NONPOSITIVE')
    coverage=e.get('primary_cash_eight_quarters',{}).get(code,{})
    gates=research_gates(primary,code,valuation_period,flow,coverage.get('eight_quarter_key_income_cash_values_reconciled'))
    for name,value in e.get('certificates',{}).get(code,{}).items():
        if name in GATES:gates[name]=value
    if event:
        gates['original_eight_quarter_statements']=gate('PENDING','LATEST_SELF_REPORT_IS_NOT_REVIEWED_QUARTERLY_STATEMENTS')
        gates['forecast_bridge']=gate('PENDING','LATEST_EARNINGS_EVENT_REBASED_ISSUER_2027_OPERATING_BRIDGE_REQUIRED')
    # A provisional normalized Base cannot inherit a generic forecast PASS:
    # the issuer-specific recovery mechanism needs a documented signoff.
    if (recovery['applied'] and not e.get('issuer_operating_bridges',{}).get(code)
        and gates['forecast_bridge'].get('status')=='PASS'
        and gates['forecast_bridge'].get('margin_normalization_review_complete') is not True):
        gates['forecast_bridge']=gate('PENDING','CONDITIONAL_MARGIN_RECOVERY_ISSUER_SIGNOFF_REQUIRED')
    if thin:
        gates['tradability']=gate('PENDING','LOW_SINGLE_DAY_TRADING_VALUE_OR_PRICE_REQUIRES_MULTI_SESSION_REVIEW')
    elif low_turnover_review and gates['tradability'].get('status')!='FAIL':
        # A single session worth 1m-12m is discoverable, never an automatic A+ PASS.
        # A documented multiple-session fill/spread and exit-capacity review is required.
        t=gates['tradability']
        if not (t.get('multi_session_liquidity_verified') is True and t.get('exit_capacity_verified') is True):
            gates['tradability']=gate('PENDING','BELOW_12M_DAILY_TURNOVER_REQUIRES_MULTI_SESSION_SPREAD_AND_EXIT_CAPACITY_REVIEW')
    if primary and primary['qualified_review'] and gates['auditor_scope'].get('status')=='PASS' and not gates['auditor_scope'].get('materiality_assessment_complete'):
        gates['auditor_scope']=gate('PENDING','QUALIFIED_SCOPE_MATERIALITY_SIGNOFF_REQUIRED')
    if gates['fully_diluted_shares'].get('status')=='PASS' and (share['unresolved_terms'] or share['missing_legal_conversion_inputs'] or gates['fully_diluted_shares'].get('forecast_denominator_shares')!=share['base_shares']):
        gates['fully_diluted_shares']=gate('PENDING','ACTUAL_DENOMINATOR_OR_CB_TERMS_NOT_RECONCILED')
    stress_shares=share['conversion_price_down_10pct_full_conversion_shares']
    dilution_stress_factor=share['base_shares']/stress_shares if stress_shares else None
    stress=(base['target_price']*POLICY['stress_eps_factor']*POLICY['stress_pe_factor']*dilution_stress_factor/close-1)*100 if base['target_price'] is not None and dilution_stress_factor is not None else None
    if primary and primary['qualified_review']:warnings.append('QUALIFIED_REVIEW_MATERIALITY_PENDING' if gates['auditor_scope'].get('status')!='PASS' else 'QUALIFIED_REVIEW_MATERIALITY_ASSESSED')
    specialist=[];business=primary.get('business_description','') if primary else ''
    developer=bool(re.search(r'興建.*住宅|大樓.*(?:出售|出租)|住宅.*開發|不動產.*開發',business))
    contractor=bool(re.search(r'無塵室|廠務|工程之設計|工程規劃|統包|機電.*建造|承攬.*工程|土木|建築工程|營造',business) or re.search('工程|營造',latest.get('name','')))
    if '建材營造' in industry or contractor or developer:specialist.append('PROJECT_DELIVERY_BACKLOG_REVENUE_SCHEDULE_REQUIRED')
    if '電子通路' in industry:specialist.append('DISTRIBUTOR_UNIT_SPREAD_INVENTORY_CYCLE_REQUIRED')
    if raw_cost<0:specialist.append('NEGATIVE_EXTRAPOLATED_OPEX_NOT_AN_ADMISSIBLE_BASE')
    if base['price_upside_pct'] is not None and base['price_upside_pct']>150:specialist.append('EXTREME_VALUATION_OPERATING_BRIDGE_REQUIRED')
    bridge=e.get('issuer_operating_bridges',{}).get(code)
    if bridge:
        if recovery['applied']:
            recovery['status']='SPECIFIC_ISSUER_BRIDGE_OVERRIDES_GENERIC_RECOVERY'
            recovery['applied']=False
        cases=issuer_case(bridge,code,valuation_period,asof,target_date,share['base_shares'],{'base':pe,'bear':pe_bear,'bull':pe_bull});base,bear,bull=(cases[n] for n in ('base','bear','bull'))
        for sc in (base,bear,bull):sc.update(returns(sc['target_price'],close,None,asof[:10],target_date))
        if developer and any(cases[n]['valuation_method']!='NAV' for n in cases):raise ValueError('PROPERTY_DEVELOPER_REQUIRES_ASSET_VALUE_BRIDGE')
        specialist=[];stress=(base['target_price']*.81*dilution_stress_factor/close-1)*100 if base['target_price'] is not None and dilution_stress_factor is not None and base.get('valuation_method')=='PE' else None
    elif specialist and gates['forecast_bridge'].get('status')=='PASS':gates['forecast_bridge']=gate('PENDING','SPECIALIST_OPERATING_INPUTS_REQUIRED')
    equity_offering=equity_offering_overlay(data.root,code,asof,target_date,base,master['issued_shares']) if getattr(data,'root',None) is not None else None
    if equity_offering:
        warnings.append('DISCLOSED_EQUITY_OFFERING_REQUIRES_UNISSUED_SHARE_RECONCILIATION')
        gates['fully_diluted_shares']=gate('PENDING','ANNOUNCED_EQUITY_OFFERING_SHARE_PROCEEDS_AND_FUTURE_RETURNS_NOT_VERIFIED')
    new_information_blocked=getattr(data,'earnings_event_states',{}).get(code,{}).get('blocks_current_decision',False)
    point=base['target_price'] is not None and not share['missing_legal_conversion_inputs'] and not specialist and not new_information_blocked
    if not point:warnings.append('POINT_VALUATION_NOT_COMPARABLE_WITH_UNRESOLVED_INPUTS')
    binding=forecast_binding(code,valuation_period,target_date,dict(base=base,bear=bear,bull=bull),event)
    if getattr(data,'strategy_variant','current-information')!='current-information':
        gates['forecast_bridge']=gate('PENDING','COUNTERFACTUAL_SHADOW_VARIANT_NOT_CURRENT_INFORMATION')
    forecast=gates['forecast_bridge']
    if forecast.get('status')=='PASS' and not matches_forecast(forecast,binding,code_fingerprint(),data.price_date,target_date):
        gates['forecast_bridge']=gate('PENDING','FORECAST_CERTIFICATE_DOES_NOT_MATCH_CURRENT_ECONOMIC_INPUTS_OR_METHOD')
    governance=issuer_review(getattr(data,'governance_reviews',{}),code,market)
    gates=reopen_quality_reviews(gates,governance)
    governance_blocked=governance['blocks_recommendation']
    if governance_blocked:warnings.append(governance['status'])
    certification=certify(code,base['price_upside_pct'] if point else None,stress if point else None,gates,asof,valuation_period)
    # Evidence completeness controls formal certification. It must not impose
    # membership in a hand-selected legacy cohort on the research ranking.
    rankable=point and not thin
    exclusions=list(specialist)
    if new_information_blocked:exclusions.append('NEW_ORIGINAL_EARNINGS_NOT_RECONCILED_OLD_VALUATION_DIAGNOSTIC_ONLY')
    if share['missing_legal_conversion_inputs']:exclusions.append('CB_LEGAL_CONVERSION_INPUTS_MISSING')
    if pe is None:exclusions.append('PE_SAMPLE_INSUFFICIENT')
    if base['eps']<=0:exclusions.append('NONPOSITIVE_EARNINGS_REQUIRES_NON_PE_VALUATION')
    return dict(code=code,name=latest.get('name'),market=market,industry=industry,financial_period=valuation_period,
      reviewed_financial_period=data.period,cashflow_financial_period=data.period,forecast_binding=binding,
      fresh_earnings_update=dict(applied=bool(event),source_kind=event['source_kind'] if event else None,event=event,
        method='EXISTING_CALIBRATED_ACCOUNTING_EQUATIONS_WITH_NEW_RECONCILED_YTD_FACTS' if event else None,
        annual_forecast_still_requires_issuer_operating_bridge=True,
        event_state=getattr(data,'earnings_event_states',{}).get(code)),
      reference_close=close,single_day_turnover_ntd=turnover,
      liquidity_research_band=('SHADOW_BELOW_1M_OR_PRICE_FLOOR' if thin else 'RESEARCH_1M_TO_12M_PENDING_EXECUTION' if low_turnover_review else 'RESEARCH_AT_LEAST_12M_PENDING_EVIDENCE'),
      price_date=data.price_date,revenue_month=data.revenue_month,estimate_vintage=asof,target_date=target_date,
      source_tier='ISSUER_SELF_REPORTED_ORIGINAL_TABLE' if event else 'ORIGINAL_CURRENT_ISSUER_NUMERICS' if primary else 'OFFICIAL_CURRENT_BATCH_WITH_UNVERIFIED_HISTORICAL_DETAIL',rankable=rankable,point_valuation_available=point,
      original_current_issuer_numeric_checked=primary is not None or bool(event),exclusion_reasons=exclusions,
      base=base,bear=bear,bull=bull,share_bridge=share,equity_offering_overlay=equity_offering,liquidity=flow,primary_ttm_cash=coverage or None,
      revenue_bridge=dict(actual_ytd_k=ytd,prior_year_annual_revenue_k=monthly_prior_annual,prior_year_remaining_k=monthly_prior_annual-oldytd,annual_current_year_estimate_k=r_current_year,assumed_annual_growth=g,observed_growth=observed,
        trend_inputs=dict(financial_ytd_yoy=gh,monthly_ytd_yoy=yy/100,latest_month_yoy=my/100),
        annual_forward_growth_is_extrapolation_not_validated=True,issuer_capacity_order_ASP_cost_bridge_complete=bool(e.get('issuer_operating_bridges',{}).get(code))),
      coefficient_training=dict(train_target=calibration.get('train_target'),training_cases=calibration['train_count'],revenue_persistence=calibration['revenue_persistence'],margin_persistence=calibration['margin_persistence'],cost_persistence=calibration['cost_persistence']),
      margin_bridge=dict(prior_full_year_gm=gm_fy,current_ytd_gm=gm_now,prior_ytd_gm=gm_prior,unadjusted_base_gm=raw_base_gm,base_gm=base['gross_margin'],base_opex_ratio=cost,
        quarter_margin_velocity=quarter_margin_velocity),margin_recovery=recovery,
      nonoperating_bridge=dict(base_k=nonop,method=nonop_status,component_assumptions_certified=False,
        reported_ytd_gap_k=current['pretax_profit_k']-current['operating_profit_k'],
        reported_ytd_pretax_k=current['pretax_profit_k'],
        reported_ytd_abs_gap_share_pretax_pct=100*abs(current['pretax_profit_k']-current['operating_profit_k'])/current['pretax_profit_k'] if current['pretax_profit_k']>0 else None,
        reported_ytd_gap_is_signed_original_components=False),
      eps_bridge_reference=dict(
        reported_ytd_parent_profit_k=current['parent_net_income_k'],
        fiscal_ytd_quarters=q,
        linear_annualized_ytd_parent_eps_at_model_denominator=current['parent_net_income_k']*1000*(4/q)/share['base_shares'] if share['base_shares']>0 else None,
        target_eps_vs_ytd_linear_annualized_pct=100*(base['eps']/(current['parent_net_income_k']*1000*(4/q)/share['base_shares'])-1) if share['base_shares']>0 and current['parent_net_income_k']>0 and base.get('eps') is not None else None,
        linear_annualization_not_seasonality_adjusted=True,
        not_an_actual_next_year_eps_growth_rate=True,
        original_operating_bridge_certified=False),
      pe_bridge=dict(issuer_samples=len(own),peer_samples=len(peers),base=pe,bear=pe_bear,bull=pe_bull,matched_forward_peer_review=matched_peer_review,
        exact_matched_peer_review_complete='matched_peers_and_cycle' in certification['gates_passed']),
      gates=gates,certification=certification,formal_Aplus=certification['formal_Aplus'],formal_Aplusplus=certification['formal_Aplusplus'],status=certification['status'],warning_flags=warnings,
      governance_review=governance,recommendation_blocked=governance_blocked,
      stress_eps90_pe90_upside_pct=stress,specialist_model_requirements=specialist,base_scenario_is_admissible=point,
      business_profile=dict(property_development_observed=developer,engineering_business_observed=contractor,classification_source='ISSUER_HISTORY_AND_ORGANIZATION_NOTE' if business else 'INDUSTRY_ONLY'),
      base_scenario_role='RESEARCH_FORECAST_UNCERTIFIED' if point else 'DIAGNOSTIC_ONLY_NOT_ADMISSIBLE_BASE',
      early_recovery_watch=my>0 and yy>0 and gm_now<gm_prior and bull['target_price'] is not None,
      revenue_leading_discovery=leading_signal,
      cycle_research=dict(cyclical_sector=cyclical,sector_classification='INDUSTRY_PROXY_NOT_ISSUER_VERIFIED',
        legacy_pe_cap_applied=legacy_cycle_pe_cap,research_only=True,cycle_score_not_calibrated=True),
      research_target_price_scenario=base['target_price'] if point else None,target_year_eps_scenario=base['eps'] if point else None,
      research_2027_price_scenario=base['target_price'] if point and target_year==2027 else None,eps_2027_base_scenario=base['eps'] if point and target_year==2027 else None,
      research_pe_assumption=pe,scenario_upside_pct=base['price_upside_pct'] if point else None,
      rating='重大治理待查' if governance_blocked else '估值待驗' if not certification['quality_complete'] else certification['status'],research_lane='重大治理待查／營運情境參考' if governance_blocked else ('原始當期研究候選待驗' if primary else '官方彙總研究候選待驗') if rankable else '來源或估值資料待補',
      score=None,company_forecast_confirmed=False,probabilities_calibrated=False)
