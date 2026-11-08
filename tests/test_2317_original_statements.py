"""Synthetic controls for 2317 official PDF ingestion; fixtures are not evidence."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import fitz
from scripts import honhai_original_statements as h

STAMP=dt.datetime(2026,11,8,14,0,tzinfo=dt.timezone.utc)

def fixture(period,*,code="2317",include_notes=True):
    roc=int(period[:4])-1911;q=int(period[-1])
    season=(f"民國{roc}年度及{roc-1}年度" if q==4
            else f"民國{roc}年及{roc-1}年第{q}季")
    doc=fitz.open()
    for _ in range(25):doc.new_page()
    doc[0].insert_text((45,55),"鴻海精密工業股份有限公司及子公司\n合併財務報告暨會計師核閱報告\n"+season+"\n股票代碼"+code,fontname="china-t",fontsize=10)
    sections=h.SECTIONS if include_notes else h.SECTIONS[:-1]
    doc[1].insert_text((40,55),"\n".join(sections),fontname="china-t",fontsize=10)
    raw=doc.tobytes();doc.close()
    return raw

class HonhaiOriginalIntakeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.raw={p:fixture(p) for p in h.KNOWN}
        self.urls={url:p for p,url in h.KNOWN.items()}

    def fetcher(self,url):
        return self.raw[self.urls[url]]

    def test_three_sha_archived_without_certificate_or_fake_eight_quarter_coverage(self):
        report=h.collect(self.root,"2026-Q2",fetcher=self.fetcher,clock=lambda:STAMP)
        self.assertEqual(report["records"],3)
        self.assertEqual(report["coverage"]["required_quarters"],h.window("2026-Q2"))
        self.assertEqual(report["coverage"]["found_quarters"],sorted(h.KNOWN))
        self.assertEqual(len(report["coverage"]["missing_quarters"]),5)
        self.assertFalse(report["coverage"]["formal_gate_pass"])
        self.assertEqual(report["formal_pass_count"],0)
        self.assertTrue(report["original_archive_hashes_verified"])
        self.assertTrue(all(x["pdf_identity"]["contents_four_statements_notes_and_auditor_listed"]
                            for x in report["documents"]))
        self.assertTrue(all(x["formal_gate_pass"] is False for x in report["documents"]))
        self.assertEqual(h.validate_archive(self.root,"2026-Q2",STAMP.isoformat())["records"],3)
        again=h.collect(self.root,"2026-Q2",fetcher=lambda url: self.fail("should use existing receipts"),
                        clock=lambda:STAMP+dt.timedelta(hours=1))
        self.assertEqual(again["records"],3)

    def test_wrong_issuer_period_or_notes_rejected(self):
        for raw in (fixture("2026-Q1",code="2354"), fixture("2025-Q2"),
                    fixture("2026-Q1",include_notes=False)):
            with self.subTest(size=len(raw)):
                with self.assertRaises(ValueError):
                    h.pdf_identity(raw,"2026-Q1")

    def test_modified_pdf_bytes_invalidates_archive(self):
        h.collect(self.root,"2026-Q2",fetcher=self.fetcher,clock=lambda:STAMP)
        manifest=json.loads((self.root/h.MANIFEST).read_text())
        entry=manifest["documents"][0]
        file=self.root/entry["archive_path"]
        file.write_bytes(file.read_bytes()+b"tampering")
        with self.assertRaisesRegex(ValueError,"REHASH_OR_SIZE_FAILED"):
            h.validate_archive(self.root,"2026-Q2",STAMP.isoformat())

    def test_false_pass_and_tampered_source_rejected(self):
        h.collect(self.root,"2026-Q2",fetcher=self.fetcher,clock=lambda:STAMP)
        manifest=self.root/h.MANIFEST
        j=json.loads(manifest.read_text())
        j["documents"][0]["formal_gate_pass"]=True
        manifest.write_text(json.dumps(j))
        with self.assertRaisesRegex(ValueError,"SOURCE_ID_INVALID"):
            h.validate_archive(self.root,"2026-Q2",STAMP.isoformat())

    def test_http403_fails_closed_with_bounded_retry(self):
        calls=[]
        def rejected(url):
            calls.append(url)
            raise OSError("HTTP Error 403: Forbidden")
        result=h.collect(self.root,"2026-Q2",fetcher=rejected,clock=lambda:STAMP)
        self.assertEqual(result["records"],0)
        self.assertEqual(len(result["source_errors"]),3)
        later=h.collect(self.root,"2026-Q2",fetcher=lambda url: self.fail("403 must cool down"),
                        clock=lambda:STAMP+dt.timedelta(minutes=5))
        self.assertEqual(later["records"],0)
        self.assertEqual(len(calls),3)
        self.assertEqual(later["formal_pass_count"],0)
        self.assertFalse(later["original_archive_hashes_verified"])

    def test_missing_manifest_is_unknown_not_zero_quarter_claim(self):
        result=h.validate_archive(self.root,"2026-Q2",STAMP.isoformat())
        self.assertIsNone(result["coverage"])
        self.assertEqual(result["records"],0)
        for path in ("../other","/tmp/other"):
            with self.assertRaisesRegex(ValueError,"UNSAFE_PATH"):
                h.safe(self.root,path)

if __name__=="__main__":
    unittest.main()
