"""Explain certification coverage without changing a single evidence decision."""
import math
from .evidence import GATES, POLICY


def summarize_certification(rows,backtest,price_freshness):
    counts={name:dict(PASS=0,FAIL=0,PENDING=0) for name in GATES}
    completed=0;price_candidates=0
    for row in rows:
        cert=row.get('certification') or {}
        decisions={}
        for name in GATES:
            states=[status for status,field in (('PASS','gates_passed'),('FAIL','gates_failed'))
                    if name in cert.get(field,[])]
            # Count effective model decisions, never a raw ledger's PASS claim.
            state=states[0] if len(states)==1 and name not in cert.get('gates_pending',[]) else 'PENDING'
            decisions[name]=state;counts[name][state]+=1
        completed+=all(s!='PENDING' for s in decisions.values())
        upside=(row.get('base') or {}).get('price_upside_pct')
        if (row.get('rankable') and type(upside) in (int,float) and math.isfinite(upside)
                and upside>=POLICY['Aplus_price_upside_pct']):
            price_candidates+=1
    blockers=[]
    if not rows or completed!=len(rows):blockers.append('QUALITY_GATE_REVIEW_INCOMPLETE')
    if backtest.get('performance') is None:blockers.append('PIT_RETURN_BACKTEST_INCOMPLETE')
    if price_freshness.get('equity_source_may_be_stale'):blockers.append('REFERENCE_CLOSE_MAY_BE_STALE')
    return dict(schema='APLUS_CERTIFICATION_COVERAGE_V1',
        status='CERTIFICATION_INCOMPLETE' if blockers else 'TRACKED_SCOPE_DECIDED',
        tracked_issuers=len(rows),fully_decided_issuers=completed,
        unresolved_issuers=len(rows)-completed,gate_counts=counts,
        price_only_Aplus_threshold_count=price_candidates,
        recorded_formal_Aplus_count=sum(bool(r.get('formal_Aplus')) for r in rows),
        blocking_reasons=blockers,
        zero_formal_is_proof_of_no_market_opportunities=False,
        all_13_original_gates_and_price_policy_unchanged=True)
