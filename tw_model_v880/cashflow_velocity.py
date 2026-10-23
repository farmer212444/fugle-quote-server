"""Same-year YTD operating cash flow to individual-quarter bridge.

Source: period-dated normalized official MOPS cashflow observations. A
sequential increase in OCF is not, on its own, proof of recurring FCF,
receivable collection, auditor-certified cash quality, or alpha.
"""
from .math import number,quarter_key


def operating_cashflow_quarter_bridge(history,period,effective_current_ocf_k=None):
    year,quarter=quarter_key(period)
    common=dict(period=period,
        source='DATED_NORMALIZED_MOPS_YTD_CASHFLOW_NOT_ORIGINAL_NOTES_ATTESTED',
        original_cash_notes_reconciled=False,
        working_capital_component_bridge_certified=False,
        one_quarter_improvement_is_not_sustained_cash_conversion=True,
        no_certification_or_forecast_changed=True)
    if quarter==1:
        return dict(common,status='NO_PREVIOUS_SAME_YEAR_QUARTER',
                    latest_standalone_ocf_k=None)
    cur=history.get(period) or {}
    previous_period=f'{year}-Q{quarter-1}'
    prev=history.get(previous_period) or {}
    now=number(cur.get('operating_cashflow_ytd_k'))
    old=number(prev.get('operating_cashflow_ytd_k'))
    if now is None or old is None:
        return dict(common,status='MISSING_OFFICIAL_YTD_CASHFLOW',
                    previous_period=previous_period,latest_standalone_ocf_k=None)
    if effective_current_ocf_k is not None:
        effective=number(effective_current_ocf_k)
        if effective is None or abs(effective-now)>max(1.,abs(now)*1e-6):
            return dict(common,status='EFFECTIVE_CASHFLOW_SOURCE_MISMATCH_RECONCILIATION_REQUIRED',
                        previous_period=previous_period,latest_standalone_ocf_k=None,
                        latest_ytd_ocf_normalized_k=now,
                        latest_ytd_ocf_effective_k=effective)
    quarter_value=now-old
    if old<0 and quarter_value>0:
        label='PREVIOUS_STANDALONE_NEGATIVE_CURRENT_POSITIVE' if quarter==2 else 'CURRENT_STANDALONE_POSITIVE_PREVIOUS_QUARTER_NOT_CONFIRMED_NEGATIVE'
    else:
        label='LATEST_STANDALONE_POSITIVE' if quarter_value>0 else 'LATEST_STANDALONE_NONPOSITIVE'
    return dict(common,status='DATED_NORMALIZED_YTD_BRIDGE',
        previous_period=previous_period,
        previous_ytd_ocf_k=old,
        latest_ytd_ocf_k=now,
        latest_standalone_ocf_k=quarter_value,
        earlier_standalone_ocf_k=old if quarter==2 else None,
        latest_standalone_ocf_positive=quarter_value>0,
        h1_or_current_ytd_ocf_still_negative=now<0,
        changed_sign_after_q1=quarter==2 and old<0 and quarter_value>0,
        observation_label=label,
        current_quarter_positive_does_not_override_negative_ytd_review=True)
