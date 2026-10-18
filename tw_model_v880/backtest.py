"""PIT admission and execution accounting; no invented live performance."""
import math,re
from .evidence import timestamp

def admission(snapshot,signal_at):
    cut=timestamp(signal_at);reasons=[]
    if not snapshot.get('universe_membership_verified'):reasons.append('CONTEMPORANEOUS_UNIVERSE_UNVERIFIED')
    for field in ('model_created_at','estimate_created_at'):
        try:
            if timestamp(snapshot[field])>cut:reasons.append('FUTURE_'+field.upper())
        except (KeyError,ValueError,TypeError):reasons.append('MISSING_'+field.upper())
    if not snapshot.get('inputs'):reasons.append('INPUT_PUBLICATION_HISTORY_MISSING')
    for source in snapshot.get('inputs',[]):
        try:
            if not re.fullmatch('[0-9a-f]{64}',source.get('sha256','')):reasons.append('INPUT_HASH_MISSING')
            if timestamp(source['published_at'])>cut:reasons.append('UNPUBLISHED_INPUT')
            if timestamp(source['revision_at'])>cut:reasons.append('RESTATED_DATA_FROM_FUTURE')
        except (KeyError,ValueError,TypeError):reasons.append('INPUT_TIME_MISSING')
    policy=snapshot.get('cost_policy') or {}
    if any(not isinstance(policy.get(k),(int,float)) or not math.isfinite(policy[k]) or not 0<=policy[k]<1 for k in ('buy_fee_rate','sell_fee_rate','sell_tax_rate')):reasons.append('EXPLICIT_COST_POLICY_MISSING')
    return dict(admitted=not reasons,reasons=sorted(set(reasons)))

def event_return(snapshot,bars,signal_at,exit_at,actions):
    check=admission(snapshot,signal_at)
    if not check['admitted']:raise ValueError(str(check['reasons']))
    signal=timestamp(signal_at);end=timestamp(exit_at)
    eligible=sorted([b for b in bars if timestamp(b['open_at'])>signal and timestamp(b['close_at'])<=end],key=lambda b:timestamp(b['open_at']))
    if not eligible:raise ValueError('NO_EXECUTABLE_SESSION')
    first,last=eligible[0],eligible[-1];shares=1.;cash=0.
    for a in sorted(actions,key=lambda a:timestamp(a['effective_at'])):
        if not timestamp(first['open_at'])<timestamp(a['effective_at'])<=timestamp(last['close_at']):continue
        if a['type']=='split':shares*=a['ratio']
        elif a['type']=='cash_dividend':cash+=shares*a['per_share']
        else:raise ValueError('UNHANDLED_CORPORATE_ACTION')
    c=snapshot['cost_policy'];paid=first['open']*(1+c['buy_fee_rate']);received=shares*last['close']*(1-c['sell_fee_rate']-c['sell_tax_rate'])+cash
    return dict(entry_at=first['open_at'],exit_at=last['close_at'],ending_shares=shares,dividend_cash=cash,total_return_pct=(received/paid-1)*100,
      event_return_only_not_portfolio_CAGR=True)

def live_backtest_status(evidence):
    return dict(status='BLOCKED_MISSING_PIT_HISTORY',performance=None,estimated_hit_rate=None,
      missing=['Issuer disclosure and revision timestamps','Contemporaneous listing and delisting universe','Historical frozen forecast vintages','Execution prices and explicit fees/tax/slippage policy'],
      accounting_holdout_is_stock_return_backtest=False)
