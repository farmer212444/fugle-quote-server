"""Consecutive standalone-quarter margin velocity from dated YTD statements.

Only in-year q>=2 quarters are compared to avoid joining a potentially stale
prior-year Q4 into a new annual reporting sequence. This is an audit trigger,
not a reason to revise EPS, PE, A+ or trading eligibility.
"""
from .math import number,quarter_key


def standalone_gm(history,year,quarter):
    """Return unrounded standalone gross margin (fraction) or None."""
    row=history.get(f'{year}-Q{quarter}')
    if not row:return None
    r=number(row.get('revenue_ytd_k'))
    gp=number(row.get('gross_profit_ytd_k'))
    if r is None or gp is None:return None
    if quarter>1:
        prior=history.get(f'{year}-Q{quarter-1}')
        if not prior:return None
        prior_r=number(prior.get('revenue_ytd_k'))
        prior_gp=number(prior.get('gross_profit_ytd_k'))
        if prior_r is None or prior_gp is None:return None
        r-=prior_r
        gp-=prior_gp
    if r<=0:return None
    return gp/r


def recent_quarter_gm_velocity(history,valuation_period):
    y,q=quarter_key(valuation_period)
    if q<2:
        return dict(status='IN_YEAR_PREVIOUS_STANDALONE_QUARTER_UNAVAILABLE',
                    period=valuation_period,not_a_2027_earnings_revision=True)
    latest=standalone_gm(history,y,q)
    previous=standalone_gm(history,y,q-1)
    if latest is None or previous is None:
        return dict(status='MISSING_OR_INCONSISTENT_CONSECUTIVE_QUARTER_YTD_INPUTS',
                    period=valuation_period,not_a_2027_earnings_revision=True)
    return dict(status='NORMALIZED_YTD_STANDALONE_MARGINS_UNCERTIFIED_NOTES',
        period=valuation_period,
        current_quarter=f'{y}-Q{q}',
        previous_quarter=f'{y}-Q{q-1}',
        current_standalone_gm_pct=100*latest,
        previous_standalone_gm_pct=100*previous,
        recent_standalone_vs_previous_gm_delta_pp=100*(latest-previous),
        source_method='CURRENT_YTD_MINUS_PREVIOUS_YTD_SEPARATE_SINGLE_QUARTER',
        original_issuer_notes_full_reviewed=False,
        not_a_2027_earnings_revision=True)
