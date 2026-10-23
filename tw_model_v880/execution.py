"""Next-session long-only execution with explicit costs and share actions."""
import math

from .evidence import timestamp
from .portfolio import finite

COST_FIELDS=("buy_fee_rate","sell_fee_rate","sell_tax_rate",
             "buy_slippage_rate","sell_slippage_rate","half_spread_rate")


def validate_cost_policy(costs):
    if not isinstance(costs,dict):
        raise ValueError('EXPLICIT_COST_POLICY_REQUIRED')
    for name in COST_FIELDS:
        value=costs.get(name)
        if not finite(value) or not 0<=value<1:
            raise ValueError('EXPLICIT_COST_MISSING_OR_INVALID_'+name)
    if costs['sell_fee_rate']+costs['sell_tax_rate']>=1:
        raise ValueError('INVALID_AGGREGATE_SELL_COST')
    if costs['sell_slippage_rate']+costs['half_spread_rate']>=1:
        raise ValueError('INVALID_AGGREGATE_EXIT_FRICTION')
    minimum_fee=costs.get('minimum_fee_ntd',0.)
    if not finite(minimum_fee) or minimum_fee<0:
        raise ValueError('INVALID_MINIMUM_BROKER_FEE')
    return costs


def net_trade(bars, actions, *, signal_at, exit_at, costs,
              corporate_actions_complete, requested_notional_ntd,
              max_participation, entry_execution='NEXT_SESSION_OPEN'):
    """No same-close fill, holiday guessing, price carry-forward, or missing as zero.

    Caller must supply an independently checked corporate-action coverage
    declaration even when there were no actions. Spread/slippage are explicit
    execution assumptions; actual fills remain a separate verification task.
    """
    if corporate_actions_complete is not True:
        raise ValueError("CORPORATE_ACTION_COVERAGE_UNKNOWN")
    if entry_execution not in ('NEXT_SESSION_OPEN','NEXT_SESSION_CLOSE'):
        raise ValueError('UNKNOWN_ENTRY_EXECUTION_RULE')
    signal,end=timestamp(signal_at),timestamp(exit_at)
    if end<=signal:
        raise ValueError("EXIT_NOT_AFTER_SIGNAL")
    validate_cost_policy(costs)
    minimum_fee=costs.get('minimum_fee_ntd',0.)
    if not finite(requested_notional_ntd,positive=True) or not finite(max_participation,positive=True) or max_participation>1:
        raise ValueError("INVALID_EXECUTION_SIZE_OR_PARTICIPATION")
    sessions=sorted(bars,key=lambda b:timestamp(b['open_at']))
    seen=set()
    for bar in sessions:
        opening,closing=timestamp(bar['open_at']),timestamp(bar['close_at'])
        if opening in seen or opening>=closing:
            raise ValueError("DUPLICATE_OR_INVALID_SESSION")
        seen.add(opening)
    eligible=[b for b in sessions if timestamp(b['open_at'])>signal and timestamp(b['close_at'])<=end]
    if not eligible:
        raise ValueError("AWAITING_FUTURE_EXECUTION_SESSION")
    # The first eligible session must not be silently skipped because an open
    # is absent, trading is suspended, or a limit queue was not executable.
    first,last=eligible[0],eligible[-1]
    for bar in (first,last):
        if not finite(bar.get('open'),positive=True) or not finite(bar.get('close'),positive=True):
            raise ValueError("EXECUTION_OPEN_OR_CLOSE_MISSING")
        if not finite(bar.get('turnover_ntd'),positive=True):
            raise ValueError("EXECUTION_TURNOVER_MISSING")
        if bar.get('fillability_verified') is not True:
            raise ValueError("SUSPENSION_LIMIT_QUEUE_OR_FILLABILITY_UNVERIFIED")
    entry_at=first['open_at'] if entry_execution=='NEXT_SESSION_OPEN' else first['close_at']
    entry_quote=first['open'] if entry_execution=='NEXT_SESSION_OPEN' else first['close']
    entry_price=entry_quote*(1+costs['buy_slippage_rate']+costs['half_spread_rate'])
    cash_paid=requested_notional_ntd+max(requested_notional_ntd*costs['buy_fee_rate'],minimum_fee)
    shares=requested_notional_ntd/entry_price
    dividend_cash=0.0
    seen_actions=set()
    for action in sorted(actions,key=lambda a:timestamp(a['effective_at'])):
        when=timestamp(action['effective_at'])
        if not timestamp(entry_at)<when<=timestamp(last['close_at']):
            continue
        identity=action.get('id')
        if not identity or identity in seen_actions:
            raise ValueError("DUPLICATE_OR_UNIDENTIFIED_CORPORATE_ACTION")
        seen_actions.add(identity)
        if action['type']=='split':
            if not finite(action.get('ratio'),positive=True):
                raise ValueError("INVALID_SPLIT_RATIO")
            shares*=action['ratio']
        elif action['type']=='cash_dividend':
            amount=action.get('per_share')
            if not finite(amount) or amount<0:
                raise ValueError("INVALID_DIVIDEND")
            dividend_cash+=shares*amount
        else:
            raise ValueError("RIGHTS_DELISTING_OR_OTHER_ACTION_REQUIRES_EXPLICIT_MODEL")
    exit_price=last['close']*(1-costs['sell_slippage_rate']-costs['half_spread_rate'])
    if exit_price<=0:
        raise ValueError("NONPOSITIVE_NET_EXIT_PRICE")
    entry_participation=requested_notional_ntd/first['turnover_ntd']
    exit_notional=shares*last['close']
    exit_participation=exit_notional/last['turnover_ntd']
    if max(entry_participation,exit_participation)>max_participation:
        raise ValueError("PARTICIPATION_CAPACITY_EXCEEDED")
    gross_proceeds=shares*exit_price
    proceeds=(gross_proceeds-max(gross_proceeds*costs['sell_fee_rate'],minimum_fee)
              -gross_proceeds*costs['sell_tax_rate']+dividend_cash)
    if proceeds<0:
        raise ValueError('EXIT_PROCEEDS_INSUFFICIENT_FOR_MINIMUM_FEES')
    return dict(entry_at=entry_at,exit_at=last['close_at'],
                net_total_return=proceeds/cash_paid-1,dividend_cash=dividend_cash,
                ending_shares=shares,entry_participation=entry_participation,
                exit_participation=exit_participation,costs=costs,
                execution_is_assumption_not_broker_fill=True,
                annualized_portfolio_return=None)
