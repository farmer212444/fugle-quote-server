#!/usr/bin/env python3
"""Freeze current vs no-new-earnings-event counterfactuals and register the trial."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.tw_v880_run import run
from scripts.v897_freeze_model_vintage import freeze
from tw_model_v880 import VERSION
from tw_model_v880.contracts import canonical_hash
from tw_model_v880.validation_io import immutable_registration


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-root',default='tw-market-data')
    args=parser.parse_args();root=Path(args.data_root)
    current=json.loads((root/'rankings/latest_research.json').read_text())
    baseline=run(root,current['estimate_vintage'],current['target_date'],root/'rankings/champion',variant='without-earnings-events')
    now=dt.datetime.now(dt.timezone.utc)
    frozen_current=freeze(root,now,VERSION)
    frozen_baseline=freeze(root,now,VERSION,rankings_subdir='rankings/champion')
    config=json.loads((root/'config/institutional_research.json').read_text())
    spec=dict(hypothesis='Reconciled issuer earnings events improve forecasts and research selections versus the same model without those events',
              champion_model_sha256=baseline['strategy_variant_sha256'],challenger_model_sha256=current['strategy_variant_sha256'],
              selection_rule='RESEARCH_TOP10_EQUAL_WEIGHT_NEXT_OPEN',holding_sessions=21,
              model_target_date=current['target_date'],cost_policy=config['cost_policy'],
              reference_notional_ntd=config['reference_capital_ntd'],max_daily_participation=config['risk_policy']['max_daily_participation'],
              minimum_nonoverlapping_oos_periods=config['experiment_policy']['minimum_nonoverlapping_oos_periods'],
              no_investment_edge_claim_before_matured_outcomes=True)
    spec['trial_id']='earnings-events-'+canonical_hash(spec)[:20]
    registered=immutable_registration(root,spec,now.isoformat())
    print(json.dumps(dict(trial_id=spec['trial_id'],registered_at=registered['registered_at'],
                          current_archive=frozen_current['path'],baseline_archive=frozen_baseline['path'],
                          cost_policy_fixed=config['cost_policy'] is not None,
                          evaluation_status='AWAITING_PREDECLARED_COSTS_AND_FUTURE_OUTCOME_SOURCES'),ensure_ascii=False))


if __name__=='__main__':main()
