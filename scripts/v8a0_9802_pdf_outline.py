#!/usr/bin/env python3
"""Native text preflight for the eight 9802 archived issuer reports.

This is source *inspection*, not a substantive audit opinion or the named
reviewer attestation necessary for any of the formal 13 quality gates.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from scripts.v896_original_archive import (
    original_quarter_coverage, read_original_archive, validate_bundle
)

SCHEMA="V8A0_9802_PDF_TEXT_OUTLINE_NOT_FORMAL_REVIEW"
COMPANY_MARKERS=("鈺齊", "fulgentsun", "fulgentsuninternational", "9802")
SECTIONS={
    "financial_position":(
        "合併資產負債表","consolidatedbalancesheets",
        "consolidatedstatementsoffinancialposition",
        "consolidatedstatementoffinancialposition"),
    "profit_and_comprehensive_income":(
        "合併綜合損益表","合併損益表",
        "consolidatedstatementsofcomprehensiveincome",
        "consolidatedstatementofcomprehensiveincome"),
    "equity_changes":(
        "合併權益變動表","consolidatedstatementsofchangesinequity",
        "consolidatedstatementofchangesinequity"),
    "cash_flows":(
        "合併現金流量表","consolidatedstatementsofcashflows",
        "consolidatedstatementofcashflows"),
    "footnotes":("財務報告附註","合併財務報告附註","notes to consolidated financial statements".replace(" ",""),
                 "notestotheconsolidatedfinancialstatements"),
    "auditor_report_text":(
        "會計師核閱報告","會計師查核報告",
        "independentauditorsreviewreport","independentauditorreviewreport",
        "independentauditorsreport","independentauditorreport",
        "independentauditorsauditreport","independentauditorauditreport")
}

def compact(value):
    # Official reports use singular and plural auditor headings, with
    # ASCII and curly apostrophes. Remove only typography, not financial data.
    return re.sub(r"[\s'’‘ʼ]+","",unicodedata.normalize("NFKC",str(value))).lower()

def period_of_title(title):
    # A self-reported earnings *press release* is not an eight-quarter
    # consolidated financial report, even if its title includes a quarter.
    title=str(title)
    if "合併財務報告" not in title and not re.search(
            r"Consolidated\s+Financial\s+Statements",title,re.I):
        return None
    zh=re.search(r"(20\d{2})年(第一|第二|第三|第四)季",title)
    if zh:
        q={"第一":1,"第二":2,"第三":3,"第四":4}[zh[2]]
        return f"{zh[1]}-Q{q}"
    en=re.search(r"(20\d{2})\s+Q([1-4])\s+Consolidated\s+Financial\s+Statements",
                 str(title),re.I)
    if en:return f"{en[1]}-Q{en[2]}"
    return None

def period_tokens(period):
    year,quarter=period.split("-Q")
    year=int(year);quarter=int(quarter)
    day={1:31,2:30,3:30,4:31}[quarter]
    month=quarter*3
    month_name={3:"march",6:"june",9:"september",12:"december"}[month]
    roc=year-1911
    return (
        f"{year}年{month}月{day}日",
        f"{roc}年{month}月{day}日",
        f"{year}/{month:02d}/{day:02d}",
        f"{year}.{month:02d}.{day:02d}",
        f"{month_name}{day},{year}",
        f"{month_name}{day}{year}",
    )

def inspect_native_text(pages,period):
    """Page-keyword observations only; no financial number is claimed."""
    if not isinstance(pages,list) or len(pages)>250 or not pages:
        raise ValueError("PDF_PAGE_COUNT_OUT_OF_RANGE")
    normalized=[compact(page) for page in pages]
    first12="".join(normalized[:12])
    chars=sum(len(x) for x in normalized)
    if chars>1_800_000:
        raise ValueError("PDF_TEXT_EXTRACTION_OVERSIZE")
    company_hits=[token for token in COMPANY_MARKERS if compact(token) in first12]
    date_hits=[token for token in period_tokens(period)
               if compact(token) in first12]
    section_pages={}
    for field,terms in SECTIONS.items():
        hits=[i+1 for i,page in enumerate(normalized)
              if any(compact(term) in page for term in terms)]
        section_pages[field]=hits[:8]
    missing=[name for name,hits in section_pages.items() if not hits]
    has_text=chars>=500
    status=("NATIVE_TEXT_SECTION_MARKERS_FOUND_NOT_CERTIFIED" if
            has_text and company_hits and date_hits and not missing
            else "NATIVE_TEXT_GAPS_REQUIRE_VISUAL_OR_DOCUMENT_REVIEW")
    return dict(page_count=len(pages),native_extracted_characters=chars,
                issuer_tokens_observed_on_first_12_pages=company_hits,
                accounting_period_date_tokens_on_first_12_pages=date_hits,
                section_page_keyword_hits=section_pages,
                missing_native_text_section_markers=missing,
                issuer_identity_and_period_text_hints=bool(company_hits and date_hits),
                preflight_status=status,
                pdf_internal_financial_number_reconciliation_completed=False,
                accounting_period_in_full_PDF_independently_attested=False,
                auditors_opinion_and_materiality_independently_reviewed=False,
                financial_notes_substantive_review_completed=False,
                source_issuer_filing_PIT_verified=False,
                formal_original_eight_quarter_gate_pass=False)

def pdf_page_text(original):
    """Read issuer-hosted PDF bytes already hashed by original archive."""
    import pymupdf
    doc=pymupdf.open(original)
    if doc.needs_pass or not 1<=doc.page_count<=250:
        raise ValueError("ENCRYPTED_OR_INVALID_PAGE_COUNT")
    try:
        return [page.get_text("text",sort=True) for page in doc]
    finally:
        doc.close()

def audit(root,reader=pdf_page_text):
    root=Path(root).resolve()
    verified=validate_bundle(root,"9802")
    coverage=original_quarter_coverage(root,"9802","2026-Q2")
    records=read_original_archive(root,"9802")["documents"]
    needed=set(coverage["required_quarters"])
    reports={}
    missing=[]
    for doc in records:
        if doc["document_kind"]!="quarterly":
            continue
        period=period_of_title(doc.get("title",""))
        if period not in needed:
            continue
        archive=root/doc["archive_path"]
        if period in reports:
            raise ValueError("AMBIGUOUS_DUPLICATED_PERIOD_ORIGINAL_"+period)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=doc["sha256"]:
            raise ValueError("ORIGINAL_BYTES_CHANGED_"+period)
        try:
            precheck=inspect_native_text(reader(archive),period)
            error=None
        except (ValueError,ImportError,RuntimeError,OSError) as exc:
            precheck=dict(preflight_status="NATIVE_TEXT_EXTRACTOR_FAILURE_REVIEW_REQUIRED",
                          error=type(exc).__name__+":"+str(exc)[:220],
                          formal_original_eight_quarter_gate_pass=False)
            error=precheck["error"]
        reports[period]=dict(issuer="9802",accounting_period=period,
             source_publisher_title=doc["title"],
             issuer_display_date=doc["document_date"],
             first_source_capture_utc=doc["captured_at_utc"],
             source_url=doc["source_url"],
             original_pdf_sha256=doc["sha256"],
             archived_original=doc["archive_path"],
             publisher_english_translation=doc.get("english_translation_of_chinese_original") is True,
             translation_supremacy_reconciled=False if
               doc.get("english_translation_of_chinese_original") else None,
             extraction_failure=error,**precheck)
    missing=[p for p in coverage["required_quarters"] if p not in reports]
    if missing != coverage["missing_quarters"]:
        raise ValueError("PDF_PRECHECK_AND_ORIGINAL_COVERAGE_DISAGREE")
    result=dict(schema=SCHEMA,issuer="9802",financial_last_quarter="2026-Q2",
       period=coverage["required_quarters"],reported_quarters=reports,
       quarterly_source_records_rechecked=verified["document_kinds"]["quarterly"],
       required_periods_with_original_sources=len(reports),
       required_periods_without_original_sources=missing,
       source_url_and_pdf_sha256_verified=True,
       website_dates_do_not_prove_independent_MOPS_filing_PIT=True,
       original_audited_opinions_substantively_reviewed=False,
       all_eight_originals_have_formal_content_signoff=False,
       no_2027_EPS_PE_or_Base_override=True,formal_13_gate_pass_count_increment=0,
       formal_Aplus_unchanged=True,
       note=("Only native selectable PDF text and locations of selected section keywords "
             "were checked. Does NOT independently authenticate the document contents, "
             "auditor scope, four-statement numeric reconciliations or initial MOPS filing PIT."))
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-root",default="tw-market-data")
    ap.add_argument("--output",default="tw-market-data/evidence/v880/originals/9802/content_outline.json")
    args=ap.parse_args()
    report=audit(args.data_root)
    dest=Path(args.output);dest.parent.mkdir(parents=True,exist_ok=True)
    serialized=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    if not dest.exists() or dest.read_text(encoding="utf-8")!=serialized:
        dest.write_text(serialized,encoding="utf-8")
    print(json.dumps(dict(issuer="9802",source_quarters=report["required_periods_with_original_sources"],
           missing=report["required_periods_without_original_sources"],
           extracted_preflight_passes=sum(
               x.get("preflight_status")=="NATIVE_TEXT_SECTION_MARKERS_FOUND_NOT_CERTIFIED"
               for x in report["reported_quarters"].values()),
           formal_gate_passes=0),ensure_ascii=False))

if __name__=="__main__":
    main()
