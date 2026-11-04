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
    # Pricing may be announced after the original share-count event. Keep its
    # separate discovery clock so today's issue price cannot leak into old PIT.
    issue_price=number(event.get('issuance_price_twd'))
    price_source_url=event.get('source_url')
    price_first_observed_at=None
    prior_update_clock=None
    for update in event.get('pricing_updates', []):
        update_clock=timestamp(update['first_observed_at'])
        public_date=timestamp(update['announced_on']+'T00:00:00+08:00')
        if prior_update_clock is not None and update_clock<=prior_update_clock:
            raise ValueError('OFFERING_PRICING_UPDATES_NOT_ORDERED')
        prior_update_clock=update_clock
        if update_clock<public_date:
            raise ValueError('OFFERING_PRICING_UPDATE_BEFORE_PUBLICATION')
        if update_clock>cut or public_date>cut:
            continue
        value=number(update.get('issuance_price_twd'))
        if value is None or value<=0 or not str(update.get('source_url','')).startswith('https://'):
            raise ValueError('OFFERING_PRICING_UPDATE_INVALID')
        issue_price=value
        price_source_url=update['source_url']
        price_first_observed_at=update['first_observed_at']
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
        expected_proceeds_twd=shares*issue_price if issue_price is not None else None,
        proceeds_basis='ANNOUNCED_GROSS_NOT_RECEIVED_NOT_NET_OF_COSTS' if issue_price is not None else None,
        issuance_price_twd=issue_price,
        pricing_source_url=price_source_url,
        pricing_first_observed_at=price_first_observed_at,
        is_new_stock_already_outstanding=False,
        rank_using_mechanical_sensitivity=False,
        price_upside_from_pre_ex_rights_close_not_comparable=True,
        proceeds_project_returns_and_ex_rights_adjustment_unmodelled=True,
        certified=False)
