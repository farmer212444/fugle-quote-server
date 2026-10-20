"""Conditional gross-margin normalization for research scenarios, NOT issuer certification.

Only information inside the as-of dataset is used. Historic stability plus revenue
acceleration motivates a research assumption; it does not prove a new factory's
learning curve has ended or guarantee a margin rebound.
"""
import math
from .math import number,quarter_key

EXCLUDED_SECTOR_FRAGMENTS=(
    '金融保險','航運','鋼鐵','建材營造','電子通路','觀光餐旅',
    '資訊服務','數位雲端','生技醫療','貿易百貨','油電燃氣',
)
MAX_FY_VOLATILITY=.025
MIN_CURRENT_SHORTFALL=.020
MIN_UNADJUSTED_SHORTFALL=.012
MAX_BASE_LIFT=.035

def _annual_margin(history,year):
    row=history.get(f'{year}-Q4')
    if not row:return None
    rev=number(row.get('revenue_ytd_k'))
    gp=number(row.get('gross_profit_ytd_k'))
    if rev is None or gp is None or rev<=0:return None
    margin=gp/rev
    return margin if math.isfinite(margin) and 0<=margin<=1 else None

def assess_margin_recovery(history,financial_period,unadjusted_gm,current_ytd_gm,
                           monthly_yoy_pct,ytd_yoy_pct,industry):
    """Return an explicitly provisional, capped, conditional 2027 recovery case.

    No recovered margin is ever interpreted as audited profitability, a forecast
    approval, factory causality, or an A+ quality gate. Bear must continue to use
    the original unrecovered margin so the stressed risk is not erased.
    """
    year,q=quarter_key(financial_period)
    last_complete=year if q==4 else year-1
    years=[last_complete-1,last_complete]
    older,recent=(_annual_margin(history,z) for z in years)
    result=dict(status='INSUFFICIENT_HISTORY',candidate=False,applied=False,
                unadjusted_base_gm=unadjusted_gm,
                provisional_base_gm=unadjusted_gm,
                annual_reference_years=years,annual_gm=[older,recent],
                normalized_gm=None,recovery_fraction=0.0,research_case_gm=None,
                base_uplift_pp=0.0,base_override_blocked=True,
                causal_factory_evidence_verified=False,
                holdout_validation_complete=False)
    if older is None or recent is None or current_ytd_gm is None:
        return result
    anchor=(older+recent)/2
    result['normalized_gm']=anchor
    if not all(math.isfinite(x) for x in (anchor,unadjusted_gm,current_ytd_gm)):
        result['status']='INVALID_INPUT';return result
    if abs(older-recent)>MAX_FY_VOLATILITY:
        result['status']='UNSTABLE_TWO_YEAR_REFERENCE_REQUIRES_COMPANY_REVIEW';return result
    if anchor-current_ytd_gm<MIN_CURRENT_SHORTFALL or anchor-unadjusted_gm<MIN_UNADJUSTED_SHORTFALL:
        result['status']='NO_MATERIAL_TEMPORARY_GM_DISCOUNT';return result
    result['candidate']=True
    if any(x in (industry or '') for x in EXCLUDED_SECTOR_FRAGMENTS):
        result['status']='SECTOR_SPECIALIST_OPERATING_DRIVERS_REQUIRED';return result
    monthly=number(monthly_yoy_pct);ytd=number(ytd_yoy_pct)
    if monthly is None or ytd is None:
        result['status']='REVENUE_ACCELERATION_EVIDENCE_MISSING';return result
    # Very high growth can be a tiny-base/acquisition effect; do not extrapolate.
    if monthly>200 or ytd>150:
        result['status']='EXTREME_REVENUE_GROWTH_REQUIRES_BUSINESS_RECONCILIATION';return result
    if monthly>=20 and ytd>=5:
        fraction=.75
    elif monthly>=10 and ytd>=2:
        fraction=.50
    else:
        result['status']='RECOVERY_DEMAND_SIGNALS_NOT_MET';return result
    lift=max(0,min(MAX_BASE_LIFT,fraction*(anchor-unadjusted_gm),anchor-unadjusted_gm))
    if lift<=0:
        result['status']='NO_POSITIVE_BASE_ADJUSTMENT';return result
    # Revenue is a discovery input.  Without a signed issuer operating
    # bridge it must not convert an historical-margin sensitivity into Base.
    result.update(status='REVENUE_LEAD_DISCOVERY_ONLY_ISSUER_BRIDGE_REQUIRED',
                  applied=False,provisional_base_gm=unadjusted_gm,
                  research_case_gm=unadjusted_gm+lift,
                  recovery_fraction=fraction,base_uplift_pp=100*lift)
    return result
