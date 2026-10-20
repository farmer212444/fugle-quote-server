"""Revenue-first discovery lane. No formal A+ gate or Base valuation override.

Uses only already ingested, dated monthly/YTD and financial figures.
Thresholds are exploratory, NOT trained probabilities or trading rules.
"""
from .math import number

def revenue_leading_signal(monthly_yoy_pct, ytd_yoy_pct, financial_ytd_yoy,
                           current_gm=None, prior_gm=None):
    monthly=number(monthly_yoy_pct)
    ytd=number(ytd_yoy_pct)
    fy=number(financial_ytd_yoy)
    gm=number(current_gm)
    prior=number(prior_gm)
    if monthly is None or ytd is None or fy is None:
        return dict(status="INSUFFICIENT_DATED_REVENUE_DATA",priority="NONE",
                    discovery_only=True,formal_quality_pass=False)
    # Monthly YoY vs cumulative YoY is a *momentum proxy*, not a true
    # month-on-month acceleration series or seasonality-adjusted causal proof.
    proxy=monthly-ytd
    growth=monthly>=20 and ytd>=5 and fy>0
    margin_deteriorating=(gm is not None and prior is not None and gm<prior)
    if growth and proxy>=15:
        status="EARLY_REVENUE_ACCELERATION"
        priority="HIGH"
    elif monthly>0 and ytd>0:
        status="POSITIVE_REVENUE_WATCH"
        priority="NORMAL"
    else:
        status="NO_POSITIVE_REVENUE_SIGNAL"
        priority="NONE"
    if margin_deteriorating and priority=="HIGH":
        status="REVENUE_ACCELERATION_WITH_MARGIN_CONVERSION_RISK"
    return dict(status=status,priority=priority,discovery_only=True,
                formal_quality_pass=False,monthly_yoy_pct=monthly,
                ytd_yoy_pct=ytd,financial_ytd_yoy_pct=fy*100,
                monthly_minus_ytd_yoy_pp=proxy,
                momentum_proxy_not_seasonally_adjusted=True,
                margin_conversion_risk=margin_deteriorating,
                base_valuation_unchanged=True,
                validation_status="EXPLORATORY_THRESHOLDS_NOT_WALK_FORWARD_VALIDATED")
