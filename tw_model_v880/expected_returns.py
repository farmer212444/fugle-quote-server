"""Empirical terminal wealth with chronological, cohort-weighted diagnostics.

Point scenarios are not conditional means. Actual joint price/dividend residuals
retain losses and tails. Rates are fractions. This layer never grants A+.
"""
import datetime as dt
import random
import statistics
from collections import defaultdict
from pathlib import Path

from .contracts import canonical_hash
from .evidence import timestamp
from .execution import COST_FIELDS
from .portfolio import finite

STATES = ('bear', 'base', 'bull')
TAIPEI = dt.timezone(dt.timedelta(hours=8))
FOLDER = 'experiments/expected_returns_v1'
RETURN_DEFINITION = 'HYPOTHETICAL_REFERENCE_CLOSE_TO_TARGET_NET_TOTAL_RETURN'
POLICY = dict(schema='EMPIRICAL_TERMINAL_WEALTH_V1', minimum_train_rows=100,
              minimum_oos_rows=100, minimum_train_cohorts=12, minimum_oos_cohorts=12,
              minimum_issuers=20, minimum_market_regimes=2, embargo_days=5,
              maximum_reliability_gap=.10, bootstrap_draws=2000, automatic_deployment=False)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def validate_policy(p):
    require(set(p) == set(POLICY) and p['schema'] == POLICY['schema']
            and p['automatic_deployment'] is False, 'EXPECTED_RETURN_POLICY_UNSUPPORTED')
    for k, floor in POLICY.items():
        if type(floor) is int:
            require(type(p[k]) is int and p[k] >= floor, 'EXPECTED_RETURN_POLICY_BELOW_FLOOR_'+k)
    require(finite(p['maximum_reliability_gap']) and 0 < p['maximum_reliability_gap'] <= .10,
            'EXPECTED_RETURN_RELIABILITY_POLICY_INVALID')


def horizon(f):
    days = (dt.date.fromisoformat(f['target_date'])-dt.date.fromisoformat(f['price_date'])).days
    require(days > 0, 'EXPECTED_RETURN_NONPOSITIVE_HORIZON')
    return days


def scope(f):
    method = (f.get('forecast_binding') or {}).get('forecast_method_sha256', '')
    require(isinstance(method, str) and len(method) == 64 and all(c in '0123456789abcdef' for c in method),
            'EXPECTED_RETURN_METHOD_MISSING')
    require(isinstance(f.get('industry'), str) and f['industry'].strip(), 'EXPECTED_RETURN_INDUSTRY_MISSING')
    return method, f['industry'], horizon(f)


def target_close(f):
    return dt.datetime.combine(dt.date.fromisoformat(f['target_date']),dt.time(13,30),tzinfo=TAIPEI)


def validate_forecast_at(f, asof):
    """Keep issuance and estimation prospective at the caller's actual clock."""
    instant = timestamp(asof)
    require(timestamp(f['estimate_vintage']) <= instant,'EXPECTED_RETURN_FORECAST_FROM_FUTURE')
    require(instant < target_close(f),'EXPECTED_RETURN_TARGET_ALREADY_CLOSED')


def prices(f):
    p = [f.get(s, {}).get('target_price') for s in STATES]
    require(all(finite(v, positive=True) for v in p) and p[0] < p[1] < p[2],
            'EXPECTED_RETURN_SCENARIOS_INVALID')
    require(finite(f.get('reference_close'), positive=True), 'EXPECTED_RETURN_REFERENCE_INVALID')
    require(dt.date.fromisoformat(f['price_date']) <= timestamp(f['estimate_vintage']).astimezone(TAIPEI).date(),
            'EXPECTED_RETURN_REFERENCE_AFTER_FORECAST')
    require(timestamp(f['estimate_vintage']) < target_close(f),'EXPECTED_RETURN_FORECAST_NOT_PROSPECTIVE')
    scope(f)
    return p


def validate_costs(c):
    require(isinstance(c, dict) and all(finite(c.get(k)) and 0 <= c[k] < 1 for k in COST_FIELDS)
            and finite(c.get('minimum_fee_ntd')) and c['minimum_fee_ntd'] >= 0
            and c['sell_fee_rate']+c['sell_tax_rate'] < 1
            and c['sell_slippage_rate']+c['half_spread_rate'] < 1, 'EXPECTED_RETURN_COSTS_INVALID')


def net_return(reference, terminal, dividends, costs, notional):
    validate_costs(costs)
    require(all(finite(v, positive=True) for v in (reference, notional))
            and all(finite(v) and v >= 0 for v in (terminal, dividends)), 'EXPECTED_RETURN_WEALTH_INVALID')
    shares = notional/(reference*(1+costs['buy_slippage_rate']+costs['half_spread_rate']))
    paid = notional+max(notional*costs['buy_fee_rate'], costs['minimum_fee_ntd'])
    sale = shares*terminal*(1-costs['sell_slippage_rate']-costs['half_spread_rate'])
    fee = max(sale*costs['sell_fee_rate'], costs['minimum_fee_ntd']) if sale else 0.
    proceeds = sale*(1-costs['sell_tax_rate'])-fee+shares*dividends
    require(proceeds >= 0, 'EXPECTED_RETURN_PROCEEDS_BELOW_ZERO')
    return proceeds/paid-1


def state(wealth, p):
    return 'bear' if wealth < (p[0]+p[1])/2 else 'base' if wealth < (p[1]+p[2])/2 else 'bull'


def frozen_cohorts(root):
    from .superforecast import read_record
    root = Path(root)
    for path in sorted((root/FOLDER/'cohorts').glob('*.json')):
        c = read_record(path)
        require(c.get('cohort_id') == path.stem, 'EXPECTED_RETURN_COHORT_FILE_IDENTITY')
        identity = c.get('registration_id', '')
        require(isinstance(identity, str) and len(identity) == 64 and all(x in '0123456789abcdef' for x in identity),
                'EXPECTED_RETURN_INVALID_REGISTRATION_ID')
        reg = read_record(root/FOLDER/'registrations'/(identity+'.json'))
        require(canonical_hash(reg['spec']) == identity and reg['record_sha256'] == c['registration_sha256']
                and timestamp(reg['registered_at']) <= timestamp(c['issued_at']), 'EXPECTED_RETURN_REGISTRATION_MISMATCH')
        seen = set()
        for f in c['forecasts']:
            prices(f)
            key = (f['market'], f['code'])
            require(key not in seen and f['target_date'] == c['target_date']
                    and timestamp(f['estimate_vintage']) <= timestamp(c['issued_at']), 'EXPECTED_RETURN_FROZEN_FORECAST_MISMATCH')
            seen.add(key)
        yield c


def validate_observations(records, asof):
    """Caller must additionally reparse original bytes and verify complete cohorts."""
    seen = set()
    for r in records:
        f = r['forecast']; prices(f)
        key = (r['cohort_id'], f['market'], f['code'])
        require(key not in seen, 'EXPECTED_RETURN_DUPLICATE_OBSERVATION'); seen.add(key)
        issued, ended, checked = (timestamp(r[k]) for k in ('issued_at','exit_at','first_verified_at'))
        require(timestamp(f['estimate_vintage']) <= issued < ended <= checked <= timestamp(asof),
                'EXPECTED_RETURN_OUTCOME_CLOCK_INVALID')
        due = dt.date.fromisoformat(f['target_date'])
        require(ended.astimezone(TAIPEI).date() <= due <= checked.astimezone(TAIPEI).date(),
                'EXPECTED_RETURN_OUTCOME_NOT_MATURE')
        require(r.get('sources_verified') is True and r.get('cohort_complete') is True
                and r.get('return_definition') == RETURN_DEFINITION, 'EXPECTED_RETURN_UNVERIFIED_OR_PARTIAL_COHORT')
        require(all(finite(r.get(k)) and r[k] >= 0 for k in
                    ('terminal_value_per_initial_share','dividends_per_initial_share')), 'EXPECTED_RETURN_COMPONENT_MISSING_NOT_ZERO')
        require(r.get('market_regime') in ('UP','DOWN','FLAT'), 'EXPECTED_RETURN_REGIME_MISSING')


def independent_cohorts(records):
    groups = defaultdict(list)
    for r in records:
        groups[r['cohort_id']].append(r)
    selected, previous = [], None
    for g in sorted(groups.values(), key=lambda x: (timestamp(x[0]['issued_at']), x[0]['cohort_id'])):
        require(len({r['issued_at'] for r in g}) == 1 and len({r['exit_at'] for r in g}) == 1,
                'EXPECTED_RETURN_COHORT_CLOCK_CONFLICT')
        start = min(timestamp(r['forecast']['price_date']+'T13:30:00+08:00') for r in g)
        if previous is not None and start <= previous:
            continue
        selected.append(g); previous = timestamp(g[0]['exit_at'])
    return selected


def distribution(forecast, cohorts, costs, notional):
    p = prices(forecast)
    require(bool(cohorts), 'EXPECTED_RETURN_TRAINING_EMPTY')
    projected = []
    for group in cohorts:
        weight = 1/len(cohorts)/len(group)
        for r in group:
            base = r['forecast']['base']['target_price']
            terminal = p[1]*r['terminal_value_per_initial_share']/base
            cash = p[1]*r['dividends_per_initial_share']/base
            value = net_return(forecast['reference_close'],terminal,cash,costs,notional)
            projected.append((weight,state(terminal+cash,p),value,terminal,cash))
    probabilities = {s:sum(w for w,k,*_ in projected if k == s) for s in STATES}
    conditional = {}
    for s in STATES:
        subset = [x for x in projected if x[1] == s]; mass = probabilities[s]
        conditional[s] = ({'net_return':sum(x[0]*x[2] for x in subset)/mass,
                           'terminal_price_equivalent':sum(x[0]*x[3] for x in subset)/mass,
                           'dividends':sum(x[0]*x[4] for x in subset)/mass} if mass else None)
    expected = sum(x[0]*x[2] for x in projected)
    return dict(scenario_probabilities=probabilities,conditional_scenario_means=conditional,
                expected_net_total_return=expected,expected_future_dividends=sum(x[0]*x[4] for x in projected),
                annualized_expected_terminal_wealth=(1+expected)**(365.25/horizon(forecast))-1,
                annualized_expected_terminal_wealth_is_not_expected_annualized_return=True,
                future_dividends_are_empirical_estimates_not_declared_cash=True)


def walk_forward(records, costs, notional, policy=POLICY):
    validate_policy(policy)
    cohorts = independent_cohorts(records); tests = []
    for group in cohorts:
        cut = timestamp(group[0]['issued_at'])-dt.timedelta(days=policy['embargo_days'])
        train = [g for g in cohorts if all(timestamp(r['exit_at']) < cut and timestamp(r['first_verified_at']) < cut for r in g)]
        issuers = {(r['forecast']['market'],r['forecast']['code']) for g in train for r in g}
        if (len(train) < policy['minimum_train_cohorts'] or sum(map(len,train)) < policy['minimum_train_rows']
                or len(issuers) < policy['minimum_issuers']):
            continue
        results = []
        for r in group:
            f = r['forecast']; pred = distribution(f,train,costs,notional)
            actual_state = state(r['terminal_value_per_initial_share']+r['dividends_per_initial_share'],prices(f))
            actual = net_return(f['reference_close'],r['terminal_value_per_initial_share'],r['dividends_per_initial_share'],costs,notional)
            baseline = net_return(f['reference_close'],f['base']['target_price'],0.,costs,notional)
            probabilities = pred['scenario_probabilities']
            results.append(dict(market=f['market'],code=f['code'],probabilities=probabilities,actual_state=actual_state,
                brier=sum((probabilities[s]-int(actual_state == s))**2 for s in STATES),
                uniform_brier=sum((1/3-int(actual_state == s))**2 for s in STATES),
                absolute_error=abs(pred['expected_net_total_return']-actual),base_error=abs(baseline-actual),
                market_regime=r['market_regime']))
        tests.append(results)
    count = sum(map(len,tests))
    oos_issuers = {(r['market'],r['code']) for g in tests for r in g}
    result = dict(status='AWAITING_MATCHED_MATURE_OOS_COHORTS',diagnostics_passed=False,
                  oos_cohorts=len(tests),oos_rows=count,oos_issuers=len(oos_issuers),
                  minimum_oos_issuers=policy['minimum_issuers'],multiclass_brier=None,reliability_bins=[])
    if len(tests) < policy['minimum_oos_cohorts'] or count < policy['minimum_oos_rows']:
        return result
    if len(oos_issuers) < policy['minimum_issuers']:
        result['status'] = 'AWAITING_MATCHED_MATURE_OOS_ISSUERS'
        return result
    def avg(key):
        return statistics.fmean(statistics.fmean(r[key] for r in g) for g in tests)
    gap, bins = 0., []
    for s in STATES:
        for i in range(5):
            bucket = [(r,1/len(tests)/len(g)) for g in tests for r in g if min(4,int(r['probabilities'][s]*5)) == i]
            if not bucket:
                continue
            mass = sum(w for _,w in bucket)
            p = sum(r['probabilities'][s]*w for r,w in bucket)/mass
            y = sum(int(r['actual_state'] == s)*w for r,w in bucket)/mass
            gap = max(gap,abs(p-y));bins.append(dict(state=s,lower=i/5,rows=len(bucket),mean_forecast=p,observed_frequency=y))
    regimes = {r['market_regime'] for g in tests for r in g}
    passed = (gap <= policy['maximum_reliability_gap'] and avg('brier') <= avg('uniform_brier')
              and avg('absolute_error') <= avg('base_error') and len(regimes) >= policy['minimum_market_regimes'])
    result.update(status='OOS_DIAGNOSTICS_WITHIN_RESEARCH_POLICY' if passed else 'OOS_DIAGNOSTICS_FAILED',
                  diagnostics_passed=passed,multiclass_brier=avg('brier'),uniform_baseline_brier=avg('uniform_brier'),
                  expected_return_mae=avg('absolute_error'),price_only_base_mae=avg('base_error'),
                  maximum_reliability_gap=gap,reliability_bins=bins,market_regimes=len(regimes),
                  brier_alone_is_not_calibration_or_alpha_proof=True)
    return result


def estimate(forecast, records, *, asof, costs, notional, policy=POLICY):
    validate_policy(policy); validate_costs(costs); prices(forecast); validate_forecast_at(forecast,asof)
    validate_observations(records,asof)
    cut = min(timestamp(asof),timestamp(forecast['estimate_vintage']))-dt.timedelta(days=policy['embargo_days'])
    matched = [r for r in records if scope(r['forecast']) == scope(forecast)
               and timestamp(r['first_verified_at']) < cut and timestamp(r['exit_at']) < cut]
    cohorts = independent_cohorts(matched)
    diagnostic = walk_forward(matched,costs,notional,policy)
    result = dict(schema=POLICY['schema'],return_definition=RETURN_DEFINITION,status=diagnostic['status'],
        holding_calendar_days=horizon(forecast),matched_rows=len(matched),independent_training_cohorts=len(cohorts),
        diagnostics=diagnostic,scenario_probabilities=None,expected_net_total_return=None,
        annualized_expected_terminal_wealth=None,formal_Aplus_added=0,investment_outperformance_proven=False,
        automatic_deployment=False,cost_policy_sha256=canonical_hash(costs),research_policy_sha256=canonical_hash(policy))
    if not diagnostic['diagnostics_passed']:
        return result
    result.update(distribution(forecast,cohorts,costs,notional))
    rng = random.Random(8108)
    means = sorted(distribution(forecast,[rng.choice(cohorts) for _ in cohorts],costs,notional)['expected_net_total_return']
                   for _ in range(policy['bootstrap_draws']))
    result.update(status='EMPIRICAL_EXPECTATION_AFTER_OOS_CHECKS_RESEARCH_ONLY',
                  expected_return_mean_bootstrap_interval_95=[means[int(len(means)*.025)],means[int(len(means)*.975)]],
                  interval_is_not_a_future_return_prediction_interval=True)
    return result
