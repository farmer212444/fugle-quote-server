"""Consume registered trials and recompute outcomes from hashed source files."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from .contracts import canonical_hash
from .evidence import timestamp
from .execution import net_trade,COST_FIELDS


TAIPEI = dt.timezone(dt.timedelta(hours=8))


def taipei_signal_date(when):
    """Resolve either an aware datetime or ISO timestamp to the Taiwan cohort."""
    instant = when if isinstance(when, dt.datetime) else timestamp(when)
    if instant.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return instant.astimezone(TAIPEI).date().isoformat()


def source(root,reference,decode=True):
    rel=Path(reference['path'])
    path=(root/rel).resolve()
    if rel.is_absolute() or '..' in rel.parts or root not in path.parents:
        raise ValueError('VALIDATION_UNSAFE_SOURCE_PATH')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=reference.get('sha256'):
        raise ValueError('VALIDATION_SOURCE_HASH_MISMATCH')
    return json.loads(raw) if decode else raw


def immutable_registration(root,spec,now):
    """A changed hypothesis requires a new trial ID; never rewrite its clock."""
    root=Path(root)
    trial_id=spec.get('trial_id')
    if not isinstance(trial_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',trial_id):
        raise ValueError('INVALID_TRIAL_ID')
    path=root/'experiments/registrations'/(trial_id+'.json')
    if path.exists():
        prior=json.loads(path.read_text())
        if prior.get('spec_sha256')!=canonical_hash(spec) or prior.get('spec')!=spec:
            raise ValueError('REGISTERED_EXPERIMENT_IS_IMMUTABLE_USE_NEW_TRIAL_ID')
        return prior
    timestamp(now)
    obj=dict(schema='V810_PROSPECTIVE_TRIAL_REGISTRATION',registered_at=now,
             spec_sha256=canonical_hash(spec),spec=spec,
             registry_is_prospective_not_a_historical_PIT_certificate=True)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(obj,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    return obj


def collect_trials(root,asof):
    """No manual net-return or victory flag is accepted as an observed outcome."""
    from scripts.v897_freeze_model_vintage import verify_frozen_receipt
    root=Path(root).resolve();cutoff=timestamp(asof)
    trials=[];errors=[];probability_records=[];valid_trade_count=0
    registration_paths=sorted((root/'experiments/registrations').glob('*.json'))
    for path in registration_paths:
        pairs=[];rejected=[]
        try:
            registration=json.loads(path.read_text(encoding='utf-8'))
            spec=registration['spec']
            if registration.get('schema')!='V810_PROSPECTIVE_TRIAL_REGISTRATION' or registration['spec_sha256']!=canonical_hash(spec):
                raise ValueError('TRIAL_REGISTRATION_HASH_OR_SCHEMA_MISMATCH')
            registered=timestamp(registration['registered_at'])
            if registered>cutoff:
                continue
            input_path=root/'experiments/inputs'/(path.stem+'.json')
            if not input_path.exists():
                trials.append(dict(trial_id=path.stem,status='AWAITING_FUTURE_OUTCOME_INPUTS',pairs=[],promotion_eligible=False))
                continue
            payload=json.loads(input_path.read_text(encoding='utf-8'))
            if payload.get('registration_sha256')!=canonical_hash(registration):
                raise ValueError('OUTCOME_INPUT_NOT_BOUND_TO_REGISTERED_TRIAL')
            costs=spec.get('cost_policy')
            if not isinstance(costs,dict) or any(k not in costs for k in COST_FIELDS):
                raise ValueError('COST_POLICY_NOT_FIXED_IN_PROSPECTIVE_REGISTRATION')
            for outcome in payload.get('outcomes',[]):
                try:
                    signal=timestamp(outcome['signal_at']);end=timestamp(outcome['exit_at'])
                    if not registered<=signal<end<=cutoff:
                        raise ValueError('TRIAL_NOT_REGISTERED_BEFORE_SIGNAL_OR_OUTCOME_NOT_MATURE')
                    returns={}
                    frozen_times={}
                    for variant in ('champion','challenger'):
                        variant_input=outcome[variant]
                        frozen_rel=Path(variant_input['frozen_receipt_path'])
                        frozen=(root/frozen_rel).resolve()
                        if frozen_rel.is_absolute() or '..' in frozen_rel.parts or root not in frozen.parents:
                            raise ValueError('UNSAFE_FROZEN_MODEL_PATH')
                        receipt=verify_frozen_receipt(frozen)
                        strategy_id=receipt.get('strategy_variant_sha256') or receipt['model_code_sha256']
                        frozen_at=max(timestamp(receipt['estimate_vintage']),timestamp(receipt['archived_at_utc']))
                        if strategy_id!=spec[variant+'_model_sha256'] or frozen_at>signal:
                            raise ValueError('MODEL_NOT_FROZEN_BEFORE_SIGNAL_OR_WRONG_VARIANT')
                        frozen_times[variant]=frozen_at.isoformat()
                        if spec.get('selection_rule')!='RESEARCH_TOP10_EQUAL_WEIGHT_NEXT_OPEN':
                            raise ValueError('UNSUPPORTED_PREDECLARED_SELECTION_RULE')
                        frozen_model=json.loads((frozen.parent/'latest_research.json').read_text())
                        required={(r['market'],r['code']) for r in frozen_model['top10_market_research']}
                        legs=variant_input['legs']
                        observed={(r['market'],r['code']) for r in legs}
                        if not required or required!=observed or len(observed)!=len(legs):
                            raise ValueError('WINNER_SELECTION_OR_MISSING_FROZEN_PORTFOLIO_LEGS')
                        leg_returns=[]
                        for trade in legs:
                            review=source(root,trade['corporate_action_review'])
                            if (review.get('complete') is not True or not review.get('reviewer_id')
                                    or review.get('code')!=trade.get('code') or review.get('market')!=trade.get('market')
                                    or timestamp(review['from'])>signal or timestamp(review['through'])<end
                                    or not end<=timestamp(review['checked_at'])<=cutoff or not review.get('original_sources')):
                                raise ValueError('FULL_HOLDING_WINDOW_CORPORATE_ACTION_REVIEW_REQUIRED')
                            for original in review['original_sources']:
                                source(root,original,decode=False)
                            bars=source(root,trade['bars'])
                            if not isinstance(bars,list) or any(b.get('code')!=trade['code'] or b.get('market')!=trade['market'] for b in bars):
                                raise ValueError('EXECUTION_BAR_ISSUER_MISMATCH')
                            eligible=[b for b in bars if timestamp(b['open_at'])>signal and timestamp(b['close_at'])<=end]
                            if len(eligible)!=spec['holding_sessions']:
                                raise ValueError('OUTCOME_WINDOW_DIFFERS_FROM_REGISTERED_HOLDING_SESSIONS')
                            actions=source(root,trade['actions'])
                            leg_returns.append(net_trade(bars,actions,signal_at=outcome['signal_at'],exit_at=outcome['exit_at'],
                                                      costs=costs,corporate_actions_complete=True,
                                                      requested_notional_ntd=spec['reference_notional_ntd']/len(legs),
                                                      max_participation=spec['max_daily_participation'])['net_total_return'])
                        returns[variant]=sum(leg_returns)/len(leg_returns)
                    signal_day=taipei_signal_date(signal)
                    pairs.append(dict(signal_date=signal_day,signal_at=signal.isoformat(),
                                      champion_net_return=returns['champion'],challenger_net_return=returns['challenger'],
                                      champion_frozen_at=frozen_times['champion'],challenger_frozen_at=frozen_times['challenger'],
                                      execution_and_actions_verified=True,
                                      cost_policy_sha256_champion=canonical_hash(costs),cost_policy_sha256_challenger=canonical_hash(costs),
                                      outcome_end_champion=end.isoformat(),outcome_end_challenger=end.isoformat(),
                                      market_regime=(spec.get('predeclared_market_regimes') or {}).get(signal_day)))
                    valid_trade_count+=2
                    prediction=(spec.get('preissued_positive_return_probabilities') or {}).get(signal_day)
                    if prediction is not None:
                        probability_records.append(dict(sample_id=path.stem+':'+signal_day,
                                                        predicted_probability=prediction,
                                                        outcome=returns['challenger']>0,
                                                        probability_issued_at=registration['registered_at'],
                                                        outcome_at=end.isoformat()))
                except (ValueError,KeyError,OSError,TypeError) as exc:
                    rejected.append(dict(signal_at=outcome.get('signal_at'),reason=str(exc)))
            trials.append(dict(trial_id=path.stem,status='RECOMPUTED_RESEARCH_OUTCOMES',pairs=pairs,
                               rejected_outcomes=rejected,all_outcomes_usable=not rejected,
                               formal_out_of_sample_pass=False))
        except (ValueError,KeyError,OSError,TypeError) as exc:
            errors.append(dict(trial_id=path.stem,reason=str(exc)))
    return dict(trials=trials,errors=errors,probability_records=probability_records,registered_trial_count=len(registration_paths),
                validated_trade_observations=valid_trade_count,formal_out_of_sample_pass=False)
