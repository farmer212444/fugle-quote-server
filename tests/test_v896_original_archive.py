"""V8.9.6 original PDF archiving must never fabricate issuer certification."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v896_original_archive import (
    collect, is_official, select_sources, validate_bundle, validate_pdf,
    original_quarter_coverage
)

DAY = "2026-10-21"
NOW = "2026-10-20T22:00:00+00:00"


def fixture_pdf(extra=b""):
    return b"%PDF-1.4\n" + b"A" * 5200 + extra + b"\n%%EOF\n"


class OriginalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.ctx.cleanup)
        self.root = Path(self.ctx.name)
        (self.root / "issuer/9802").mkdir(parents=True)
        (self.root / "ir/6206").mkdir(parents=True)

    def write_source(self, issuer, item):
        target = (self.root / "issuer/9802/manifest.json" if issuer=="9802"
                  else self.root / "ir/6206/manifest.json")
        target.write_text(json.dumps(item), encoding="utf-8")

    def source9802(self):
        entries=[
            {"id":"a"*20,"category":"quarterly","site_display_date":"2026-08-18",
             "title":"2026年第二季合併財務報告","url":"https://www.fulgentsun.com/img/Finance/115Q2.pdf"},
            {"id":"b"*20,"category":"quarterly","site_display_date":"2025-11-06",
             "title":"2025年第三季合併財務報告","url":"https://www.fulgentsun.com/img/Finance/.pdf"},
            {"id":"c"*20,"category":"news","site_display_date":"2026-10-20",
             "title":"2026年第三季自結財報新聞稿",
             "url":"https://www.fulgentsun.com/img/News_Release/FY2026%203Q%20financial%20results%20CN.pdf"}
        ]
        return {"issuer":"9802","publisher":"鈺齊國際","discovered":entries,
                "receipts":{"a"*20:{"versions":[{"sha256":"0"*64}]}}}

    def test_publisher_whitelist_and_broken_quarter_link(self):
        self.assertTrue(is_official("9802","https://www.fulgentsun.com/img/Finance/115Q2.pdf"))
        self.assertFalse(is_official("9802","https://www.fulgentsun.com/img/Finance/.pdf"))
        self.assertFalse(is_official("9802","http://www.fulgentsun.com/img/Finance/115Q2.pdf"))
        self.assertFalse(is_official("9802","https://bad.example/img/Finance/115Q2.pdf"))
        self.assertFalse(is_official("9802","https://www.fulgentsun.com/img/Finance/../secrets.pdf"))
        self.assertFalse(is_official("6206","https://www.fulgentsun.com/img/Finance/115Q2.pdf"))
        r=select_sources("9802",self.source9802(),DAY)
        self.assertEqual(len(r),2)
        self.assertEqual(r[0]["category"],"news")
        self.assertEqual(r[1]["document_date"],"2026-08-18")
        self.assertEqual(len(select_sources("9802",self.source9802(),"2026-09-01")),1)

    def test_2024q3_official_pdf_is_in_eight_quarter_intake_window(self):
        source=self.source9802()
        source["discovered"].append({
            "id":"d"*20,"category":"quarterly",
            "site_display_date":"2024-11-07",
            "title":"2024年第三季合併財務報告",
            "url":"https://www.fulgentsun.com/img/Finance/202403_9802_AI1_20241128_102700.pdf"
        })
        urls=[r["url"] for r in select_sources("9802",source,DAY,max_documents=12)]
        self.assertTrue(any("202403_9802_AI1_20241128_102700.pdf" in x for x in urls))
        self.assertFalse(any(x.endswith("/.pdf") for x in urls))

    def test_2025q3_english_official_fallback_closes_missing_quarter_only(self):
        source=self.source9802()
        source["discovered"].extend([
            {"id":"e"*20, "category":"quarterly_en", "site_display_date":"2025-12-05",
             "title":"2025 Q3 Consolidated Financial Statements",
             "url":"https://www.fulgentsun.com/img/Finance/2025Q3(EN)%201204.pdf"},
            {"id":"f"*20, "category":"quarterly_en", "site_display_date":"2026-09-18",
             "title":"2026 Q2 Consolidated Financial Statements",
             "url":"https://www.fulgentsun.com/img/Finance/2026Q2(EN).pdf"}
        ])
        selected=select_sources("9802", source, DAY,max_documents=12)
        q3=[s for s in selected if "2025Q3(EN)" in s["url"]]
        self.assertEqual(len(q3),1)
        self.assertEqual(q3[0]["category"],"quarterly")
        self.assertEqual(q3[0]["document_date"],"2025-12-05")
        self.assertTrue(q3[0]["translation_of_chinese_original"])
        self.assertFalse(any("2026Q2(EN)" in s["url"] for s in selected))
        selected_early=select_sources("9802",source,"2025-11-30")
        self.assertFalse(any("2025Q3(EN)" in s["url"] for s in selected_early))
        # Do not accept fake 2025Q3 index dates that attempt historical lookahead.
        source["discovered"][-2]["site_display_date"]="2025-11-06"
        rejected=select_sources("9802",source,DAY,max_documents=12)
        self.assertFalse(any("2025Q3(EN)" in s["url"] for s in rejected))

    def test_durable_pdf_exact_sha_and_no_rating_promotion(self):
        self.write_source("9802",self.source9802())
        documents=[fixture_pdf(b"Q3"),fixture_pdf(b"Q2")]
        calls=[]
        def fetch(issuer,url):
            calls.append(url)
            return documents[len(calls)-1]
        report=collect(self.root,"9802",DAY,NOW,fetcher=fetch)
        self.assertEqual(report["selected"],2)
        self.assertEqual(report["captured"],2)
        self.assertEqual(report["receipt_hash_discrepancies"],1)
        self.assertEqual(report["formal_pass_count"],0)
        self.assertEqual(report["errors"],[])
        self.assertTrue(report["original_archive_hashes_verified"])
        manifest=json.loads((self.root/"evidence/v880/originals/9802/manifest.json").read_text())
        self.assertFalse(manifest["original_MOPS_PIT_verified"])
        self.assertFalse(manifest["original_document_content_independently_reviewed"])
        self.assertEqual(manifest["formally_certified_gates"],0)
        self.assertTrue(all(not x["formal_gate_pass"] for x in manifest["documents"]))
        # A later run retains prior captures and does not re-download them.
        second=collect(self.root,"9802",DAY,NOW,fetcher=lambda *_: self.fail("re-fetched"))
        self.assertEqual(second["reused"],2)
        self.assertEqual(second["captured"],0)
        self.assertEqual(validate_bundle(self.root,"9802")["records"],2)

    def test_archive_change_or_counterfeit_certification_fails_closed(self):
        self.write_source("9802",self.source9802())
        collect(self.root,"9802",DAY,NOW,fetcher=lambda *_: fixture_pdf())
        bundle_path=self.root/"evidence/v880/originals/9802/manifest.json"
        doc=json.loads(bundle_path.read_text())
        item=doc["documents"][0]
        (self.root/item["archive_path"]).write_bytes(b"altered")
        with self.assertRaisesRegex(ValueError,"INVALID_OR_OVERSIZE|HASH"):
            validate_bundle(self.root,"9802")
        (self.root/item["archive_path"]).write_bytes(fixture_pdf())
        doc["formally_certified_gates"]=1
        bundle_path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError,"FALSE_CERTIFICATION"):
            validate_bundle(self.root,"9802")

    def test_archive_cannot_point_to_other_issuer_or_external_source(self):
        self.write_source("9802",self.source9802())
        collect(self.root,"9802",DAY,NOW,fetcher=lambda *_:fixture_pdf())
        path=self.root/"evidence/v880/originals/9802/manifest.json"
        obj=json.loads(path.read_text(encoding="utf-8"))
        obj["documents"][0]["archive_path"]="evidence/v880/originals/6206/some.pdf"
        path.write_text(json.dumps(obj),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"OUTSIDE_ISSUER_DIRECTORY"):
            validate_bundle(self.root,"9802")

    def test_6206_official_presentation_sha_receipt(self):
        source={"code":"6206","presentations":[
            {"event_date":"2026-08-12","title":"飛捷Q2官方法說",
             "source_url":"https://www.flytech.com.tw/data/investor_law/attached/1786525880605469429.pdf",
             "pdf_sha256":"1"*64}]}
        self.write_source("6206",source)
        found=select_sources("6206",source,DAY)
        self.assertEqual(len(found),1)
        result=collect(self.root,"6206",DAY,NOW,fetcher=lambda *_:fixture_pdf())
        self.assertEqual(result["captured"],1)
        self.assertEqual(result["receipt_hash_discrepancies"],1)
        self.assertEqual(result["formal_pass_count"],0)

    def test_exact_eight_quarters_not_just_count_of_eight_pdfs(self):
        source=self.source9802()
        source["discovered"]=[
            {"id":f"{idx:020x}","category":"quarterly",
             "site_display_date":f"{year}-{month:02d}-{day:02d}",
             "title":f"{period[:4]}年{qname}季合併財務報告",
             "url":f"https://www.fulgentsun.com/img/Finance/{period}.pdf"}
            for idx,(period,year,month,day,qname) in enumerate([
                ("2024Q2",2024,8,19,"第二"),("2024Q3",2024,11,7,"第三"),
                ("2024Q4",2025,2,26,"第四"),("2025Q1",2025,5,8,"第一"),
                ("2025Q2",2025,8,26,"第二"),("2025Q4",2026,2,25,"第四"),
                ("2026Q1",2026,5,8,"第一"),("2026Q2",2026,8,18,"第二")
            ])
        ]
        self.write_source("9802",source)
        # The published archive previously held eight PDFs but accidentally
        # included 2024Q2 and omitted the necessary 2025Q3.
        captured=collect(self.root,"9802",DAY,NOW,max_documents=12,
                         fetcher=lambda issuer,url:fixture_pdf(url.encode()))
        self.assertEqual(captured["records"],8)
        coverage=original_quarter_coverage(self.root,"9802","2026-Q2")
        self.assertEqual(coverage["missing_quarters"],["2025-Q3"])
        self.assertFalse(coverage["source_title_coverage_complete"])
        self.assertFalse(coverage["formal_gate_pass"])
        # Add the genuine index metadata of the official English translation.
        source["discovered"].append({
            "id":"f"*20,"category":"quarterly_en",
            "site_display_date":"2025-12-05",
            "title":"2025 Q3 Consolidated Financial Statements",
            "url":"https://www.fulgentsun.com/img/Finance/2025Q3(EN)%201204.pdf"})
        self.write_source("9802",source)
        captured=collect(self.root,"9802",DAY,NOW,max_documents=12,
                         fetcher=lambda issuer,url:fixture_pdf(url.encode()))
        self.assertEqual(captured["records"],9)
        coverage=original_quarter_coverage(self.root,"9802","2026-Q2")
        self.assertTrue(coverage["source_title_coverage_complete"])
        self.assertEqual(len(coverage["found_quarters"]),8)
        self.assertEqual(coverage["missing_quarters"],[])
        self.assertFalse(coverage["pdf_accounting_period_internal_identity_verified"])
        self.assertFalse(coverage["formal_gate_pass"])

    def test_pdf_size_and_trailer_restrictions(self):
        for invalid in (b"%PDF-bad",b"<html>not a pdf</html>",b"%PDF-1.7"+b"x"*7000):
            with self.assertRaisesRegex(ValueError,"INVALID_OR_OVERSIZE_PDF_BYTES"):
                validate_pdf(invalid)
        self.assertRegex(validate_pdf(fixture_pdf()),r"^[a-f0-9]{64}$")


if __name__=="__main__":
    unittest.main()
