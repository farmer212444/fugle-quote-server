"""Document clocks for verified MOPS originals; never a full-model PIT certificate.

Call with the versions returned by scripts.mops_filing_archive.audit_archive.
Reconstruction candidates remain distinct from documents actually archived before
a signal. The current index's 'no correction' indicator is not a complete audit of
all historical versions and cannot promote a model or supply missing numerics.
"""
import datetime as dt
from collections import defaultdict

from .evidence import timestamp


def filing_view(versions,asof,*,mode='observed_archive',lag_hours=24):
    if mode not in ('observed_archive','official_upload_reconstruction'):
        raise ValueError('UNKNOWN_FILING_CLOCK_MODE')
    if type(lag_hours) is not int or lag_hours<0:
        raise ValueError('INVALID_FILING_AVAILABILITY_LAG')
    cutoff=timestamp(asof);groups=defaultdict(list);conflicts=defaultdict(set)
    for version in versions:
        row=version['index_row'];published=timestamp(row['official_upload_at'])
        captured=timestamp(version['captured_at_utc'])
        if captured<published:raise ValueError('FILING_CAPTURE_PRECEDES_OFFICIAL_UPLOAD')
        observed=mode=='observed_archive'
        available=(max(published,captured) if observed else published)+dt.timedelta(hours=lag_hours)
        if available>cutoff:continue
        code,period=row['code'],row['financial_period']
        item=dict(code=code,financial_period=period,official_upload_at=published.isoformat(),
            original_capture_at=captured.isoformat(),available_after=available.isoformat(),
            receipt=version['reference'],pdf_original=version['pdf_original'],
            latest_reported_correction=row['latest_reported_correction'],
            mode=mode,reconstruction_candidate_only=not observed,formal_gate_pass=False,
            numerical_facts_reconciled=False)
        groups[(code,period)].append(item)
        conflicts[(code,period,published.isoformat())].add(version['pdf_original']['sha256'])
    selected=[];rejected=[]
    for (code,period),items in sorted(groups.items()):
        # Never substitute an older apparently clean file when the latest
        # eligible observation reports a correction or has conflicting bytes.
        latest=max(items,key=lambda r:(timestamp(r['official_upload_at']),timestamp(r['original_capture_at'])))
        key=(code,period,latest['official_upload_at'])
        reason=('AMBIGUOUS_BYTES_FOR_SAME_OFFICIAL_UPLOAD' if len(conflicts[key])>1 else
                'AMENDED_FILING_REQUIRES_EXACT_REVISION_HISTORY' if latest['latest_reported_correction']!='無' else None)
        if reason:rejected.append(dict(code=code,financial_period=period,reason=reason));continue
        # Byte-identical observations keep the first actual archive clock.
        same=[r for r in items if r['official_upload_at']==latest['official_upload_at']
              and r['pdf_original']['sha256']==latest['pdf_original']['sha256']]
        selected.append(min(same,key=lambda r:timestamp(r['original_capture_at'])))
    return dict(asof=asof,mode=mode,availability_lag_hours=lag_hours,
        documents=selected,rejected_versions=rejected,
        historically_frozen_model=False,
        complete_historical_revision_chains_reviewed=False,
        full_model_input_PIT_complete=False,stock_return_backtest_completed=False,
        formal_out_of_sample_pass=False)


def coverage_at(versions,asof,codes,*,mode='official_upload_reconstruction',lag_hours=24,count=8):
    view=filing_view(versions,asof,mode=mode,lag_hours=lag_hours)
    coverage=[]
    for code in codes:
        docs=[r for r in view['documents'] if r['code']==code]
        periods={r['financial_period'] for r in docs}
        if periods:
            last=max(periods);year,quarter=map(int,last.split('-Q'));end=year*4+quarter-1
            required=[f'{i//4}-Q{i%4+1}' for i in range(end-count+1,end+1)]
        else:required=[]
        coverage.append(dict(code=code,last_available_period=max(periods) if periods else None,
            available_periods=sorted(periods),required_periods=required,
            missing_required_periods=[p for p in required if p not in periods],
            eight_quarter_document_clock_coverage=bool(required) and all(p in periods for p in required),
            formal_original_statement_gate_pass=False))
    return dict(**view,issuer_coverage=coverage)
