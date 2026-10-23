"""Original issuer IR slides: 6206 selected inventory and turnover observations.

Reproducible selected-slide subcheck, not full audited balance-sheet review,
not a positive cash-quality certificate, not a PIT trading signal.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path

SCHEMA='V8B2_6206_ORIGINAL_IR_STOCK_BUILD_NOT_FORMAL_CASH_GATE'
SOURCE_URL='https://www.flytech.com.tw/data/investor_law/attached/1786525880605469429.pdf'
ARCHIVE_PATH='evidence/v880/originals/6206/2026-08-12_0d20ed91a43b95a79f07_523a4595b772a0b9.pdf'
EXPECTED_SHA='523a4595b772a0b98e14a832086848e393ff432658a2ae9d48d36a9a92a5a056'


def check_6206_inventory_original(record,root,asof,history):
    if (record.get('schema')!=SCHEMA or record.get('issuer')!='6206' or
        record.get('market')!='TWSE' or record.get('financial_period')!='2026-Q2' or
        record.get('issuer_original_source_url')!=SOURCE_URL or
        record.get('original_issuer_pdf_path')!=ARCHIVE_PATH or
        record.get('original_issuer_pdf_sha256')!=EXPECTED_SHA or
        record.get('formal_cash_working_capital_gate_pass') is not False or
        record.get('formal_Aplus_addition')!=0 or
        record.get('MOPS_PIT_original_presentation_verified') is not False or
        record.get('full_balance_sheet_notes_reviewed') is not False or
        record.get('inventory_write_down_not_proven') is not True or
        record.get('inventory_days_method_independently_recomputed_from_cogs') is not False):
        raise ValueError('6206_INVENTORY_IR_SOURCE_OR_CERTIFICATION_MISMATCH')
    observed=dt.date.fromisoformat(record['first_issuer_slide_reviewed_date'])
    published=dt.date.fromisoformat(record['issuer_presentation_date'])
    cutoff=dt.date.fromisoformat(asof[:10])
    if observed>cutoff or published>observed or published>cutoff:
        raise ValueError('6206_IR_OBSERVATION_IS_FROM_FUTURE')
    root=Path(root).resolve()
    source=(root/ARCHIVE_PATH).resolve()
    if not source.is_relative_to(root) or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=EXPECTED_SHA:
        raise ValueError('6206_ORIGINAL_IR_PDF_BYTES_MISSING_OR_SHA_MISMATCH')
    rows=record.get('quarterly_balance_and_turnover') or {}
    revenue=record.get('q2_single_revenue_m') or {}
    for period in ('q2_2026','q1_2026','q2_2025'):
        values=rows.get(period) or {}
        for key in ('accounts_receivable_m','inventory_m','accounts_payable_m',
                    'days_receivable','days_inventory'):
            x=values.get(key)
            if type(x) is not int or x<=0 or x>100000:
                raise ValueError('6206_IR_INVALID_ROUNDED_BALANCE_OR_DAYS')
        if type(revenue.get(period)) is not int or not 0<revenue[period]<100000:
            raise ValueError('6206_IR_INVALID_Q_REVENUE')
    # Match the official exchange MOPS standardized *year-to-date* income
    # to the issuer's single-quarter revenue (rounded to NTD millions).
    def income(period):
        v=history.get(period) or {}
        if (v.get('code')!='6206' or v.get('market')!='TWSE' or
            v.get('period')!=period or type(v.get('revenue_ytd_k')) is not int):
            raise ValueError('6206_IR_OFFICIAL_INCOME_MIRROR_UNAVAILABLE:'+
                repr(dict(period=period,code=v.get('code'),market=v.get('market'),
                          row_period=v.get('period'),revenue_type=type(v.get('revenue_ytd_k')).__name__)))
        return v['revenue_ytd_k']
    official=dict(
        q1_2026=income('2026-Q1'),
        q2_2026=income('2026-Q2')-income('2026-Q1'),
        q2_2025=income('2025-Q2')-income('2025-Q1'))
    for period,value in official.items():
        if abs(value/1000-revenue[period])>.5:
            raise ValueError('6206_IR_PUBLISHED_REVENUE_AND_MOPS_MIRROR_CONFLICT_'+period)
    q2=rows['q2_2026'];q1=rows['q1_2026'];prior=rows['q2_2025']
    inventory_yoy_pct=100*(q2['inventory_m']/prior['inventory_m']-1)
    sales_yoy_pct=100*(official['q2_2026']/official['q2_2025']-1)
    receivables_yoy_pct=100*(q2['accounts_receivable_m']/prior['accounts_receivable_m']-1)
    return dict(code='6206',period='2026-Q2',
        status='SHA_CHECKED_ISSUER_IR_ROUNDED_BALANCE_AND_MOPS_REVENUE_CROSSCHECKED',
        original_presentation_sha256=EXPECTED_SHA,
        original_presentation_archive_path=ARCHIVE_PATH,
        first_review_date=record['first_issuer_slide_reviewed_date'],
        original_pdf_page=record['original_pdf_slide_number_1indexed']['consolidated_balance_sheet_and_turnover'],
        inventory_q2_2026_m=q2['inventory_m'],
        inventory_q2_2025_m=prior['inventory_m'],
        inventory_q1_2026_m=q1['inventory_m'],
        inventory_yoy_pct=inventory_yoy_pct,
        q2_revenue_yoy_pct=sales_yoy_pct,
        inventory_yoy_minus_revenue_yoy_pp=inventory_yoy_pct-sales_yoy_pct,
        receivables_yoy_pct=receivables_yoy_pct,
        inventory_days_q2_2026=q2['days_inventory'],
        inventory_days_q2_2025=prior['days_inventory'],
        inventory_days_q1_2026=q1['days_inventory'],
        inventory_days_yoy_delta=q2['days_inventory']-prior['days_inventory'],
        inventory_days_qoq_delta=q2['days_inventory']-q1['days_inventory'],
        receivable_days_yoy_delta=q2['days_receivable']-prior['days_receivable'],
        inventory_growth_exceeds_revenue_by_30pp=(inventory_yoy_pct-sales_yoy_pct>=30),
        MOPS_PIT_original_presentation_verified=False,
        original_inventory_valuation_notes_fully_checked=False,
        inventory_days_method_independently_recomputed=False,
        inventory_impairment_or_obsolescence_inferred=False,
        cash_quality_gate_pass=False,formal_Aplus_addition=0)


def load_6206_inventory_watch(root,asof,history):
    root=Path(root)
    results={};errors=[]
    for path in sorted((root/'evidence/v880/inventory_original_watch').glob('*.json')):
        try:
            document=json.loads(path.read_text(encoding='utf-8'))
            if path.stem!='6206' or document.get('issuer')!=path.stem:
                raise ValueError('6206_INVENTORY_WATCH_UNKNOWN_ISSUER')
            if document['first_issuer_slide_reviewed_date']>asof[:10]:
                continue
            rows=history.get(('TWSE','6206')) or {}
            results['6206']=check_6206_inventory_original(document,root,asof,rows)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            errors.append(dict(source=str(path.relative_to(root)),error=str(exc)))
    return results,errors
