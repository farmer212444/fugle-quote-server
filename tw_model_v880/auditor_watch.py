"""Bounded issuer-review qualification receipts, not human approval.

An issuer-hosted PDF's visually checked pages establish a documented
observation. Without original bytes + hash, full subsidiary source review
and filing PIT, this MUST NOT be represented as an audited certificate.
"""
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlsplit

VALID_SCHEMA='DATED_ISSUER_PDF_SCOPE_WATCH_V1'
ALLOWED_HOSTS={'8383':{'www.chenfull.com.tw','chenfull.com.tw'}}


def check_scope_receipt(record, income, cash, asof):
    if (record.get('schema')!=VALID_SCHEMA or
        record.get('issuer') not in ALLOWED_HOSTS or
        record.get('market')!='TPEX' or record.get('period')!='2026-Q2' or
        record.get('review_conclusion')!='QUALIFIED_CONCLUSION_DUE_TO_SUBSIDIARIES_NOT_REVIEWED_BY_AUDITOR'):
        raise ValueError('INVALID_SCOPE_RECEIPT_IDENTITY_OR_REVIEW_CONCLUSION')
    u=urlsplit(record.get('source_pdf_url',''))
    if u.scheme!='https' or u.hostname not in ALLOWED_HOSTS[record['issuer']] or not u.path.lower().endswith('.pdf'):
        raise ValueError('SCOPE_WATCH_UNVERIFIED_PUBLISHER_HOST')
    if (record.get('original_MOPS_filing_PIT_verified') is not False or
        record.get('pdf_bytes_sha256_saved_and_revalidated') is not False or
        record.get('formal_auditor_scope_gate_pass') is not False or
        record.get('formal_gate_added')!=0 or
        record.get('all_consolidated_notes_fully_reviewed') is not False):
        raise ValueError('SCOPE_WATCH_FALSE_ORIGIN_OR_CERTIFICATION')
    observed=dt.date.fromisoformat(record['first_directly_inspected_on'])
    cutoff=dt.date.fromisoformat(asof[:10])
    report_day=dt.date.fromisoformat(record['document_dated'])
    if observed>cutoff or report_day>observed or report_day>cutoff:
        raise ValueError('SCOPE_WATCH_FUTURE_DATA')
    fields=record.get('issuer_pdf_mirror_observations_ntd_thousands',{})
    if (income.get('code')!=record['issuer'] or cash.get('code')!=record['issuer'] or
        income.get('period')!=record['period'] or cash.get('period')!=record['period'] or
        income.get('market')!=record['market'] or cash.get('market')!=record['market']):
        raise ValueError('SCOPE_WATCH_MIRROR_DIFFERENT_ISSUER_OR_PERIOD')
    expected={'revenue_ytd_k':income.get('revenue_ytd_k'),
              'gross_profit_ytd_k':income.get('gross_profit_ytd_k'),
              'operating_profit_ytd_k':income.get('operating_profit_ytd_k'),
              'operating_cashflow_ytd_k':cash.get('operating_cashflow_ytd_k')}
    if any(type(fields.get(k)) is not int or fields[k]!=v for k,v in expected.items()):
        raise ValueError('SCOPE_WATCH_ORIGINAL_VS_NORMALIZED_MIRROR_MISMATCH')
    scope=record.get('quantitative_scope_reported_pct') or {}
    for k in ('assets_at_2026_06_30','liabilities_at_2026_06_30',
              'quarterly_consolidated_comprehensive_income',
              'half_year_consolidated_comprehensive_income'):
        if type(scope.get(k)) not in (float,int) or not 0<=scope[k]<=100:
            raise ValueError('SCOPE_WATCH_INVALID_SCOPE_PERCENT')
    previous=record.get('prior_interim_review_observation') or {}
    if previous:
        earlier_url=urlsplit(previous.get('issuer_original_source_url',''))
        if (previous.get('period')!='2026-Q1' or
            previous.get('review_conclusion')!=record['review_conclusion'] or
            earlier_url.scheme!='https' or earlier_url.hostname not in ALLOWED_HOSTS[record['issuer']] or
            not earlier_url.path.lower().endswith('.pdf') or
            previous.get('original_pdf_bytes_hashed') is not False or
            previous.get('MOPS_PIT_verified') is not False or
            previous.get('review_notes_fully_reconciled') is not False):
            raise ValueError('SCOPE_WATCH_PRIOR_Q1_ORIGINAL_SOURCE_INVALID')
        if not (dt.date.fromisoformat(previous['document_dated'])<=
                dt.date.fromisoformat(previous['first_directly_inspected_on'])<=cutoff):
            raise ValueError('SCOPE_WATCH_PRIOR_Q1_FUTURE_SOURCE')
        for field in ('subsidiaries_unreviewed_share_of_total_assets_pct',
                      'subsidiaries_unreviewed_share_of_total_comprehensive_income_pct'):
            v=previous.get(field)
            if type(v) not in (int,float) or v<0 or v>100:
                raise ValueError('SCOPE_WATCH_PRIOR_Q1_MALFORMED_SCOPE')
    if not (record.get('original_url_link_checked') and
            record.get('publication_label_is_not_PIT_timestamp') is True):
        raise ValueError('SCOPE_WATCH_MISSING_URL_OR_PIT_CAVEAT')
    return dict(code=record['issuer'],market=record['market'],period=record['period'],
        status='ISSUER_ORIGINAL_QUALIFIED_REVIEW_SCOPE_DOC_VISUALLY_CHECKED_NO_FORMAL_PASS',
        conclusion=record['review_conclusion'],
        qualified_scope_pct=scope,
        source_pdf_url=record['source_pdf_url'],
        source_index_url=record['source_index_url'],
        preceding_q1_review=dict(previous) if previous else None,
        document_dated=record['document_dated'],
        first_directly_inspected_on=record['first_directly_inspected_on'],
        matched_official_normalized_mirror_fields=sorted(expected),
        issuer_original_pdf_bytes_hashed=False,
        notes_and_subsidiary_scope_fully_reconciled=False,
        MOPS_PIT_verified=False,formal_auditor_scope_pass=False,
        latest_source_scope_not_a_fraud_or_material_misstatement_finding=True)


def load_scope_watches(root,asof,history,cash):
    root=Path(root)
    out={};errors=[]
    for path in sorted((root/'evidence/v880/auditor_scope_watch').glob('*.json')):
        try:
            obj=json.loads(path.read_text(encoding='utf-8'))
            code=obj['issuer']
            if code!=path.stem or code in out:
                raise ValueError('SCOPE_WATCH_INVALID_FILENAME_OR_DUPLICATE')
            key=(obj['market'],code);period=obj['period']
            result=check_scope_receipt(obj,(history.get(key) or {}).get(period) or {},
                                        (cash.get(key) or {}).get(period) or {},asof)
            out[code]=result
        except (ValueError,KeyError,TypeError,OSError) as exc:
            errors.append(dict(source=str(path.relative_to(root)),error=str(exc)))
    return out,errors
