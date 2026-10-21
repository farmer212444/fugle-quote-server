"""Observe immutable forecast vintages without inventing matured outcomes."""
import datetime as dt
import json
from pathlib import Path

from .evidence import timestamp


def forward_observations(root, asof):
    from scripts.v897_freeze_model_vintage import verify_frozen_receipt
    root=Path(root)
    cutoff=timestamp(asof)
    cohorts, errors = {}, []
    for path in sorted((root/'pit_vintages').glob('*/*/receipt.json')):
        try:
            receipt=verify_frozen_receipt(path)
            vintage=timestamp(receipt['estimate_vintage'])
            if vintage>cutoff:
                continue
            # Many reruns on one date are one temporal cohort per strategy,
            # never independent statistical trials or extra trading sessions.
            key=(vintage.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat(),
                 receipt.get('strategy_variant_sha256') or receipt['model_code_sha256'])
            if key in cohorts and timestamp(cohorts[key]['estimate_vintage'])<=vintage:
                continue
            cohorts[key]=dict(model=receipt['model'],model_code_sha256=receipt['model_code_sha256'],
                              strategy_variant_sha256=receipt.get('strategy_variant_sha256'),
                              strategy_variant=receipt.get('strategy_variant','current-information'),
                              estimate_vintage=receipt['estimate_vintage'],
                              reference_price_date=receipt['issuer_market_reference_date'],
                              receipt_path=path.relative_to(root).as_posix(),
                              status='AWAITING_SUBSEQUENT_SESSION',
                              formal_out_of_sample_pass=False)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            errors.append(dict(path=path.relative_to(root).as_posix(),reason=str(exc)))
    dates=[]
    for path in (root/'prices').glob('20??-??-??.json'):
        day=dt.date.fromisoformat(path.stem)
        if day<=cutoff.date():
            dates.append(day.isoformat())
    dates=sorted(set(dates))
    for (signal_day,_),cohort in cohorts.items():
        later=[d for d in dates if d>signal_day]
        if later:
            cohort.update(status='FUTURE_PRICES_PRESENT_EXECUTION_AND_ACTION_REVIEW_REQUIRED',
                          first_subsequent_price_date=later[0],latest_observed_price_date=later[-1])
        cohort['missing_for_certified_return']=[
            'Verified next-session open and fillability',
            'Explicit spread/slippage/fees/tax policy fixed before outcome',
            'Dividends/splits/rights/delistings coverage for full holding period',
            'Matched benchmark total returns and predeclared evaluation horizon']
    rows=sorted(cohorts.values(),key=lambda x:(x['estimate_vintage'],x['model_code_sha256']))
    return dict(status='PROSPECTIVE_OBSERVATION_NOT_CERTIFIED_INVESTMENT_PERFORMANCE',
                distinct_signal_days=len({key[0] for key in cohorts}),
                strategy_date_cohorts=len(rows),cohorts=rows,archive_errors=errors,
                verified_net_total_return_observations=0,
                historical_reconstruction_used=False,formal_out_of_sample_pass=False)
