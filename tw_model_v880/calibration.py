"""Cross-period accounting forecast validation, not a PIT return backtest."""
import statistics
from .math import number,quarter_key
GRID=(0.,.25,.5,.75,1.)
def ratio(r,k):return number(r[k])/number(r['revenue_ytd_k'])
def fit_accounting(history,last_period,industry_map=None):
    y,q=quarter_key(last_period);train_year=y-1;train=[];hold=[]
    for issuer,rs in history.items():
        try:
            fy=rs[f'{train_year}-Q4'];prior=rs[f'{train_year-1}-Q4'];nine=rs[f'{train_year}-Q3'];oldnine=rs[f'{train_year-1}-Q3']
            rfy=number(fy['revenue_ytd_k']);rp=number(prior['revenue_ytd_k']);rn=number(nine['revenue_ytd_k']);ron=number(oldnine['revenue_ytd_k'])
            if min(rfy,rp,rn,ron)<=0 or rp<=ron or rfy<=rn:continue
            vals=[ratio(r,'gross_profit_ytd_k') for r in (fy,prior,nine,oldnine)]
            costs=[ratio(r,'gross_profit_ytd_k')-ratio(r,'operating_profit_ytd_k') for r in (fy,prior,nine,oldnine)]
            if any(abs(x)>1.5 for x in vals+costs):continue
            train.append(dict(issuer=issuer,actual_revenue=rfy,ytd=rn,prior_remaining=rp-ron,growth=rn/ron-1,
              actual_gm=vals[0],prior_gm=vals[1],delta_gm=vals[2]-vals[3],actual_cost=costs[0],prior_cost=costs[1],delta_cost=costs[2]-costs[3]))
            if q>=2:
                a=rs[f'{y}-Q2'];b=rs[f'{y-1}-Q2'];c=rs[f'{y}-Q1'];d=rs[f'{y-1}-Q1']
                if min(number(r['revenue_ytd_k']) for r in (a,b,c,d))<=0:continue
                if number(a['revenue_ytd_k'])<=number(c['revenue_ytd_k']) or number(b['revenue_ytd_k'])<=number(d['revenue_ytd_k']):continue
                hold.append(dict(issuer=issuer,actual_revenue=number(a['revenue_ytd_k']),prior_revenue=number(b['revenue_ytd_k']),known_prefix=number(c['revenue_ytd_k']),prior_prefix=number(d['revenue_ytd_k']),growth=number(c['revenue_ytd_k'])/number(d['revenue_ytd_k'])-1,
                  actual_gm=ratio(a,'gross_profit_ytd_k'),prior_gm=ratio(b,'gross_profit_ytd_k'),delta_gm=ratio(c,'gross_profit_ytd_k')-ratio(d,'gross_profit_ytd_k'),
                  actual_cost=ratio(a,'gross_profit_ytd_k')-ratio(a,'operating_profit_ytd_k'),prior_cost=ratio(b,'gross_profit_ytd_k')-ratio(b,'operating_profit_ytd_k'),
                  delta_cost=(ratio(c,'gross_profit_ytd_k')-ratio(c,'operating_profit_ytd_k'))-(ratio(d,'gross_profit_ytd_k')-ratio(d,'operating_profit_ytd_k'))))
        except (KeyError,TypeError,ZeroDivisionError,ValueError):continue
    if len(train)<50:
        return dict(status='INSUFFICIENT_CROSS_PERIOD_SAMPLE',revenue_persistence=.5,margin_persistence=.5,cost_persistence=.5,
          coefficients_are_fallback_assumptions=True,train_count=len(train),holdout_count=len(hold),pit_return_backtest_passed=False)
    # Fit the unobserved quarter, not the full year dominated by nine known months.
    # Use the same known-prefix + next-quarter horizon in the untouched holdout.
    legacy_lossr=lambda a:statistics.median(abs((r['ytd']+r['prior_remaining']*(1+a*r['growth']))/r['actual_revenue']-1) for r in train)
    lossr=lambda a:statistics.median(abs(r['prior_remaining']*max(.05,1+a*r['growth'])/(r['actual_revenue']-r['ytd'])-1) for r in train)
    lossm=lambda a:statistics.median(abs(r['prior_gm']+a*r['delta_gm']-r['actual_gm']) for r in train)
    lossc=lambda a:statistics.median(abs(r['prior_cost']+a*r['delta_cost']-r['actual_cost']) for r in train)
    alpha=min(GRID,key=lossr);legacy_alpha=min(GRID,key=legacy_lossr);beta=min(GRID,key=lossm);gamma=min(GRID,key=lossc)
    def metrics(rows,rv,gm,co):
        if not rows:return None
        return dict(n=len(rows),revenue_median_absolute_pct_error=statistics.median(abs(rv(r)/r['actual_revenue']-1)*100 for r in rows),
          revenue_wape_pct=sum(abs(rv(r)-r['actual_revenue']) for r in rows)/sum(r['actual_revenue'] for r in rows)*100,
          gross_margin_median_abs_pp=statistics.median(abs(gm(r)-r['actual_gm'])*100 for r in rows),
          opex_ratio_median_abs_pp=statistics.median(abs(co(r)-r['actual_cost'])*100 for r in rows))
    def future_revenue(r,a):return r['known_prefix']+(r['prior_revenue']-r['prior_prefix'])*max(.05,1+a*r['growth'])
    train_metrics=metrics(train,lambda r:r['ytd']+r['prior_remaining']*max(.05,1+alpha*r['growth']),lambda r:r['prior_gm']+beta*r['delta_gm'],lambda r:r['prior_cost']+gamma*r['delta_cost'])
    hold_metrics=metrics(hold,lambda r:future_revenue(r,alpha),lambda r:r['prior_gm']+beta*r['delta_gm'],lambda r:r['prior_cost']+gamma*r['delta_cost'])
    baseline=metrics(hold,lambda r:r['prior_revenue'],lambda r:r['prior_gm'],lambda r:r['prior_cost']);sectors={}
    if industry_map:
        for name in sorted({industry_map.get(k[1]) for k in history}-{None,''}):
            subset={k:v for k,v in history.items() if industry_map.get(k[1])==name}
            if len(subset)<50:continue
            fit=fit_accounting(subset,last_period)
            if fit['train_count']>=50:sectors[name]=fit
    def parameter(r,name,default):return sectors.get(industry_map.get(r['issuer'][1]) if industry_map else None,{}).get(name,default)
    deployed=metrics(hold,lambda r:future_revenue(r,parameter(r,'revenue_persistence',alpha)),
      lambda r:r['prior_gm']+parameter(r,'margin_persistence',beta)*r['delta_gm'],lambda r:r['prior_cost']+parameter(r,'cost_persistence',gamma)*r['delta_cost'])
    def revenue_metrics(rows,forecast,actual):
        if not rows:return None
        return dict(n=len(rows),median_absolute_pct_error=statistics.median(abs(forecast(r)/actual(r)-1)*100 for r in rows),
          wape_pct=sum(abs(forecast(r)-actual(r)) for r in rows)/sum(actual(r) for r in rows)*100)
    new_quarter=lambda r:future_revenue(r,parameter(r,'revenue_persistence',alpha))-r['known_prefix']
    old_quarter=lambda r:(r['prior_revenue']-r['prior_prefix'])*max(.05,1+parameter(r,'legacy_revenue_persistence',legacy_alpha)*r['growth'])
    actual_quarter=lambda r:r['actual_revenue']-r['known_prefix']
    high_growth=[r for r in hold if r['growth']>=.2]
    return dict(status='ACCOUNTING_CROSS_PERIOD_VALIDATION_ONLY',train_target=f'{train_year}-Q4',holdout_target=f'{y}-Q2' if q>=2 else None,
      coefficients_frozen_before_holdout=True,grid=list(GRID),revenue_persistence=alpha,legacy_revenue_persistence=legacy_alpha,margin_persistence=beta,cost_persistence=gamma,
      revenue_fit_target='UNOBSERVED_STANDALONE_QUARTER_NOT_KNOWN_PREFIX_DOMINATED_FULL_YEAR',
      revenue_holdout_horizon='KNOWN_Q1_PLUS_FORECAST_STANDALONE_Q2',annual_forward_growth_is_extrapolation_not_validated=True,
      holdout_standalone_quarter_revenue=revenue_metrics(hold,new_quarter,actual_quarter),
      holdout_standalone_quarter_legacy_coefficient=revenue_metrics(hold,old_quarter,actual_quarter),
      holdout_high_growth_quarter_revenue=revenue_metrics(high_growth,new_quarter,actual_quarter),
      holdout_high_growth_legacy_coefficient=revenue_metrics(high_growth,old_quarter,actual_quarter),
      holdout_known_prefix_zero_growth_baseline=revenue_metrics(hold,lambda r:future_revenue(r,0),lambda r:r['actual_revenue']),
      train_count=len(train),holdout_count=len(hold),train_metrics=train_metrics,holdout_metrics=hold_metrics,holdout_no_change_baseline=baseline,
      sector_parameters=sectors,minimum_sector_training_sample=50,deployed_sector_or_global_holdout_metrics=deployed,
      survivor_universe_bias_not_resolved=True,company_publication_times_verified=False,pit_return_backtest_passed=False,
      not_a_probability_calibration=True,not_a_trading_performance_claim=True)
