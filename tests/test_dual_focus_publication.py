"""Synthetic publication checks; no source fixture is an actual financial original."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts.verify_dual_focus_publication import verify, HEADING


class DualPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.r=self.root/"rankings"
        self.r.mkdir()
        self.source=b'{"issuer_diagnostics":[]}'
        (self.r/"v891_gate_progress.json").write_bytes(self.source)
        self.report=dict(model="TEST",estimate_vintage="2026-11-08T12:00+08:00",
                         source_progress_sha256=hashlib.sha256(self.source).hexdigest(),
                         issuer_jobs=[],dual_focus_status=[])
        for code,name in (("2330","台積電"),("2317","鴻海")):
            job=dict(code=code,formal_Aplus=False,original_quarter_coverage=None,
                     work=[dict(gate=g) for g in (
                         "original_eight_quarter_statements","cash_and_working_capital",
                         "nonoperating_components","fully_diluted_shares",
                         "matched_peers_and_cycle","management_promises",
                         "auditor_scope","tradability","forecast_bridge",
                         "insider_claims","dividend_window","point_in_time",
                         "out_of_sample_validation")])
            self.report["issuer_jobs"].append(job)
            self.report["dual_focus_status"].append(dict(
                code=code,name=name,diagnostic_status="IN_CURRENT_DIAGNOSTIC",
                company_gates_passed=0,formal_Aplus=False,original_quarter_coverage=None))
        self.markdown=("\n".join(["# 研究", "模型：TEST；估計：2026-11-08T12:00+08:00。",
                         HEADING,"|公司|正式PASS|正式A+|",
                         "|---|---|---|",
                         "|2330 台積電|0/12；待核12|否|",
                         "|2317 鴻海|0/12；待核12|否|",
                         "## 後續工作",""]))
        self.save()

    def save(self):
        (self.r/"latest_research_work_queue.json").write_text(
            json.dumps(self.report,ensure_ascii=False),encoding="utf-8")
        (self.r/"latest_research_work_queue.md").write_text(self.markdown,encoding="utf-8")

    def test_valid_synced_report(self):
        result=verify(self.root)
        self.assertEqual(result["validated_focus_codes"],["2330","2317"])
        self.assertTrue(result["verified_report_sync"])

    def test_existing_main_style_without_dual_heading_fails_closed(self):
        self.markdown=self.markdown.replace(HEADING,"## 僅台積電")
        self.save()
        with self.assertRaisesRegex(ValueError,"SECTION_MISSING"):
            verify(self.root)

    def test_old_original_ledger_source_hash_is_rejected(self):
        (self.r/"v891_gate_progress.json").write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError,"SOURCE_LEDGER_SHA_MISMATCH"):
            verify(self.root)

    def test_mismatched_archived_quarter_count_is_rejected(self):
        self.report["dual_focus_status"][0]["original_quarter_coverage"]=dict(
            archived=8,required=8,missing_quarters=[])
        self.save()
        with self.assertRaisesRegex(ValueError,"ARCHIVE_COVERAGE_MISMATCH"):
            verify(self.root)

    def test_fake_formal_certification_not_accepted(self):
        self.report["dual_focus_status"][0]["formal_Aplus"]=True
        self.save()
        with self.assertRaisesRegex(ValueError,"FORMAL_STATUS_MISMATCH"):
            verify(self.root)

    def test_missing_second_company_is_rejected(self):
        self.report["dual_focus_status"].pop()
        self.save()
        with self.assertRaisesRegex(ValueError,"LANE_LIST_INCOMPLETE"):
            verify(self.root)


if __name__=="__main__":
    unittest.main()
