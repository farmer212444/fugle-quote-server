"""Fail-closed 2317 human-auditor review packet regression tests."""
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import fitz

from scripts import honhai_original_statements as h
from scripts import honhai_original_review_packet as p

ASOF="2026-11-09T05:00:00+08:00"
CAPTURE="2026-11-08T14:10:00+00:00"

def synthetic_full_pdf():
    doc=fitz.open()
    for _ in range(25):doc.new_page()
    doc[0].insert_text((40,60),
        "鴻海精密工業股份有限公司及子公司\n合併財務報告暨會計師查核報告\n民國114年度及113年度\n股票代碼2317",
        fontname="china-t",fontsize=10)
    doc[1].insert_text((40,60),"\n".join(h.SECTIONS),fontname="china-t",fontsize=10)
    doc[2].insert_text((40,60),"會計師查核報告\n保留意見\n其他事項",
                           fontname="china-t",fontsize=10)
    pdf=doc.tobytes();doc.close()
    return pdf

class ReviewerPrepTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)

    def insert_original(self):
        raw=synthetic_full_pdf()
        identity=h.pdf_identity(raw,"2025-Q4")
        digest=hashlib.sha256(raw).hexdigest()
        rel=f"{h.FOLDER}/2025-Q4_{digest[:20]}.pdf"
        path=self.root/rel
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
        m=dict(schema=h.SCHEMA,issuer="2317",formal_gate_pass=False,
               full_content_review_complete=False,MOPS_filing_PIT_verified=False,
               documents=[dict(period="2025-Q4",source_url=h.KNOWN["2025-Q4"],
                               sha256=digest,bytes=len(raw),archive_path=rel,
                               captured_at_utc=CAPTURE,pdf_identity=identity,
                               formal_gate_pass=False)])
        (self.root/h.MANIFEST).write_text(json.dumps(m,ensure_ascii=False),encoding="utf-8")
        return path

    def test_direct_cli_import_from_outside_project(self):
        env=dict(os.environ)
        env.pop("PYTHONPATH",None)
        script=Path(p.__file__).resolve()
        with tempfile.TemporaryDirectory() as cwd:
            proc=subprocess.run([sys.executable,str(script),"--help"],
                                cwd=cwd,env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn("--data-root",proc.stdout)

    def test_no_manifest_is_unknown_not_formal_missing_or_pass(self):
        report=p.build_packet(self.root,"2026-Q2",ASOF)
        self.assertEqual(report["coverage"]["status"],"UNKNOWN_NO_MANIFEST")
        self.assertIsNone(report["coverage"]["archived_count"])
        self.assertEqual(len(report["original_documents"]),8)
        self.assertEqual(report["formal_gate_pass_count_created"],0)
        self.assertFalse(report["formal_certificate_emitted"])
        self.assertIsNone(report["reviewer_id"])

    def test_partial_originals_rehash_and_link_auditor_page_only(self):
        self.insert_original()
        report=p.build_packet(self.root,"2026-Q2",ASOF)
        self.assertEqual(report["coverage"]["archived_count"],1)
        self.assertEqual(len(report["coverage"]["missing_quarters"]),7)
        doc=next(d for d in report["original_documents"] if d["period"]=="2025-Q4")
        self.assertEqual(doc["archive_state"],"SHA_REHASHED")
        self.assertFalse(doc["formal_gate_pass"])
        self.assertFalse(doc["publication_PIT_verified"])
        lead=doc["auditor_leads"]
        self.assertFalse(lead["formal_auditor_opinion_reviewed"])
        self.assertFalse(lead["complete_notes_reviewed"])
        self.assertTrue(any(d["keyword"]=="保留意見" and d["pdf_page_1based"]==3
                            for d in lead["keyword_leads"]))
        markdown=p.render(report)
        self.assertIn("第3頁",markdown)
        self.assertIn("不產生任何正式PASS",markdown)

    def test_tamper_stops_report_before_exposing_unverified_evidence(self):
        path=self.insert_original()
        path.write_bytes(path.read_bytes()+b"malicious change")
        with self.assertRaisesRegex(ValueError,"HONHAI_PDF_REHASH_OR_SIZE_FAILED"):
            p.build_packet(self.root,"2026-Q2",ASOF)

    def test_issuer_identities_are_strictly_original_validated(self):
        path=self.insert_original()
        mpath=self.root/h.MANIFEST
        obj=json.loads(mpath.read_text())
        obj["documents"][0]["source_url"]="https://untrusted.invalid/fake.pdf"
        mpath.write_text(json.dumps(obj,ensure_ascii=False))
        with self.assertRaisesRegex(ValueError,"HONHAI_ARCHIVED_ORIGINAL_SOURCE_ID_INVALID"):
            p.build_packet(self.root,"2026-Q2",ASOF)

if __name__=="__main__":
    unittest.main()
