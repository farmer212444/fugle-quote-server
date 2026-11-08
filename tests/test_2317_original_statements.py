"""Synthetic controls for 2317 official PDF ingestion; fixtures are not evidence."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import fitz
from scripts import honhai_original_statements as h

STAMP=dt.datetime(2026,11,8,14,0,tzinfo=dt.timezone.utc)

class HonhaiCommandTests(unittest.TestCase):
    def test_direct_cli_launch_without_pythonpath_or_project_working_directory(self):
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        script = Path(h.__file__).resolve()
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(script), '--help'], cwd=folder,
                                    env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--data-root', result.stdout)

def fixture(period,*,code="2317",include_notes=True):
    roc=int(period[:4])-1911;q=int(period[-1])
    season=(f"民國{roc}年度及{roc-1}年度" if q==4
            else f"民國{roc}年及{roc-1}年第{h.CHINESE_QUARTERS[q-1]}季")
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

    def test_official_allowlisted_pdfs_archive_without_certificate_or_fake_eight_quarter_coverage(self):
        report=h.collect(self.root,"2026-Q2",fetcher=self.fetcher,clock=lambda:STAMP)
        self.assertEqual(report["records"],len(h.KNOWN))
        self.assertEqual(report["coverage"]["required_quarters"],h.window("2026-Q2"))
        self.assertEqual(report["coverage"]["found_quarters"],sorted(h.KNOWN))
        self.assertEqual(len(report["coverage"]["missing_quarters"]),8-len(h.KNOWN))
        self.assertFalse(report["coverage"]["formal_gate_pass"])
        self.assertEqual(report["formal_pass_count"],0)
        self.assertTrue(report["original_archive_hashes_verified"])
        self.assertTrue(all(x["pdf_identity"]["contents_four_statements_notes_and_auditor_listed"]
                            for x in report["documents"]))
        self.assertTrue(all(x["formal_gate_pass"] is False for x in report["documents"]))
        self.assertEqual(h.validate_archive(self.root,"2026-Q2",STAMP.isoformat())["records"],len(h.KNOWN))
        again=h.collect(self.root,"2026-Q2",fetcher=lambda url: self.fail("should use existing receipts"),
                        clock=lambda:STAMP+dt.timedelta(hours=1))
        self.assertEqual(again["records"],len(h.KNOWN))

    def test_real_official_cover_wording_for_q1_and_q2_is_accepted(self):
        # Actual 2025-Q2 and 2026-Q1 official covers use 第一季/第二季,
        # not 第1季/第2季. These synthetic PDFs reproduce that exact wording.
        for period in ("2025-Q1", "2025-Q2", "2025-Q3", "2026-Q1"):
            raw=fixture(period)
            identity=h.pdf_identity(raw,period)
            self.assertTrue(identity["native_cover_issuer_and_period_verified"])
            self.assertTrue(identity["contents_four_statements_notes_and_auditor_listed"])
            self.assertFalse(identity["formal_gate_pass"])
        # Preserve a strict quarter match: a Q1 original cannot pass as Q2.
        with self.assertRaisesRegex(ValueError,"ISSUER_PERIOD_NOT_CONFIRMED"):
            h.pdf_identity(fixture("2026-Q1"),"2025-Q2")
        # Arabic 1/2 cannot silently replace the official Chinese quarter labels.

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
        self.assertEqual(len(result["source_errors"]),len(h.KNOWN))
        later=h.collect(self.root,"2026-Q2",fetcher=lambda url: self.fail("403 must cool down"),
                        clock=lambda:STAMP+dt.timedelta(minutes=5))
        self.assertEqual(later["records"],0)
        self.assertEqual(len(calls),len(h.KNOWN))
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
