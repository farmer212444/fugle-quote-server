"""Time-aware, unissued-equity sensitivity only; never silently changes Base."""
import json
from pathlib import Path

from .evidence import timestamp
from .math import number


def equity_offering_overlay(root, code, asof, target_date, base, issued_common_shares):
    """Calculate a gross, profit-constant issuance sensitivity.

    The event is *not* added to currently issued or fully diluted shares.
    Unconfirmed issue price, proceeds, ex-rights adjustment, investment returns
    and profit attribution prevent treating this as a certified target return.
    Evidence discovered today must not leak into historical PIT runs.
    """
    path = Path(root) / 'evidence/v880/equity_offerings' / (str(code) + '.json')
    if not path.is_file():
        return None
    event = json.loads(path.read_text(encoding='utf-8'))
    if event.get('code') != str(code):
        raise ValueError('OFFERING_ISSUER_IDENTITY_MISMATCH')
    cut = timestamp(asof)
    observed = timestamp(event['first_observed_at'])
    announced = timestamp(event['announced_at'])
    if announced > cut or observed > cut:
        return None
    if target_date < event['planned_subscription_record_date']:
        return None
    if event.get('status') != 'ANNOUNCED_NOT_YET_ISSUED':
        return dict(status='OFFERING_STATUS_RECONCILIATION_REQUIRED',
                    source_url=event.get('source_url'), certified=False)
    shares = event.get('planned_new_common_shares')
    if type(shares) is not int or shares <= 0:
        raise ValueError('OFFERING_NEW_SHARE_COUNT_INVALID')
    baseline = number(event.get('reference_existing_common_shares'))
    current = number(issued_common_shares)
    if baseline is None or current is None or baseline <= 0:
        raise ValueError('OFFERING_ISSUED_SHARE_BASELINE_MISSING')
    if abs(current - baseline) > 1:
        return dict(status='OFFERING_MASTER_SHARE_COUNT_CHANGED_RECONCILE_FIRST',
                    issued_shares_at_event=baseline, issued_shares_in_master=current,
                    planned_new_common_shares=shares,
                    source_url=event.get('source_url'), certified=False)
    denominator = number(base.get('shares'))
    profit_k = number(base.get('parent_profit_k'))
    pe = number(base.get('pe'))
    if denominator is None or denominator <= 0 or profit_k is None:
        return dict(status='OFFERING_BASE_INPUTS_UNAVAILABLE',
                    planned_new_common_shares=shares, certified=False)
    projected_eps = profit_k * 1000 / (denominator + shares)
    mechanical_target = projected_eps * pe if pe is not None and projected_eps > 0 else None
    return dict(
        status='ANNOUNCED_UNISSUED_DILUTION_SCENARIO_ONLY',
        planned_new_common_shares=shares,
        reference_existing_common_shares=baseline,
        model_current_denominator_shares=denominator,
        assumed_post_issue_denominator_shares=denominator + shares,
        issuance_eps_sensitivity=projected_eps,
        issuance_target_price_sensitivity=mechanical_target,
        source_url=event['source_url'],
        first_observed_at=event['first_observed_at'],
        announced_at=event['announced_at'],
        planned_subscription_record_date=event['planned_subscription_record_date'],
        expected_proceeds_twd=None,
        issuance_price_twd=event.get('issuance_price_twd'),
        is_new_stock_already_outstanding=False,
        rank_using_mechanical_sensitivity=False,
        price_upside_from_pre_ex_rights_close_not_comparable=True,
        proceeds_project_returns_and_ex_rights_adjustment_unmodelled=True,
        certified=False)
