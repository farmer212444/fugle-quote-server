"""Purged chronological folds and paired, trial-aware model comparisons."""
import datetime as dt
import math
import random
import re
import statistics

from .evidence import timestamp


def purged_walk_forward(samples, test_windows, embargo_days=0):
    if not isinstance(embargo_days,int) or isinstance(embargo_days,bool) or embargo_days < 0:
        raise ValueError("INVALID_EMBARGO")
    if len({s['id'] for s in samples}) != len(samples):
        raise ValueError("DUPLICATE_VALIDATION_SAMPLE")
    for sample in samples:
        if timestamp(sample['label_end']) < timestamp(sample['signal_at']):
            raise ValueError("LABEL_BEFORE_SIGNAL")
    folds = []
    previous_end = None
    for start, end in test_windows:
        start, end = timestamp(start), timestamp(end)
        if start >= end or (previous_end is not None and start < previous_end):
            raise ValueError("NONCHRONOLOGICAL_TEST_WINDOWS")
        train_end = start-dt.timedelta(days=embargo_days)
        train = [s['id'] for s in samples if timestamp(s['signal_at']) < train_end
                 and timestamp(s['label_end']) < train_end]
        test = [s['id'] for s in samples if start <= timestamp(s['signal_at']) < end]
        folds.append(dict(train=train, test=test, test_start=start.isoformat(), test_end=end.isoformat()))
        previous_end = end
    return folds


def compare_models(pairs, *, trials, block_size=5, min_dates=60, draws=2000, seed=810):
    """Each pair is one independent signal-date cohort's net total return.

    Block bootstrap preserves local serial dependence. Trial correction is
    Bonferroni across the declared experiments; it is not a claimed PBO metric.
    Parameters must be declared before observing the evaluation period.
    """
    if any(not isinstance(x,int) or isinstance(x,bool) or x<=0 for x in (trials,block_size,min_dates,draws)):
        raise ValueError("INVALID_EXPERIMENT_POLICY")
    if trials > draws*.025:
        return dict(status="INSUFFICIENT_BOOTSTRAP_DRAWS_FOR_TRIAL_CORRECTION", promotion_eligible=False)
    dates = [p['signal_date'] for p in pairs]
    if len(set(dates)) != len(dates) or dates != sorted(dates):
        raise ValueError("DUPLICATE_OR_UNORDERED_COHORT_DATES")
    previous_end=None
    for pair in pairs:
        dt.date.fromisoformat(pair['signal_date'])
        signal=timestamp(pair['signal_at']);end=timestamp(pair['outcome_end_champion'])
        if signal.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()!=pair['signal_date']:
            raise ValueError('SIGNAL_COHORT_DATE_MISMATCH')
        if end<=signal or (previous_end is not None and signal<previous_end):
            raise ValueError('OVERLAPPING_OUTCOME_PERIODS_ARE_NOT_INDEPENDENT_PORTFOLIO_RETURNS')
        if timestamp(pair['champion_frozen_at'])>signal or timestamp(pair['challenger_frozen_at'])>signal:
            raise ValueError('MODEL_CREATED_AFTER_SIGNAL')
        previous_end=end
        for key in ('champion_net_return','challenger_net_return'):
            if not isinstance(pair.get(key),(int,float)) or isinstance(pair[key],bool) or not math.isfinite(pair[key]) or pair[key] < -1:
                raise ValueError("INVALID_NET_TOTAL_RETURN")
        if (not pair.get('execution_and_actions_verified') or
                pair.get('cost_policy_sha256_champion') != pair.get('cost_policy_sha256_challenger') or
                not re.fullmatch('[a-f0-9]{64}',pair.get('cost_policy_sha256_champion','')) or
                pair.get('outcome_end_champion') != pair.get('outcome_end_challenger') or
                not pair.get('outcome_end_champion')):
            raise ValueError("UNPAIRED_OR_UNVERIFIED_MODEL_OUTCOMES")
    if len(pairs)<min_dates:
        return dict(status="AWAITING_INDEPENDENT_OOS_DATES", independent_dates=len(pairs),
                    required_dates=min_dates, promotion_eligible=False)
    differences = [p['challenger_net_return']-p['champion_net_return'] for p in pairs]
    rng = random.Random(seed)
    blocks = [differences[i:i+block_size] for i in range(0,len(differences),block_size)]
    means = []
    for _ in range(draws):
        sample = []
        while len(sample)<len(differences):
            sample.extend(rng.choice(blocks))
        means.append(statistics.fmean(sample[:len(differences)]))
    means.sort()
    lower = means[max(0,int(draws*.025/trials)-1)]
    regimes = {p.get('market_regime') for p in pairs if p.get('market_regime')}
    enough_regimes = len(regimes)>=2
    # Return improvement alone is not sufficient when the challenger has
    # materially greater observed peak-to-trough loss on the same periods.
    def drawdown(key):
        wealth=peak=1.0;worst=0.0
        for pair in pairs:
            wealth*=1+pair[key];peak=max(peak,wealth)
            worst=max(worst,1-wealth/peak)
        return worst
    champion_dd=drawdown('champion_net_return');challenger_dd=drawdown('challenger_net_return')
    eligible=lower>0 and enough_regimes and challenger_dd<=champion_dd+1e-12
    return dict(status="PAIRED_OOS_COMPARISON", independent_dates=len(pairs),
                mean_net_return_improvement=statistics.fmean(differences),
                trial_adjusted_lower_bound=lower, declared_trials=trials,
                correction="BONFERRONI_BLOCK_BOOTSTRAP_NOT_PBO", block_size=block_size,
                regime_count=len(regimes), champion_max_drawdown=champion_dd,
                challenger_max_drawdown=challenger_dd, promotion_eligible=eligible,
                automatic_deployment=False)


def calibration_summary(records, min_samples=100):
    """Score genuinely pre-issued probabilities; no subjective weights inferred."""
    if not isinstance(min_samples,int) or isinstance(min_samples,bool) or min_samples<=0:
        raise ValueError("INVALID_CALIBRATION_MINIMUM")
    if len({r['sample_id'] for r in records}) != len(records):
        raise ValueError("DUPLICATE_CALIBRATION_OUTCOME")
    for row in records:
        p,y=row.get('predicted_probability'),row.get('outcome')
        if not isinstance(p,(int,float)) or isinstance(p,bool) or not math.isfinite(p) or not 0<=p<=1 or type(y) is not bool:
            raise ValueError("INVALID_CALIBRATION_OBSERVATION")
        if timestamp(row['probability_issued_at'])>=timestamp(row['outcome_at']):
            raise ValueError("POST_OUTCOME_PROBABILITY_FORBIDDEN")
    if len(records)<min_samples:
        return dict(status="UNCALIBRATED_INSUFFICIENT_OUTCOMES", count=len(records),
                    calibrated_probability=None, brier_score=None)
    bins=[]
    for i in range(5):
        lo=i/5
        group=[r for r in records if min(4,int(r['predicted_probability']*5))==i]
        if group:
            bins.append(dict(lower=lo,count=len(group),mean_forecast=statistics.fmean(r['predicted_probability'] for r in group),
                             observed_frequency=statistics.fmean(r['outcome'] for r in group)))
    return dict(status="OOS_PROBABILITY_DIAGNOSTICS_NOT_AUTOMATIC_CALIBRATION",count=len(records),
                calibrated_probability=None,
                brier_score=statistics.fmean((r['predicted_probability']-int(r['outcome']))**2 for r in records),
                reliability_bins=bins)
