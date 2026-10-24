#!/usr/bin/env python3
"""One ordered research recipe, with measured stage times and failure receipts."""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def research_stages(phase='full'):
    stages=[
        ('valuation', ['tw_v880_run.py','--target-date','2027-12-31']),
        ('accounting_history', ['v881_history_diagnostic.py']),
        ('universe_queue', ['build_universe_verification_queue.py']),
        ('unmodeled_diagnostic', ['diagnose_unmodeled_universe.py']),
        ('unmodeled_blockers', ['v881_unmodeled_blockers.py']),
        ('thin_liquidity', ['v881_thin_shadow.py']),
        ('gate_dispatch', ['v883_gate_orchestrator.py','--top','50']),
        ('source_probe', ['v884_evidence_probe.py','--top','50','--focus','8390','1785','5439','4739','9802','6206']),
        ('gate_progress', ['v891_gate_certification.py']),
        ('review_work_queue', ['research_work_queue.py']),
        ('9802_early_revalue', ['v886_9802_early_revalue.py']),
        ('6206_valuation', ['v888_6206_valuation.py']),
        ('6206_triage', ['v891_6206_gate_triage.py']),
        ('chip_diagnostic', ['tw_chip_diagnostic.py']),
        ('risk_audit', ['v880_audit_exports.py','--kind','risk']),
        ('cash_audit', ['v880_audit_exports.py','--kind','cash']),
        ('shares_audit', ['v880_audit_exports.py','--kind','shares']),
        ('9802_cash_review', ['cash_quality_9802.py']),
        ('footwear_review', ['footwear_review.py']),
        ('five_candidate_audit', ['v890_five_candidate_audit.py']),
        ('top20_quality', ['v892_top20_quality_audit.py']),
        ('revenue_discovery', ['v894_revenue_lead_discovery.py']),
        ('etf_rotation', ['v8a6_etf_rotation_watch.py']),
        ('2069_valuation', ['v8a7_2069_independent_valuation.py']),
        ('quality_decision', ['v8a5_quality_decision_lane.py']),
        ('historical_source_readiness', ['historical_pit_readiness.py']),
        ('return_model_search', ['return_model_search.py']),
        ('shadow_comparison', ['institutional_shadow.py']),
        ('benchmark_validation', ['benchmark_validation.py']),
        ('institutional_review', ['institutional_review.py']),
        ('munger_inversion', ['munger_quality_review.py']),
    ]
    if phase=='core':
        return stages[:-4]
    if phase=='observation':
        return stages[-4:]
    if phase!='full':
        raise ValueError('UNKNOWN_RESEARCH_PHASE')
    return stages


def atomic_json(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.write('\n')
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_pipeline(repo_root=ROOT,*,runner=None,clock=None,stages=None,report_path=None,phase='full'):
    repo_root=Path(repo_root).resolve()
    runner=runner or subprocess.run
    clock=clock or time.perf_counter
    stages=research_stages(phase) if stages is None else stages
    filename='latest_observation_timing.json' if phase=='observation' else 'latest_pipeline_timing.json'
    path=Path(report_path) if report_path is not None else repo_root/'tw-market-data/rankings'/filename
    start=clock()
    report=dict(schema='RESEARCH_PIPELINE_TIMING_V1',
                started_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                status='RUNNING',phase=phase,stages=[],
                measures='ORDERED_RESEARCH_STAGES_EXCLUDING_TESTS_SOURCE_REFRESH_AND_PUBLICATION',
                engineering_timing_is_not_investment_validation=True)
    atomic_json(path,report)
    for name,args in stages:
        command=[sys.executable,str(repo_root/'scripts'/args[0]),*args[1:]]
        entry=dict(stage=name,argv=['python','scripts/'+args[0],*args[1:]],status='RUNNING')
        report['stages'].append(entry)
        began=clock()
        atomic_json(path,report)
        try:
            completed=runner(command,cwd=repo_root,check=True)
            if completed.returncode:
                raise subprocess.CalledProcessError(completed.returncode,command)
        except (OSError,subprocess.CalledProcessError) as exc:
            entry.update(status='FAILED',elapsed_seconds=round(clock()-began,6),
                         returncode=getattr(exc,'returncode',None),error=str(exc))
            report.update(status='FAILED',failed_stage=name,total_elapsed_seconds=round(clock()-start,6))
            atomic_json(path,report)
            raise
        entry.update(status='SUCCESS',elapsed_seconds=round(clock()-began,6),returncode=0)
        report['total_elapsed_seconds']=round(clock()-start,6)
        atomic_json(path,report)
        print(json.dumps(dict(stage=name,elapsed_seconds=entry['elapsed_seconds'],status='SUCCESS')),flush=True)
    report.update(status='SUCCESS',total_elapsed_seconds=round(clock()-start,6),
                  completed_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    atomic_json(path,report)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report-path')
    parser.add_argument('--phase',choices=('full','core','observation'),default='full')
    args=parser.parse_args()
    try:
        run_pipeline(report_path=args.report_path,phase=args.phase)
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except OSError:
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
