"""Evidence-first review order, separate from upside ranking and formal A+.

No return probabilities, learned confidence weights, or historical winner fitting.
A conservative -20% EPS/-20% PE calculation is a *sensitivity*, not a
quantile or a 2027 confidence bound. Missing evidence cannot be counted as PASS.
"""
import math


def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def research_priority_entry(row,holdout=None):
    """Issuer research triage from audited facts, not a trade recommendation."""
    base=row.get('base') or {}
    bear=row.get('bear') or {}
    close=row.get('reference_close')
    upside=base.get('price_upside_pct')
    if not row.get('rankable') or not _finite(upside) or not _finite(close) or close<=0:
        return None
    source_original=bool(row.get('original_current_issuer_numeric_checked'))
    capital=row.get('equity_offering_overlay') or {}
    pending_offering=bool(capital)
    share=row.get('share_bridge') or {}
    cb_unresolved=bool(share.get('missing_legal_conversion_inputs') or share.get('unresolved_terms'))
    special=bool(row.get('specialist_model_requirements'))
    cash=row.get('liquidity') or {}
    ocf=cash.get('ocf_k')
    warning=[]
    if not source_original:warning.append('HISTORICAL_OR_ORIGINAL_ISSUER_DETAILS_UNVERIFIED')
    if pending_offering:warning.append('ANNOUNCED_EQUITY_OFFERING_REQUIRES_SHARE_RECONCILIATION')
    if cb_unresolved:warning.append('CB_TERMS_OR_DENOMINATOR_NOT_SIGNED_OFF')
    if _finite(ocf) and ocf<0:warning.append('NEGATIVE_OCF_REQUIRES_WORKING_CAPITAL_BRIDGE_NOT_AUTOMATIC_FAIL')
    if ocf is None:warning.append('OCF_SOURCE_INCOMPLETE')
    if special:warning.append('SPECIALIST_BUSINESS_FORECAST_REQUIRED')
    if row.get('margin_recovery',{}).get('applied'):warning.append('MARGIN_RECOVERY_NOT_ISSUER_CERTIFIED')
    if not (row.get('pe_bridge') or {}).get('exact_matched_peer_review_complete'):
        warning.append('PEER_PE_NOT_CERTIFIED')
    if not row.get('company_forecast_confirmed'):
        warning.append('2027_COMPANY_OPERATING_BRIDGE_UNVERIFIED')
    nonop=(row.get('nonoperating_bridge') or {})
    reported_ytd_nonop_share_pct=nonop.get('reported_ytd_abs_gap_share_pretax_pct')
    material_ytd_nonop=(_finite(reported_ytd_nonop_share_pct) and
        reported_ytd_nonop_share_pct>=20 and
        nonop.get('component_assumptions_certified') is not True)
    if material_ytd_nonop:
        warning.append('REPORTED_YTD_NONOPERATING_GAP_GE20PCT_PRETAX_COMPONENTS_UNCERTIFIED')
    eps_reference=(row.get('eps_bridge_reference') or {})
    eps_above_annualized_pct=eps_reference.get('target_eps_vs_ytd_linear_annualized_pct')
    requires_eps_bridge=(_finite(eps_above_annualized_pct) and
        eps_above_annualized_pct>=30 and
        eps_reference.get('original_operating_bridge_certified') is not True)
    if requires_eps_bridge:
        warning.append('2027_EPS_GE30PCT_ABOVE_UNSEASONALIZED_CURRENT_YTD_RUN_RATE')
    if row.get('recommendation_blocked'):
        warning.append('MATERIAL_GOVERNANCE_BLOCK')
    current=base.get('target_price')
    stress=(100*(current*.64/close-1)) if _finite(current) else None
    bearprice=bear.get('target_price')
    bear_return=100*(bearprice/close-1) if _finite(bearprice) else None
    # This is the same target horizon's algebraic sensitivity, not a stochastic VaR.
    conservative_positive=_finite(stress) and stress>=0
    trend=(row.get('revenue_bridge') or {}).get('trend_inputs') or {}
    latest_yoy=trend.get('latest_month_yoy')
    ytd_yoy=trend.get('monthly_ytd_yoy')
    latest_month_yoy_pct=100*latest_yoy if _finite(latest_yoy) else None
    ytd_revenue_yoy_pct=100*ytd_yoy if _finite(ytd_yoy) else None
    # A single month is a dated monitoring signal, never a confirmed operating
    # turn, forecast revision, formal gate failure, or automatic sell order.
    latest_month_reversal_warning=(latest_month_yoy_pct is not None
        and ytd_revenue_yoy_pct is not None
        and latest_month_yoy_pct<=-10 and ytd_revenue_yoy_pct>0)
    if latest_month_reversal_warning:
        warning.append('LATEST_MONTH_REVENUE_FELL_AT_LEAST_10PCT_YOY_WHILE_YTD_POSITIVE')
    forecast_growth=(row.get('revenue_bridge') or {}).get('assumed_annual_growth')
    if _finite(forecast_growth) and forecast_growth>=.2:
        warning.append('HIGH_ASSUMED_GROWTH_UNVERIFIED_2027_EXTRAPOLATION')
    # Two separate sources of caution: source quality and unissued capital.
    # Deliberately do not blend these into an uncalibrated score/probability.
    lane='ORIGINAL_CURRENT_RECONCILED' if source_original else 'OFFICIAL_SUMMARY_UNVERIFIED_ORIGINALS'
    gate_status=(row.get('certification') or {})
    entry=dict(code=row['code'],market=row['market'],name=row.get('name'),
        source_lane=lane,reference_close=close,base_upside_pct=upside,
        base_eps=base.get('eps'),base_target_price=base.get('target_price'),
        eps_pe_each_minus20_upside_pct=stress,bear_upside_pct=bear_return,
        original_current_numeric_reconciled=source_original,
        all_eight_quarters_and_notes_verified='original_eight_quarter_statements' in gate_status.get('gates_passed',[]),
        pending_offering=pending_offering,
        cb_terms_or_shares_unresolved=cb_unresolved,
        pending_gates=list(gate_status.get('gates_pending') or []),
        formal_Aplus=bool(row.get('formal_Aplus')),
        recommendation_blocked=bool(row.get('recommendation_blocked')),
        warning_flags=warning,
        forward_growth_assumption_pct=100*forecast_growth if _finite(forecast_growth) else None,
        latest_month_revenue_yoy_pct=latest_month_yoy_pct,
        ytd_revenue_yoy_pct=ytd_revenue_yoy_pct,
        latest_month_reversal_warning=latest_month_reversal_warning,
        one_month_reversal_is_certified_trend=False,
        reversal_warning_changes_base_eps_or_pe=False,
        reported_ytd_abs_nonoperating_gap_share_pretax_pct=reported_ytd_nonop_share_pct if _finite(reported_ytd_nonop_share_pct) else None,
        reported_ytd_material_nonoperating_gap=material_ytd_nonop,
        reported_ytd_nonoperating_figure_not_recurring_earnings_claim=True,
        ytd_parent_eps_linear_annualized_reference=eps_reference.get('linear_annualized_ytd_parent_eps_at_model_denominator'),
        target_eps_vs_unseasonalized_ytd_run_rate_pct=eps_above_annualized_pct if _finite(eps_above_annualized_pct) else None,
        requires_2027_eps_stepup_bridge=requires_eps_bridge,
        ytd_annualized_reference_not_profit_forecast=True,
        earnings_quality_flags_do_not_change_base_or_priority=True,
        research_decision='REVIEW_ONLY_NOT_BUY'
    )
    # Explicit, auditable lexicographic research-order policy:
    # originals before bulk, no open equity events before open,
    # positive 20/20 sensitivity before negative, then actual sensitivity
    # magnitude; no arbitrary weighted percentage masquerading as alpha.
    entry['_priority_key']=(
        0 if source_original else 1,
        1 if pending_offering else 0,
        1 if cb_unresolved else 0,
        0 if conservative_positive else 1,
        -(stress if _finite(stress) else -1e12),
        -(upside),
        str(row['code']))
    return entry


def build_research_priority(rows,holdout=None,*,minimum_upside_pct=25.):
    """Return sidecar research queues. Formal rating and Top10 stay unchanged."""
    if not _finite(minimum_upside_pct):
        raise ValueError('INVALID_PRIORITY_MIN_UPSIDE')
    eligible=[]; blocked=[]
    for row in rows:
        entry=research_priority_entry(row,holdout)
        if entry is None or entry['base_upside_pct']<minimum_upside_pct:
            continue
        if entry['recommendation_blocked']:
            blocked.append(entry)
        else:
            eligible.append(entry)
    eligible.sort(key=lambda r:r['_priority_key'])
    def public(entry):
        return {k:v for k,v in entry.items() if k!='_priority_key'}
    ranked=[dict(review_rank=i+1,**public(r)) for i,r in enumerate(eligible)]
    original=[r for r in ranked if r['original_current_numeric_reconciled']]
    summary=(holdout or {}).get('holdout_error_tail') or {}
    return dict(schema='EVIDENCE_FIRST_RESEARCH_QUEUE_V1',
        purpose='INVESTIGATION_PRIORITY_ONLY_NOT_EXPECTED_RETURN_OR_WIN_RATE',
        min_base_upside_pct=minimum_upside_pct,
        source_policy='ORIGINAL_CURRENT_RECONCILED_BEFORE_OFFICIAL_BULK_NOT_EIGHT_QUARTER_AUDIT',
        priority_order=['original_current_numeric_reconciled','no_pending_equity_offering',
                        'no_unresolved_cb','nonnegative_20pct_eps_and_pe_stress',
                        'larger_20pct_eps_and_pe_stress','larger_base_price_upside'],
        accounting_error_reference=dict(
            period='2026-Q2',
            overall_p90_abs_revenue_error_pct=summary.get('p90_absolute_pct_error'),
            high_growth_subgroup_p90_abs_revenue_error_pct=(summary.get('groups') or {}).get(
                'HIGH_GROWTH_AT_LEAST_20PCT',{}).get('p90_absolute_pct_error'),
            used_to_modify_eps_or_pe=False,
            used_as_2027_stock_win_probability=False,
            subgroup_cohort_not_identical_to_2027_issuer_growth=True),
        price_staleness_not_repaired_by_queue=True,
        benchmark_beat_rate=None,
        realized_return_accuracy_calibrated=False,
        formal_Aplus_added=0,
        blocked_governance_count=len(blocked),
        eligible_count=len(ranked),
        original_current_issuer_candidates=len(original),
        top10_evidence_first=ranked[:10],
        top10_original_numeric_priority=original[:10],
        blocked_governance=[public(x) for x in blocked],
        original_current_audit_priority=original[:30],
        all_ranked=ranked)
