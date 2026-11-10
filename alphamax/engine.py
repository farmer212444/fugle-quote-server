"""AlphaMax 1.0: dependency-free, independent cohort research MVP."""
from __future__ import annotations
import argparse
import calendar
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path

VERSION = '1.0.0'


def day(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('date must use YYYY-MM-DD')
    return parsed


def anniversary(value):
    d = day(value)
    return d.replace(year=d.year + 1, day=min(d.day, calendar.monthrange(d.year + 1, d.month)[1]))


def finite(value, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('expected finite number')
    if minimum is not None and value < minimum:
        raise ValueError('number below minimum')


@dataclass(frozen=True)
class Costs:
    commission: float = .001425
    sell_tax: float = .003
    slippage: float = .001
    minimum_commission_twd: float = 20
    allocation_twd: float = 100000
    lot_size: int = 1000

    def __post_init__(self):
        for key, value in asdict(self).items():
            finite(value, 0)
        if self.allocation_twd <= 0 or self.lot_size < 1 or int(self.lot_size) != self.lot_size:
            raise ValueError('invalid allocation or lot size')
        if max(self.commission, self.sell_tax, self.slippage) >= 1:
            raise ValueError('invalid rate')


def validate(data):
    """Require bitemporal evidence and a historical universe, never infer missing outcomes."""
    if data['kind'] not in ('synthetic', 'historical'):
        raise ValueError('invalid data kind')
    if not data['source'] or not data['unverified']:
        raise ValueError('source and explicit unverified items required')
    ids = set()
    for cohort in data['cohorts']:
        decision = day(cohort['decision'])
        if decision in ids:
            raise ValueError('duplicate decision')
        ids.add(decision)
        if day(cohort['universe_available']) > decision or not cohort['universe_source']:
            raise ValueError('universe unavailable at decision')
        if not cohort['includes_delisted']:
            raise ValueError('survivor-only universe forbidden')
        symbols = set()
        if not cohort['rows']:
            raise ValueError('empty universe')
        for r in cohort['rows']:
            if r['symbol'] in symbols:
                raise ValueError('duplicate security')
            symbols.add(r['symbol'])
            if not r['feature_source'] or not r['outcome_source']:
                raise ValueError('missing provenance')
            if not (day(r['feature_period_end']) <= day(r['feature_available']) <= decision):
                raise ValueError('future feature/revision')
            if not (decision < day(r['entry_date']) < day(r['exit_date'])):
                raise ValueError('execution chronology')
            if day(r['exit_date']) < anniversary(r['entry_date']):
                raise ValueError('label shorter than 12 calendar months')
            if day(r['label_available']) < day(r['exit_date']):
                raise ValueError('label available before outcome')
            if r['entry_status'] not in ('filled', 'suspended', 'limit_up', 'no_volume'):
                raise ValueError('unknown entry status')
            if r['exit_status'] not in ('filled', 'delisted', 'blocked'):
                raise ValueError('unknown exit status')
            for key in ('momentum', 'entry_price', 'exit_price', 'dividend_per_share'):
                finite(r[key], 0 if key != 'momentum' else None)
            if r['entry_price'] <= 0:
                raise ValueError('invalid entry price')
            if not isinstance(r['settlement_verified'], bool):
                raise ValueError('invalid settlement flag')
            if r['exit_status'] == 'delisted' and not r['settlement_verified']:
                raise ValueError('delisting requires explicit verified recovery, including zero')
    return sorted(data['cohorts'], key=lambda c: c['decision'])


def outcome(row, costs):
    """One fixed TWD sleeve; unfilled orders remain cash, blocked exits marked zero."""
    if row['entry_status'] != 'filled':
        return {'return': 0., 'status': 'entry_' + row['entry_status'], 'shares': 0}
    buy = row['entry_price'] * (1 + costs.slippage)
    shares = int(costs.allocation_twd / (buy * costs.lot_size)) * costs.lot_size
    while shares and shares * buy + max(costs.minimum_commission_twd, shares * buy * costs.commission) > costs.allocation_twd:
        shares -= costs.lot_size
    if not shares:
        return {'return': 0., 'status': 'insufficient_cash', 'shares': 0}
    debit = shares * buy + max(costs.minimum_commission_twd, shares * buy * costs.commission)
    if row['exit_status'] == 'blocked':
        proceeds = 0.  # explicit conservative terminal impairment; never pretend a fill
    elif row['exit_status'] == 'delisted':
        proceeds = shares * row['exit_price']  # verified cash recovery, no fictitious market sale
    else:
        gross = shares * row['exit_price'] * (1 - costs.slippage)
        proceeds = max(0., gross - max(costs.minimum_commission_twd, gross * costs.commission) - gross * costs.sell_tax)
    value = costs.allocation_twd - debit + proceeds + shares * row['dividend_per_share']
    return {'return': value / costs.allocation_twd - 1, 'status': row['exit_status'], 'shares': shares}


def quantile(values, p):
    s = sorted(values)
    x = (len(s) - 1) * p
    lo = int(x)
    return s[lo] + (s[min(lo + 1, len(s)-1)] - s[lo]) * (x-lo)


def distribution(values):
    if not values:
        return None
    return {'n': len(values), 'p10': quantile(values, .1), 'p50': quantile(values, .5),
            'p90': quantile(values, .9), 'probability_loss': sum(x < 0 for x in values)/len(values)}


def run(data, costs=Costs()):
    cohorts = validate(data)
    folds = []
    for test in cohorts:
        # Purge overlapping 12-month labels AND publication lag. No random split.
        train = [c for c in cohorts if c['decision'] < test['decision'] and
                 all(r['label_available'] < test['decision'] for r in c['rows'])]
        if not train:
            continue
        training_rows = [r for c in train for r in c['rows']]
        threshold = quantile([r['momentum'] for r in training_rows], .5)
        # Fresh research hypothesis: upper half momentum; threshold fit only on mature history.
        selected_train = [r for r in training_rows if r['momentum'] >= threshold]
        prediction = distribution([outcome(r, costs)['return'] for r in selected_train])
        selected = [r for r in test['rows'] if r['momentum'] >= threshold]
        executions = [dict(symbol=r['symbol'], **outcome(r, costs)) for r in selected]
        model_return = sum(e['return'] for e in executions)/len(executions) if executions else 0.
        equal = sum(outcome(r, costs)['return'] for r in test['rows'])/len(test['rows'])
        folds.append({'decision': test['decision'], 'train_decisions': [c['decision'] for c in train],
                      'latest_train_label': max(r['label_available'] for r in training_rows),
                      'threshold': threshold, 'prediction_12m': prediction, 'executions': executions,
                      'alphamax_return': model_return, 'equal_weight_return': equal, 'cash_return': 0.,
                      'realized_below_p10': model_return < prediction['p10'],
                      'realized_above_p90': model_return > prediction['p90']})
    if not folds:
        raise ValueError('no mature training labels / out-of-sample folds')
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {'model': 'AlphaMax', 'version': VERSION, 'engine_sha256': source_hash,
            'input_sha256': hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
            'data_kind': data['kind'], 'source': data['source'],
            'period': {'decision_start': cohorts[0]['decision'], 'decision_end': cohorts[-1]['decision'],
                       'outcome_end': max(r['exit_date'] for c in cohorts for r in c['rows'])},
            'assumptions': dict(asdict(costs), currency='TWD', holding='12 calendar months or longer to supplied exit session',
                                blocked_exit='zero terminal value; no assumed fill', allocation='equal independent sleeves; unused cash retained',
                                dividends='cash per original share, no reinvestment; prices must be unadjusted'),
            'unverified': data['unverified'] + ['Universe completeness and vendor publication timestamps require external audit',
                'Tax/fee schedule is configurable scenario, not date-effective exchange certification',
                'Corporate actions must be normalized upstream; no split/share-rights engine',
                'Independent overlapping cohorts are not a funded portfolio or CAGR',
                'Empirical security-level distribution is not a calibrated portfolio forecast; dependence and regime shifts unvalidated',
                'No exchange order-book, partial-fill, capacity or market-impact validation'],
            'folds': folds, 'oos_cohort_distribution': distribution([f['alphamax_return'] for f in folds])}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('input', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--costs', type=Path)
    args = p.parse_args()
    data = json.loads(args.input.read_text())
    report = run(data, Costs(**json.loads(args.costs.read_text())) if args.costs else Costs())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
