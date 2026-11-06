"""Source-bound retrospective financial-input admission, separate from forecasts.

An original's publication/revision review can be performed today. The source
version itself must have been available before the historical signal. Neither
review time nor capture time is backdated. This does not certify OOS returns.
"""
import datetime as dt
import re
from pathlib import Path
from urllib.parse import urlparse

from .evidence import timestamp, verify_certificate_archives
from .validation_io import source

SCHEMA = 'HISTORICAL_FINANCIAL_PIT_REVIEW_V1'
FOLDER = 'evidence/v880/historical_pit_reviews'
OFFICIAL_HOSTS = {'mops.twse.com.tw','mopsov.twse.com.tw','www.twse.com.tw','www.tpex.org.tw'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def check(root, pack, asof):
    """Requires source-identity reviews under the existing archive-review contract.

    No reviewer identity, source authentication or publication date is generated
    by this function. Normalized mirror flags alone are never admissible proof.
    """
    root = Path(root).resolve(); now = timestamp(asof)
    require(pack.get('schema') == SCHEMA, 'HISTORICAL_PIT_REVIEW_SCHEMA_INVALID')
    market,period,kind = (pack.get(k) for k in ('market','period','kind'))
    require(market in ('TWSE','TPEX') and kind in ('income','cashflow')
            and isinstance(period,str) and re.fullmatch(r'20\d{2}-Q[1-4]',period),
            'HISTORICAL_PIT_BATCH_IDENTITY_INVALID')
    signal = timestamp(pack['signal_at'])
    checked = timestamp(pack['checked_at'])
    require(signal <= checked <= now, 'HISTORICAL_PIT_REVIEW_CLOCK_INVALID')
    year,quarter = int(period[:4]),int(period[-1])
    end = dt.date(year+1,1,1)-dt.timedelta(days=1) if quarter == 4 else dt.date(year,quarter*3+1,1)-dt.timedelta(days=1)
    require(end <= signal.date(), 'HISTORICAL_PIT_FINANCIAL_PERIOD_FROM_FUTURE')
    document = source(root,pack['normalized_input'])
    require(all(document.get(k) == v for k,v in (('market',market),('period',period),('kind',kind))),
            'HISTORICAL_PIT_NORMALIZED_IDENTITY_MISMATCH')
    rows = document.get('rows')
    require(isinstance(rows,list) and rows and all(isinstance(r,dict) for r in rows),
            'HISTORICAL_PIT_INPUT_ROWS_MISSING')
    require(all(r.get('market') == market and r.get('period') == period for r in rows),
            'HISTORICAL_PIT_ROW_IDENTITY_MISMATCH')
    keys = [r.get('code') for r in rows]
    require(len(keys) == len(set(keys)) and all(isinstance(k,str) and re.fullmatch(r'\d{4}',k) for k in keys),
            'HISTORICAL_PIT_DUPLICATE_OR_INVALID_ISSUER')
    reviews = [source(root,ref) for ref in pack.get('issuer_reviews',[])]
    require(len(reviews) == len(keys) and {r.get('code') for r in reviews} == set(keys),
            'HISTORICAL_PIT_PARTIAL_OR_EXTRA_ISSUER_REVIEWS')
    for review in reviews:
        require(review.get('market') == market and review.get('kind') == kind
                and review.get('normalized_input_sha256') == pack['normalized_input']['sha256'],
                'HISTORICAL_PIT_REVIEW_NOT_BOUND_TO_INPUT')
        gate = review.get('gates',{}).get('point_in_time',{})
        require(gate.get('status') == 'PASS' and gate.get('issuer') == review['code']
                and gate.get('financial_period') == period
                and isinstance(gate.get('reviewed_by'),str) and bool(gate['reviewed_by'].strip())
                and isinstance(gate.get('method'),str) and bool(gate['method'].strip())
                and gate.get('normalized_values_reconciled_to_originals') is True
                and gate.get('revision_history_complete_through_signal') is True,
                'HISTORICAL_PIT_SOURCE_REVIEW_INCOMPLETE')
        require(timestamp(gate['review_signal_at']) == signal
                and signal <= timestamp(gate['checked_at']) <= checked,
                'HISTORICAL_PIT_REVIEW_SCOPE_OR_TIME_MISMATCH')
        proof = gate.get('publication_and_revision_evidence')
        require(isinstance(proof,list) and bool(proof), 'HISTORICAL_PIT_PUBLICATION_PROOF_MISSING')
        for ref in proof:
            url = urlparse(ref.get('url',''))
            require(url.scheme == 'https' and url.hostname in OFFICIAL_HOSTS,
                    'HISTORICAL_PIT_PUBLICATION_PROOF_NOT_OFFICIAL')
            source(root,ref,decode=False)
        # Recompute every original archive SHA; retain the established requirement
        # for a documented source-identity reviewer. No synthetic production PASS.
        verify_certificate_archives(dict(code=review['code'],gates={'point_in_time':gate}),root)
        for ref in gate['sources']:
            url = urlparse(ref.get('url',''))
            require(url.scheme == 'https' and url.hostname in OFFICIAL_HOSTS
                    and ref.get('origin_authenticated') is True
                    and isinstance(ref.get('version_id'),str) and bool(ref['version_id'].strip()),
                    'HISTORICAL_PIT_OFFICIAL_SOURCE_OR_VERSION_MISSING')
            published,revision,available = (timestamp(ref[k]) for k in ('published_at','revision_at','available_at'))
            require(published <= revision <= available <= signal,
                    'HISTORICAL_PIT_UNPUBLISHED_OR_LATER_REVISION')
    return dict(market=market,period=period,kind=kind,signal_at=pack['signal_at'],
                normalized_input_sha256=pack['normalized_input']['sha256'],issuer_count=len(keys),
                admission_scope='FINANCIAL_SOURCE_VERSIONS_ONLY_NOT_UNIVERSE_EXECUTION_OR_OOS',
                reviewed_at=pack['checked_at'],historical_model_preissuance_claimed=False)


def admitted_batches(root,asof):
    import json
    root = Path(root).resolve(); accepted,rejected,seen = [],[],set()
    for path in sorted((root/FOLDER).glob('*.json')):
        try:
            row = check(root,json.loads(path.read_bytes()),asof)
            key = (row['market'],row['period'],row['kind'],row['normalized_input_sha256'],row['signal_at'])
            require(key not in seen,'HISTORICAL_PIT_DUPLICATE_BATCH')
            seen.add(key);accepted.append(dict(path=path.relative_to(root).as_posix(),**row))
        except (ValueError,KeyError,TypeError,OSError,AttributeError) as exc:
            rejected.append(dict(path=path.relative_to(root).as_posix(),reason=str(exc)))
    return dict(admitted=accepted,rejected=rejected)


def calibration_feasibility(reference_date,target_date,policy):
    """A fixed terminal date allows at most one nonoverlapping outcome window."""
    first,last = dt.date.fromisoformat(reference_date),dt.date.fromisoformat(target_date)
    days = (last-first).days
    require(days > 0,'CALIBRATION_NONPOSITIVE_HORIZON')
    train,test = policy['minimum_train_cohorts'],policy['minimum_oos_cohorts']
    require(type(train) is int and train > 0 and type(test) is int and test > 0,
            'CALIBRATION_COHORT_POLICY_INVALID')
    required = train+test
    # A lower bound: ignores holidays, embargo, issuer/industry coverage and the
    # need to have completed/verified training before each subsequent test.
    span = required*days
    return dict(status='HISTORICAL_REPLAY_PROTOCOL_REQUIRED',holding_calendar_days=days,
        minimum_train_cohorts=train,minimum_oos_cohorts=test,
        minimum_total_nonoverlapping_cohorts=required,
        maximum_nonoverlapping_cohorts_with_same_terminal_date=1,
        fixed_target_only_can_satisfy_policy=required <= 1,
        minimum_history_span_days_ignoring_embargo=span,
        minimum_history_span_years_ignoring_embargo=round(span/365.25,2),
        waiting_until_target_date_alone_resolves_calibration=False,
        exact_horizon_industry_method_matches_still_required=True,
        historical_replay_is_a_separate_protocol_not_backdated_prospective_forecasts=True)
