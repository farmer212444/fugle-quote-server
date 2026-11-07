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
# Prioritize work that can actually advance with already archived issuer originals.
# A review-pending label or share/turnover mirror does not establish a
# complete issuer original, let alone permission to issue a formal PASS.
ORIGINAL_REVIEW_GATES=frozenset(('original_eight_quarter_statements','management_promises'))
ACTION_ZH={
    'REVIEW_ARCHIVED_SOURCE_AND_COMPLETE_SIGNOFF':'核閱已封存原件並補齊附註後再具名覆核',
    'REVIEW_MANAGEMENT_GUIDANCE':'核對已封存法說承諾與後續實績',
    'VERIFY_CAPITAL_DILUTION_TERMS':'已取得股數摘要；補可轉債、員工認股及稀釋分母原件',
    'VERIFY_MARKET_SPREAD_EXIT_CAPACITY':'已有成交額；補價差、滑價及清倉能力驗證',
    'COMPLETE_EVIDENCE_BRIDGE_AND_REVIEW':'補公司別勾稽與具名覆核',
    'CAPTURE_AND_VERIFY_ORIGINAL_SOURCE':'蒐集並驗證原始資料及SHA',
    'RESTORE_REQUIRED_MODEL_INPUTS':'修復缺漏的模型輸入',
    'RESOLVE_DOCUMENTED_FORMAL_FAILURE':'處理已明確失敗的證據',
}


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
                action={
                    'fully_diluted_shares':'VERIFY_CAPITAL_DILUTION_TERMS',
                    'tradability':'VERIFY_MARKET_SPREAD_EXIT_CAPACITY',
                    'management_promises':'REVIEW_MANAGEMENT_GUIDANCE',
                }.get(name,'REVIEW_ARCHIVED_SOURCE_AND_COMPLETE_SIGNOFF' if name in ORIGINAL_REVIEW_GATES
                      else 'COMPLETE_EVIDENCE_BRIDGE_AND_REVIEW')
            else:
                action='COMPLETE_EVIDENCE_BRIDGE_AND_REVIEW'
            work.append(dict(gate=name,decision=decision,stage=item['stage'],
                             next_action=action,scope=item['scope'],
                             required_evidence=item['required_evidence'],
                             reason=item['reason'],model_reason=item.get('model_reason'),
                             invalidates_on=item['invalidates_on']))
            if name=='out_of_sample_validation':
                strategy_issuers.append(dict(market=row['market'],code=row['code'],decision=decision))
        # The strategy-level OOS gate is collected once for a fixed strategy,
        # not repeatedly presented as each issuer's first clerical task.
        issuer_work=[w for w in work if w['gate']!='out_of_sample_validation']
        def task_priority(task):
            if task['decision']=='FAIL':
                return (0,GATES.index(task['gate']))
            return ({
                'SOURCE_CAPTURED':1,
                'MIRROR_CAPTURED':2,
                'REVIEW_PENDING':3,
                'SOURCE_MISSING':4,
                'NOT_PROBED':5,
            }.get(task['stage'],6),
                0 if task['gate'] in ORIGINAL_REVIEW_GATES else 1,
                GATES.index(task['gate']))
        next_issuer_task=min(issuer_work,key=task_priority) if issuer_work else None
        source_advanced_gates=[w['gate'] for w in issuer_work
                               if w['stage']=='SOURCE_CAPTURED' and w['decision']=='PENDING']
        ready_issuer_gates=[g for g in source_advanced_gates if g in ORIGINAL_REVIEW_GATES]
        upside=row.get('research_upside_pct')
        price_lane=('A_PLUS_PRICE_ONLY' if type(upside) in (int,float) and upside>=30
                    else 'A_DISCOVERY_PRICE_ONLY' if type(upside) in (int,float) and upside>=25
                    else 'PRICE_GATE_NOT_MET')
        jobs.append(dict(market=row['market'],code=row['code'],name=row.get('name'),
                         financial_period=row['financial_period'],
                         reviewed_financial_period=row.get('reviewed_financial_period'),
                         research_upside_pct=row.get('research_upside_pct'),
                         watchlist_focus=row['code'] in WATCHLIST,
                         passed_gate_count=len(passed),failed_gates=failed,
                         unresolved_gate_count=len(work),work=work,
                         price_lane=price_lane,
                         source_advanced_gate_count=len(source_advanced_gates),
                         source_advanced_gates=source_advanced_gates,
                         review_ready_original_gate_count=len(ready_issuer_gates),
                         review_ready_original_gates=ready_issuer_gates,
                         next_issuer_gate=next_issuer_task['gate'] if next_issuer_task else None,
                         next_issuer_action=next_issuer_task['next_action'] if next_issuer_task else None,
                         next_issuer_stage=next_issuer_task['stage'] if next_issuer_task else None,
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
    # Explicit high-upside lane: source-readiness, not upside alone, picks the
    # next issuer to audit. Formal certification counts remain engine-owned.
    high_upside=[r for r in jobs if r['price_lane']=='A_PLUS_PRICE_ONLY']
    high_upside.sort(key=lambda x:(bool(x['failed_gates']),
                                  -x['passed_gate_count'],
                                  -x['review_ready_original_gate_count'],
                                  -(x['research_upside_pct'] or 0),x['code']))
    gate_blockers={g:sum(g in {w['gate'] for w in issuer['work']}
                         for issuer in high_upside) for g in GATES}
    return dict(schema='RESEARCH_EVIDENCE_WORK_QUEUE_V1',
                model=research['model'],estimate_vintage=research['estimate_vintage'],
                asof_price_date=research['asof_price_date'],
                source_model_sha256=research['model_code_sha256'],
                issuer_job_count=len(jobs),unresolved_gate_count=sum(r['unresolved_gate_count'] for r in jobs),
                scope='ISSUERS_INCLUDED_IN_CURRENT_GATE_DIAGNOSTICS_NOT_ALL_TRACKED_COMPANIES',
                issuer_jobs=jobs,
                aplus_repair=dict(
                    price_qualified_research_issuers=len(high_upside),
                    strategy_level_gate='out_of_sample_validation',
                    strategy_backtest_requires_real_PIT_and_cost_adjusted_OOS=True,
                    high_upside_gate_pending_counts=gate_blockers,
                    original_captured_review_pending_issuers=sum(
                        bool(r['review_ready_original_gate_count']) for r in high_upside),
                    review_ready_gate_issues=sum(r['review_ready_original_gate_count'] for r in high_upside),
                    source_advanced_issuers=sum(bool(r['source_advanced_gate_count']) for r in high_upside),
                    source_advanced_gate_issues=sum(r['source_advanced_gate_count'] for r in high_upside),
                    verification_priority=[
                        dict(code=r['code'],name=r['name'],
                             upside_pct=r['research_upside_pct'],
                             pass_count=r['passed_gate_count'],
                             review_ready_original_gates=r['review_ready_original_gates'],
                             next_issuer_gate=r['next_issuer_gate'],
                             next_issuer_action=r['next_issuer_action'],
                             next_issuer_stage=r['next_issuer_stage'])
                        for r in high_upside[:30]],
                    no_gate_auto_passed=True,
                    no_reviewer_or_historical_results_fabricated=True),
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
    aplus=report['aplus_repair']
    lines=['# A+ 原始證據修復佇列','',
           f"模型：{report['model']}；估計：{report['estimate_vintage']}。",
           '僅涵蓋當次認證診斷名單。優先關注股，再按已完成門檻排序；潛在漲幅僅作同順位排序。',
           '同公司原始財報集中蒐集，各項仍須獨立查核；策略證據集中蒐集後仍須核對個股與子群適用性。','',
           f"僅達A+價格門檻的研究候選：{aplus['price_qualified_research_issuers']}；"
           f"其中已封存部分可進一步核閱的原件：{aplus['original_captured_review_pending_issuers']}家、"
           f"{aplus['review_ready_gate_issues']}項待核；其他已取得局部股數或交易資料的項目，仍須補齊法律條款及成交能力。",'',
           f"已有局部來源可繼續核對：{aplus['source_advanced_issuers']}家、"
           f"{aplus['source_advanced_gate_issues']}項（不等於完整原始證據或品質PASS）。",'',
           '## 先核閱已封存原件（價差≥30%研究候選）','',
           '|公司|研究漲幅|已有原件待核項目|下一項實際動作|',
           '|---|---:|---|---|']
    for item in aplus['verification_priority']:
        action=ACTION_ZH.get(item['next_issuer_action'],'已無公司別待辦')
        lines.append(f"|{item['code']} {item.get('name') or ''}|{item['upside_pct']:+.1f}%|"
                     f"{'、'.join(item['review_ready_original_gates']) or '尚無可直接簽核原件'}|"
                     f"{item['next_issuer_gate'] or '策略共同驗證'}：{action}|")
    lines+=['','## 全部診斷公司的待辦（公司別及共同驗證分開）','',
            '|股票|A+價格狀態|正式通過|明確未通過|未結案|下一步|',
            '|---|---|---:|---:|---:|---|']
    for job in report['issuer_jobs']:
        action=ACTION_ZH.get(job['next_issuer_action'],'已無公司別待辦')
        target=job['next_issuer_gate'] or '僅策略共同驗證'
        lines.append(f"|{job['code']} {job.get('name') or ''}|{job['price_lane']}|"
                     f"{job['passed_gate_count']}/13|{len(job['failed_gates'])}|"
                     f"{job['unresolved_gate_count']}|{target}：{action}|")
    lines+=['','## 共同策略阻礙：樣本外驗證','',
            '須重建歷史PIT、完整公司行動與交易成本，並以固定版本做Walk-Forward。'
            '不能把尚未成熟的2027報酬或相同日期的重複樣本視為完成。',
            '每家公司仍須確認該策略／子群適用性；本報告不產生證書、買賣訊號或人工簽核。']
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
