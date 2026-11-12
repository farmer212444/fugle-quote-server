"""Original 6206 PDF page locator: no mistaken signed financial review."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.flytech_original_pdf_locator import (
    PERIODS,inspect,locate,markdown,normalize)

def fixture(root):
    root=Path(root)
    docs=[]
    for period in PERIODS:
        content=("%PDF-1.4 6206 synthetic quarter "+period).encode()
        digest=hashlib.sha256(content).hexdigest()
        path=Path("evidence/v880/originals/6206/full_statements")/period/(digest[:16]+".pdf")
        target=root/path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(content)
        docs.append(dict(period=period,archive_path=path.as_posix(),
            sha256=digest,bytes=len(content),
            source_url="https://doc.twse.com.tw/pdf/"+period+".pdf",
            pdf_identity={"page_count":25},
            first_publication_timestamp_verified=False,
            original_full_notes_reviewed=False,
            formal_gate_pass=False))
    manifest=root/"evidence/v880/originals/6206/full_statements/manifest.json"
    manifest.write_text(json.dumps(dict(
        schema="V8108_6206_QUARTERLY_FULL_ORIGINALS_V1",
        issuer="6206",documents=docs)),encoding="utf-8")
    return docs,manifest

def page_text(_):
    return [
        "飛捷科技 合併資產負債表 合併綜合損益表 合併權益變動表 \n"
        "會計師 核閱報告 合併現金流量表 存 貨 應收帳款 應付帳款",
        "飛捷科技 合併財務報表附註 取得不動產",
    ]+[""]*23

class OriginalQuarterLocator(unittest.TestCase):
    def test_page_number_one_based_heading_leads_not_audit(self):
        p=locate(["", "合 併 現 金 流 量 表\\n應 收 帳 款",
                  "會計師核閱報告  存 貨"])
        self.assertEqual(p["cashflow_statement"],[])  # literal backslash is not space
        self.assertEqual(p["accountant_report"],[3])
        self.assertEqual(p["inventories"],[3])
        self.assertEqual(normalize("合 併 財 務 報 表 附 註"),"合併財務報表附註")
        p2=locate(["合 併 現 金 流 量 表\n應 收 帳 款"])
        self.assertEqual(p2["cashflow_statement"],[1])
        self.assertEqual(p2["trade_receivables"],[1])

    def test_eight_originals_mapped_without_issuing_PIT_or_PASS(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            doc=inspect(root,read_pdf=page_text)
            self.assertEqual(doc["original_document_count"],8)
            self.assertTrue(doc["eight_full_originals_sha_checked"])
            self.assertFalse(doc["formal_Aplus"])
            self.assertEqual(doc["formal_gates_PASS_added"],0)
            self.assertFalse(doc["accounting_numbers_reconciled"])
            self.assertTrue(all(x["page_locator"]["cashflow_statement"]==[1]
                    for x in doc["documents"]))
            self.assertEqual(doc["documents"][0]["page_locator"]["financial_notes"],[2])
            self.assertTrue(doc["documents"][0]["unreadable_or_unindexed_pages_require_manual_visual_review"])
            report=markdown(doc)
            self.assertIn("現金流量表",report)
            self.assertIn("0；新增A+：0",report)

    def test_wrong_sha_or_file_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);docs,manifest=fixture(root)
            target=root/docs[0]["archive_path"]
            target.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError,"SHA_OR_LENGTH_MISMATCH"):
                inspect(root,read_pdf=page_text)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);docs,manifest=fixture(root)
            docs[0]["pdf_identity"]["page_count"]=26
            manifest.write_text(json.dumps(dict(
                schema="V8108_6206_QUARTERLY_FULL_ORIGINALS_V1",issuer="6206",
                documents=docs)),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"PAGE_COUNT_MANIFEST_MISMATCH"):
                inspect(root,read_pdf=page_text)

    def test_missing_quarter_and_false_certificate_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);docs,manifest=fixture(root)
            o=json.loads(manifest.read_text());o["documents"][-1]["period"]="2025-Q4"
            manifest.write_text(json.dumps(o),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"QUARTERS_MISSING_OR_DUPLICATE"):
                inspect(root,read_pdf=page_text)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);docs,manifest=fixture(root)
            o=json.loads(manifest.read_text());o["documents"][0]["formal_gate_pass"]=True
            manifest.write_text(json.dumps(o),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"UNSUPPORTED_FORMAL_CERTIFICATION"):
                inspect(root,read_pdf=page_text)

if __name__=="__main__":
    unittest.main()
