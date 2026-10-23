#!/usr/bin/env python3
"""Prioritize actual missing evidence; never manufacture a review or PASS."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from tw_model_v880.evidence import GATES
from scripts.run_research_pipeline import atomic_json

FILING_GATES=frozenset(('original_eight_quarter_statements','cash_and_working_capital',
                       'nonoperating_components','auditor_scope','point_in_time'))
WATCHLIST=frozenset(('6206','9802'))


def build_queue(progress,research):
    for key in ('model','estimate_vintage','asof_price_date'):
        if progress.get(key)!=research.get(key):
            raise ValueError('WORK_QUEUE_MODEL_CONTEXT_MISMATCH')
    jobs=[]
    seen=set()
    strategy_issuers=[]
    for row in progress['issuer_diagnostics']:
        identity=(row['market'],row['code'])
        if identity in seen:
            raise ValueError('WORK_QUEUE_DUPLICATE_ISSUER')
        seen.add(identity)
        decisions=row['gate_stage']
        if set(decisions)!=set(GATES):
            raise ValueError('WORK_QUEUE_INCOMPLETE_GATE_LEDGER')
        work=[]
        passed=[]
        failed=[]
        for name in GATES:
            item=decisions[name]
            decision=item['decision']
            if decision not in ('PASS','FAIL','PENDING','NOT_EVALUATED'):
                raise ValueError('WORK_QUEUE_UNKNOWN_DECISION')
            if item.get('formal_pass') is not (decision=='PASS'):
                raise ValueError('WORK_QUEUE_INCONSISTENT_FORMAL_PASS')
            if decision=='PASS':
                passed.append(name)
                continue
            if decision=='FAIL':
                failed.append(name)
                action='RESOLVE_DOCUMENTED_FORMAL_FAILURE'
            elif decision=='NOT_EVALUATED':
                action='RESTORE_REQUIRED_MODEL_INPUTS'
            elif item['stage'] in ('NOT_PROBED','SOURCE_MISSING','MIRROR_CAPTURED'):
                action='CAPTURE_AND_VERIFY_ORIGINAL_SOURCE'
            elif item['stage']=='SOURCE_CAPTURED':
                action='REVIEW_ARCHIVED_SOURCE_AND_COMPLETE_SIGNOFF'
            else:
                action='COMPLETE_EVIDENCE_BRIDGE_AND_REVIEW'
            work.append(dict(gate=name,decision=decision,stage=item['stage'],
                             next_action=action,scope=item['scope'],
                             required_evidence=item['required_evidence'],
                             reason=item['reason'],model_reason=item.get('model_reason'),
                             invalidates_on=item['invalidates_on']))
            if name=='out_of_sample_validation':
                strategy_issuers.append(dict(market=row['market'],code=row['code'],decision=decision))
        jobs.append(dict(market=row['market'],code=row['code'],name=row.get('name'),
                         financial_period=row['financial_period'],
                         reviewed_financial_period=row.get('reviewed_financial_period'),
                         research_upside_pct=row.get('research_upside_pct'),
                         watchlist_focus=row['code'] in WATCHLIST,
                         passed_gate_count=len(passed),failed_gates=failed,
                         unresolved_gate_count=len(work),work=work,
                         filing_collection_packet=dict(
                             gates=[item['gate'] for item in work if item['gate'] in FILING_GATES],
                             reuse='COLLECT_SAME_ISSUER_ORIGINALS_ONCE_REVIEW_EACH_GATE_SEPARATELY'),
                         formal_Aplus=row['formal_Aplus']))
    # Existing focus first, then no known FAIL and the most completed evidence.
    # Upside breaks ties; it never overrides the source or quality requirements.
    jobs.sort(key=lambda row:(not row['watchlist_focus'],bool(row['failed_gates']),
                              -row['passed_gate_count'],
                              -(row['research_upside_pct'] if row['research_upside_pct'] is not None else -float('inf')),
                              row['market'],row['code']))
    return dict(schema='RESEARCH_EVIDENCE_WORK_QUEUE_V1',
                model=research['model'],estimate_vintage=research['estimate_vintage'],
                asof_price_date=research['asof_price_date'],
                source_model_sha256=research['model_code_sha256'],
                issuer_job_count=len(jobs),unresolved_gate_count=sum(r['unresolved_gate_count'] for r in jobs),
                scope='ISSUERS_INCLUDED_IN_CURRENT_GATE_DIAGNOSTICS_NOT_ALL_TRACKED_COMPANIES',
                issuer_jobs=jobs,
                governance_followup_tasks=[dict(code=row['code'],market=row['market'],
                    name=row.get('name'),status=row['governance_review']['status'],
                    recommendation_blocked=True,
                    next_action='CHECK_ORIGINAL_JUDICIAL_DISCLOSURE_ACCOUNTING_CONTROLS_AND_REMEDIES',
                    events=row['governance_review'].get('events',[]),
                    source_error=row['governance_review'].get('reason'))
                    for row in research.get('governance_watch',[])],
                shared_strategy_collection_task=dict(
                    gate='out_of_sample_validation',
                    strategy_variant_sha256=research.get('strategy_variant_sha256'),
                    target_date=research['target_date'],affected_issuers=strategy_issuers,
                    next_action='COLLECT_FIXED_RULE_PIT_COST_AND_OUTCOME_EVIDENCE_ONCE_THEN_REVIEW_APPLICABILITY',
                    per_issuer_and_subgroup_applicability_review_required=True,
                    collection_group_is_not_a_shared_certificate=True),
                formal_gate_decisions_changed=0,certificates_issued=0)


def render(report):
    lines=['# 原始證據工作佇列','',
           f"模型：{report['model']}；估計：{report['estimate_vintage']}。",
           '僅涵蓋當次認證診斷名單。優先關注股，再按已完成門檻排序；潛在漲幅僅作同順位排序。',
           '同公司原始財報集中蒐集，各項仍須獨立查核；策略證據集中蒐集後仍須核對個股與子群適用性。','',
           '|股票|已通過|明確未通過|未結案|下一項工作|','|---|---:|---:|---:|---|']
    for job in report['issuer_jobs']:
        first=job['work'][0] if job['work'] else None
        action=first['required_evidence'] if first else '已無待辦項目'
        lines.append(f"|{job['code']} {job.get('name') or ''}|{job['passed_gate_count']}/13|"
                     f"{len(job['failed_gates'])}|{job['unresolved_gate_count']}|{action}|")
    if report.get('governance_followup_tasks'):
        lines+=['','## 重大治理事件待辦','',
                '僅涵蓋已登錄事件；維持暫停推薦，不能以營運正常或單純時間經過自動解除。','']
        for job in report['governance_followup_tasks']:
            lines.append('- '+job['code']+' '+(job.get('name') or '')+'：'+job['status'])
            for event in job['events']:
                for evidence in event.get('next_evidence',[]):lines.append('  - '+evidence)
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',default='tw-market-data')
    args=parser.parse_args()
    root=Path(args.data_root)
    raw=(root/'rankings/v891_gate_progress.json').read_bytes()
    research=json.loads((root/'rankings/latest_research.json').read_bytes())
    report=build_queue(json.loads(raw),research)
    report['source_progress_sha256']=hashlib.sha256(raw).hexdigest()
    atomic_json(root/'rankings/latest_research_work_queue.json',report)
    (root/'rankings/latest_research_work_queue.md').write_text(render(report),encoding='utf-8')
    print(json.dumps(dict(issuer_jobs=report['issuer_job_count'],unresolved_gates=report['unresolved_gate_count'],
                         certificates_issued=0)))


if __name__=='__main__':
    main()
