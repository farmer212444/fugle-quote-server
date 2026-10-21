"""Eight-quarter native text preflight is not human-reviewed formal certification."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v896_original_archive import collect
from scripts.v8a0_9802_pdf_outline import (
    SCHEMA, audit, inspect_native_text, period_of_title, period_tokens
)


class PDFOutlineTests(unittest.TestCase):
    def test_chinese_period_and_sections_are_only_preflight(self):
        pages=[
            "鈺齊國際股份有限公司 民國115年6月30日\n會計師核閱報告",
            "合併資產負債表\n合併綜合損益表\n合併權益變動表\n合併現金流量表",
            "合併財務報告附註 " + "附註的原始正文。"*120
        ]
        p=inspect_native_text(pages,"2026-Q2")
        self.assertEqual(p["preflight_status"],
                         "NATIVE_TEXT_SECTION_MARKERS_FOUND_NOT_CERTIFIED")
        self.assertEqual(p["page_count"],3)
        self.assertEqual(p["section_page_keyword_hits"]["financial_position"],[2])
        self.assertFalse(p["formal_original_eight_quarter_gate_pass"])
        self.assertFalse(p["pdf_internal_financial_number_reconciliation_completed"])
        self.assertFalse(p["auditors_opinion_and_materiality_independently_reviewed"])

    def test_english_translation_period_preflight_does_not_backdate_publication(self):
        pages=[
            "Fulgent Sun International (Holding) Co. Ltd., September 30, 2025",
            ("Consolidated Balance Sheets, Consolidated Statements of "
             "Comprehensive Income, Consolidated Statements of Changes in Equity"),
            ("Consolidated Statements of Cash Flows, Notes to the "
             "Consolidated Financial Statements. Independent Auditors Review Report."
             + " All the detailed accounting notes. "*80)
        ]
        p=inspect_native_text(pages,"2025-Q3")
        self.assertTrue(p["issuer_identity_and_period_text_hints"])
        self.assertEqual(p["missing_native_text_section_markers"],[])
        self.assertFalse(p["source_issuer_filing_PIT_verified"])
        self.assertFalse(p["formal_original_eight_quarter_gate_pass"])

    def test_missing_auditor_report_or_wrong_period_requires_human_review(self):
        pages=["鈺齊國際 民國115年6月30日",
               "合併資產負債表 綜合損益表 合併權益變動表 合併現金流量表",
               "合併財務報告附註 " + "內容"*400]
        p=inspect_native_text(pages,"2026-Q2")
        self.assertIn("auditor_report_text",p["missing_native_text_section_markers"])
        self.assertEqual(p["preflight_status"],
                         "NATIVE_TEXT_GAPS_REQUIRE_VISUAL_OR_DOCUMENT_REVIEW")
        wrong=inspect_native_text(pages,"2026-Q1")
        self.assertFalse(wrong["accounting_period_date_tokens_on_first_12_pages"])
        self.assertFalse(wrong["formal_original_eight_quarter_gate_pass"])

    def test_period_of_title_exact_no_unrelated_expansion(self):
        self.assertEqual(period_of_title("2026年第二季合併財務報告"),"2026-Q2")
        self.assertEqual(period_of_title("2025 Q3 Consolidated Financial Statements"),"2025-Q3")
        self.assertIsNone(period_of_title("2026年第三季自結財報新聞稿"))
        self.assertIn("114年9月30日",period_tokens("2025-Q3"))

    def test_full_eight_quarter_archived_workpaper_no_false_certificate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"issuer/9802").mkdir(parents=True)
            targets=[
                ("2024-Q3","2024-11-07","第三"),
                ("2024-Q4","2025-02-26","第四"),
                ("2025-Q1","2025-05-08","第一"),
                ("2025-Q2","2025-08-26","第二"),
                ("2025-Q3","2025-12-05","EN"),
                ("2025-Q4","2026-02-25","第四"),
                ("2026-Q1","2026-05-08","第一"),
                ("2026-Q2","2026-08-18","第二"),
            ]
            found=[]
            for i,(period,display,name) in enumerate(targets):
                url=("https://www.fulgentsun.com/img/Finance/2025Q3(EN)%201204.pdf"
                     if name=="EN" else f"https://www.fulgentsun.com/img/Finance/{period}.pdf")
                found.append(dict(
                    id=f"{i+1:020x}",category="quarterly_en" if name=="EN" else "quarterly",
                    site_display_date=display,
                    title=(f"2025 Q3 Consolidated Financial Statements" if name=="EN" else
                           f"{period[:4]}年{name}季合併財務報告"),
                    url=url
                ))
            (root/"issuer/9802/manifest.json").write_text(json.dumps({
                "issuer":"9802","publisher":"鈺齊國際",
                "discovered":found,"receipts":{}
            }),encoding="utf-8")
            def fake_bytes(issuer,url):
                return b"%PDF-1.4\n"+(url.encode()+b"|")*180+b"%%EOF\n"
            result=collect(root,"9802","2026-10-21","2026-10-21T02:20:00+00:00",
                           max_documents=12,fetcher=fake_bytes)
            self.assertEqual(result["records"],8)
            def fake_page_reader(path):
                content=path.name
                return ["鈺齊國際 存查原件 2025年9月30日",
                        "會計師核閱報告 合併資產負債表 合併綜合損益表 合併權益變動表 "
                        "合併現金流量表 合併財務報告附註"+"財報"*300]
            checked=audit(root,reader=fake_page_reader)
            self.assertEqual(checked["schema"],SCHEMA)
            self.assertEqual(checked["required_periods_with_original_sources"],8)
            self.assertEqual(checked["required_periods_without_original_sources"],[])
            self.assertEqual(checked["formal_13_gate_pass_count_increment"],0)
            self.assertFalse(checked["all_eight_originals_have_formal_content_signoff"])
            translated=checked["reported_quarters"]["2025-Q3"]
            self.assertTrue(translated["publisher_english_translation"])
            self.assertFalse(translated["translation_supremacy_reconciled"])
            self.assertFalse(translated["formal_original_eight_quarter_gate_pass"])

if __name__ == "__main__":
    unittest.main()
