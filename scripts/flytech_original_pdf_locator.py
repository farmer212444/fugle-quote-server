#!/usr/bin/env python3
"""Auditable page-level *locator* for 6206 original PDFs, not a signed audit.

It reproduces issuer, quarter, page count and SHA256 original bytes; the PDF
search results are page leads for a reviewer, not evidence that any accounting
value, auditor conclusion or PIT publication clock has been certified.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from scripts.run_research_pipeline import atomic_json

SCHEMA="V8108_FLYTECH_FULL_ORIGINAL_PAGE_LOCATOR_V1"
MANIFEST="evidence/v880/originals/6206/full_statements/manifest.json"
PERIODS=["2024-Q3","2024-Q4","2025-Q1","2025-Q2",
         "2025-Q3","2025-Q4","2026-Q1","2026-Q2"]
HEADINGS={
 "accountant_report":["會計師核閱報告","會計師查核報告","核閱結論","查核意見"],
 "balance_sheet":["合併資產負債表"],
 "comprehensive_income":["合併綜合損益表","合併損益表"],
 "equity_changes":["合併權益變動表"],
 "cashflow_statement":["合併現金流量表"],
 "financial_notes":["合併財務報表附註","合併財務報告附註","財務報表附註"],
 "inventories":["存貨","存貨跌價","存貨及"],
 "trade_receivables":["應收帳款","應收票據"],
 "trade_payables":["應付帳款","應付票據"],
 "capital_expenditure":["取得不動產","購置不動產","購建不動產","不動產廠房及設備"],
 "operating_cashflow":["營業活動之淨現金","營業活動淨現金流","營業活動之現金流量"],
}

def require(ok,reason):
    if not ok:
        raise ValueError("FLYTECH_PDF_LOCATOR_"+reason)

def normalize(text):
    return re.sub(r"\s+","",unicodedata.normalize("NFKC",text or ""))

def locate(pages):
    """Return 1-indexed actual PDF page numbers, never printed-page guesses."""
    result={key:[] for key in HEADINGS}
    for page_number, raw in enumerate(pages,1):
        clean=normalize(raw)
        for key,needles in HEADINGS.items():
            if any(normalize(word) in clean for word in needles):
                result[key].append(page_number)
    return result

def document_pages(raw):
    import fitz
    with fitz.open(stream=raw,filetype="pdf") as pdf:
        require(20<=len(pdf)<=400,"DOCUMENT_LENGTH_INVALID")
        return [page.get_text("text") for page in pdf]

def inspect(root, read_pdf=document_pages):
    root=Path(root).resolve()
    mf=root/MANIFEST
    raw_manifest=mf.read_bytes()
    doc=json.loads(raw_manifest)
    require(doc.get("schema")=="V8108_6206_QUARTERLY_FULL_ORIGINALS_V1" and
            doc.get("issuer")=="6206","MANIFEST_WRONG_COMPANY")
    files=doc.get("documents")
    require(isinstance(files,list) and len(files)==8,"EIGHT_DOCUMENTS_REQUIRED")
    periods=[x.get("period") for x in files]
    require(sorted(periods)==sorted(PERIODS),"QUARTERS_MISSING_OR_DUPLICATE")
    records=[]
    for rec in sorted(files,key=lambda o:o["period"]):
        period=rec["period"]
        rel=Path(rec["archive_path"])
        target=(root/rel).resolve()
        require(not rel.is_absolute() and ".." not in rel.parts and
                root in target.parents and str(rel).startswith(
                    "evidence/v880/originals/6206/full_statements/"+period+"/"),
                "ORIGINAL_PATH_UNSAFE_OR_MISLABELED")
        pdf=target.read_bytes()
        actual=hashlib.sha256(pdf).hexdigest()
        require(actual==rec.get("sha256") and len(pdf)==rec.get("bytes"),
                "ORIGINAL_PDF_SHA_OR_LENGTH_MISMATCH")
        require(rec.get("first_publication_timestamp_verified") is False
                and rec.get("original_full_notes_reviewed") is False
                and rec.get("formal_gate_pass") is False,
                "UNSUPPORTED_FORMAL_CERTIFICATION")
        pages=read_pdf(pdf)
        pagecount=len(pages)
        require(pagecount==rec.get("pdf_identity",{}).get("page_count"),
                "PAGE_COUNT_MANIFEST_MISMATCH")
        hit=locate(pages)
        readable=sum(len(normalize(page))>=60 for page in pages)
        records.append(dict(
            period=period,archive_path=rec["archive_path"],
            original_sha256=actual,
            origin_url=rec["source_url"],
            document_pdf_page_count=pagecount,
            text_extractable_pages=readable,
            index_status="SEARCH_LEADS_ONLY_NOT_VALUE_OR_OPINION_VALIDATION",
            page_locator=hit,
            page_index_base=1,
            accountant_report_interpretation_verified=False,
            inventory_amount_or_allowance_verified=False,
            working_capital_and_ocf_reconciled=False,
            cashflow_statement_values_verified=False,
            full_financial_notes_reviewed=False,
            first_publication_PIT_verified=False,
            gate_PASS_added=0,
            unreadable_or_unindexed_pages_require_manual_visual_review=readable<pagecount))
    return dict(schema=SCHEMA,issuer="6206",asof_financial_period="2026-Q2",
         target_quarters=PERIODS,eight_full_originals_sha_checked=True,
         manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
         original_document_count=len(records),documents=records,
         statement_and_auditor_page_leads_only=True,
         no_automated_conclusion_from_missing_keyword=True,
         formal_gates_PASS_added=0,formal_Aplus=False,
         accounting_numbers_reconciled=False,
         original_release_clock_verified=False,
         named_reviewer_signature=None,
         investment_recommendation_issued=False)

def markdown(obj):
    lines=["# 6206 飛捷｜八季原始財報逐頁查核索引（非正式品質PASS）",
       "", "**八季原始檔 SHA256 已逐份重驗：8/8。** 會計師意見、現金流與存貨金額仍未核閱。",
       "此表僅是 PDF 原件第1頁起算的關鍵字定位，非印刷頁碼；文字抽取不到不代表資料不存在。",
       "", "|季度|PDF總頁數|可搜尋文字頁|會計師報告|現金流量表|存貨|應收帳款|應付帳款|",
       "|---|---:|---:|---|---|---|---|---|"]
    for d in obj["documents"]:
        p=d["page_locator"]
        def fmt(key):
            return ",".join(str(x) for x in p[key][:12]) or "待人工尋找"
        lines.append("|"+d["period"]+"|"+str(d["document_pdf_page_count"])+
            "|"+str(d["text_extractable_pages"])+
            "|"+fmt("accountant_report")+"|"+fmt("cashflow_statement")+
            "|"+fmt("inventories")+"|"+fmt("trade_receivables")+
            "|"+fmt("trade_payables")+"|")
    lines.extend(["","## 審查界線",
        "- 此表**不確認會計師是否保留、強調事項、核閱範圍或現金流與損益勾稽**。",
        "- 存貨、營業現金流、應收／應付帳款及CAPEX須逐頁取得原始數值、單位和期間才可核定。",
        "- 2024Q3～2026Q2 取得的PDF只能證明現在可重驗；不能倒填歷史PIT公告時點。",
        "- 沒有具名核閱或第13項獨立OOS，正式A+仍不可放行。",
        "","**新增正式PASS：0；新增A+：0；未產生交易指令。**",""])
    return "\n".join(lines)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-root",default="tw-market-data")
    args=parser.parse_args()
    root=Path(args.data_root)
    report=inspect(root)
    rank=root/"rankings"
    rank.mkdir(parents=True,exist_ok=True)
    atomic_json(rank/"6206_original_pdf_page_locator_latest.json",report)
    (rank/"6206_original_pdf_page_locator_latest.md").write_text(
        markdown(report),encoding="utf-8")
    print(json.dumps(dict(originals=report["original_document_count"],
        pdf_pages=sum(d["document_pdf_page_count"] for d in report["documents"]),
        cashflow_headings=sum(bool(d["page_locator"]["cashflow_statement"])
                              for d in report["documents"]),
        accountant_headings=sum(bool(d["page_locator"]["accountant_report"])
                               for d in report["documents"]),
        formal_pass=report["formal_gates_PASS_added"]),
        ensure_ascii=False))
if __name__=="__main__":
    main()
