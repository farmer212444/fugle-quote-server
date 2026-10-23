"""Partial but reproducible 8383 original-note working-capital reconciliation.

No evidence receipt may issue an issuer cash quality PASS. This only validates
line-item arithmetic against original, immutable PDF SHA and dated MOPS mirrors.
"""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from .evidence import timestamp

SCHEMA='V8B0_8383_ORIGINAL_WORKING_CAPITAL_SUBCHECK_NOT_FORMAL_GATE'
PUBLISHER='https://www.chenfull.com.tw/filestore/pdf/115/115Q2%E8%B2%A1%E5%A0%B1%28Final%E7%94%A8%E5%8D%B0%29-0814.pdf'


def _delta(record):
    return record['current_k']-record['prior_fy_close_k']


def check_working_capital_receipt(record,root,asof,income,cash):
    root=Path(root).resolve()
    if (record.get('schema')!=SCHEMA or record.get('issuer')!='8383'
        or record.get('market')!='TPEX' or record.get('period')!='2026-Q2'
        or record.get('original_issuer_source_url')!=PUBLISHER
        or record.get('formal_cash_and_working_capital_gate_pass') is not False
        or record.get('formal_auditor_scope_gate_pass') is not False
        or record.get('formal_Aplus_addition')!=0
        or record.get('issuer_historical_filings_PIT_verified') is not False
        or record.get('full_financial_statements_and_notes_reviewed') is not False):
        raise ValueError('8383_WC_RECEIPT_FALSE_SCOPE_OR_CERTIFICATION')
    date=dt.date.fromisoformat(record['independently_read_date'])
    release=dt.date.fromisoformat(record['report_dated'])
    cutoff=dt.date.fromisoformat(asof[:10])
    if date>cutoff or release>date:
        raise ValueError('8383_WC_READ_DATE_NOT_VISIBLE_IN_TARGET_VINTAGE')
    digest=record.get('original_issuer_pdf_sha256')
    if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
        raise ValueError('8383_WC_SOURCE_HASH_INVALID')
    expected=f'evidence/v880/originals/8383/2026-Q2_{digest[:20]}.pdf'
    if record.get('issuer_original_archived_pdf')!=expected:
        raise ValueError('8383_WC_ORIGINAL_PATH_CONFLICT')
    archived=root/expected
    if not archived.is_file() or hashlib.sha256(archived.read_bytes()).hexdigest()!=digest:
        raise ValueError('8383_WC_ORIGINAL_PDF_MISSING_OR_SHA_CONFLICT')
    if not (income.get('code')=='8383' and income.get('market')=='TPEX'
        and income.get('period')=='2026-Q2' and
        cash.get('code')=='8383' and cash.get('market')=='TPEX'
        and cash.get('period')=='2026-Q2'):
        raise ValueError('8383_WC_CROSS_SOURCE_ISSUER_PERIOD_NOT_IDENTICAL')
    for k,actual in (('consolidated_revenue_h1_k',income.get('revenue_ytd_k')),
                     ('cashflow_operating_ytd_k',cash.get('operating_cashflow_ytd_k'))):
        if type(record.get(k)) is not int or record[k]!=actual:
            raise ValueError('8383_WC_ORIGINAL_VS_OFFICIAL_MIRROR_CONFLICT_'+k)
    contract=record['contract_assets_construction']
    ar=record['accounts_receivable_contract_note']
    ap=record['accounts_payable_balance_sheet']
    liab=record['contract_liabilities_total']
    for data in (contract,ar,ap,liab):
        if any(type(v) is not int or v<0 for k,v in data.items()
               if k in ('current_k','prior_fy_close_k')):
            raise ValueError('8383_WC_INVALID_ACCOUNT_BALANCE')
    for data in (contract,ar,ap):
        if type(data.get('operating_cashflow_movement_signed_k')) is not int:
            raise ValueError('8383_WC_INVALID_SIGNED_CASHFLOW')
    ecl=record['expected_credit_loss_addback_ytd_k']
    if type(ecl) is not int or ecl<0:
        raise ValueError('8383_WC_INVALID_ECL')
    # The report's 2026H1 working capital statement and contract-revenue notes:
    # unbilled contract assets increase 370707 and consume cash.
    if _delta(contract)!=-contract['operating_cashflow_movement_signed_k']:
        raise ValueError('8383_WC_CONTRACT_ASSET_MISMATCH')
    # AR movement uses gross receivables; net AR delta differs by ECL addback.
    if _delta(ar)+ecl!=-ar['operating_cashflow_movement_signed_k']:
        raise ValueError('8383_WC_AR_MOVEMENT_NOT_RECONCILED_WITH_ECL')
    if _delta(ap)!=ap['operating_cashflow_movement_signed_k']:
        raise ValueError('8383_WC_ACCOUNTS_PAYABLE_MISMATCH')
    if (record.get('cashflow_generated_from_operations_ytd_k')!=159229
        or record.get('cashflow_tax_paid_ytd_k')!=-51358
        or record['cashflow_operating_ytd_k']!=109120):
        raise ValueError('8383_WC_SOURCE_LINE_ITEMS_NOT_RECONCILED')
    net_current=contract['current_k']+ar['current_k']-liab['current_k']
    net_prev=contract['prior_fy_close_k']+ar['prior_fy_close_k']-liab['prior_fy_close_k']
    return dict(code='8383',period='2026-Q2',
        status='ORIGINAL_Q2_NOTE_SELECTED_LINE_ITEMS_RECONCILED_NOT_FULL_CASH_GATE',
        source_sha256=digest,issuer_original_verified_pdf_path=expected,
        contract_assets_current_k=contract['current_k'],
        contract_assets_2025_year_end_k=contract['prior_fy_close_k'],
        contract_assets_increase_k=_delta(contract),
        receivables_net_current_k=ar['current_k'],
        receivables_net_2025_year_end_k=ar['prior_fy_close_k'],
        receivables_net_increase_k=_delta(ar),
        ar_ecl_addback_k=ecl,
        accounts_payable_increase_k=_delta(ap),
        contract_liabilities_current_k=liab['current_k'],
        net_contract_assets_plus_ar_less_contract_liabilities_current_k=net_current,
        net_contract_assets_plus_ar_less_contract_liabilities_change_k=net_current-net_prev,
        engineering_revenue_h1_k=record['engineering_revenue_h1_k'],
        consolidated_revenue_h1_k=record['consolidated_revenue_h1_k'],
        cashflow_operating_h1_k=record['cashflow_operating_ytd_k'],
        original_source_pages=record['original_pages_1indexed'],
        three_working_capital_account_movements_reconciled=True,
        incomplete_working_capital_line_items_outstanding=True,
        subsidiary_scope_review_outstanding=True,
        MOPS_historical_publication_PIT_verified=False,
        formal_cash_and_working_capital_gate_pass=False,
        formal_auditor_scope_gate_pass=False,formal_Aplus_addition=0,
        date_original_source_directly_read=record['independently_read_date'])


def load_working_capital_watch(root,asof,history,cash):
    root=Path(root);results={};errors=[]
    folder=root/'evidence/v880/working_capital_watch'
    for path in sorted(folder.glob('*.json')):
        try:
            rec=json.loads(path.read_text(encoding='utf-8'))
            if path.stem!=rec['issuer']:
                raise ValueError('8383_WC_RECEIPT_WRONG_FILENAME')
            checked_asof=asof
            if rec['issuer']=='9802':
                # Legacy callers pass a date; use start-of-day Taipei rather
                # than admitting a later same-day review without a clock.
                if len(asof)==10:checked_asof=asof+'T00:00:00+08:00'
                if timestamp(rec['reviewed_at'])>timestamp(checked_asof):continue
            elif rec['independently_read_date']>asof[:10]:
                continue  # future observation not available at historical asof
            key=(rec['market'],rec['issuer']);period=rec['period']
            checker=check_working_capital_receipt
            if rec['issuer']=='9802':
                from .cash_review_9802 import check_9802_cash_review
                checker=check_9802_cash_review
            result=checker(
                rec,root,checked_asof,(history.get(key) or {}).get(period) or {},
                (cash.get(key) or {}).get(period) or {})
            results[rec['issuer']]=result
        except (OSError,ValueError,KeyError,TypeError,RuntimeError,ImportError) as exc:
            errors.append(dict(source=str(path.relative_to(root)),error=str(exc)))
    return results,errors
