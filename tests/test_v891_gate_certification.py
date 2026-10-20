"""V8.9.1 reviewed evidence cannot be promoted without original bytes/signoff."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "v891", Path(__file__).resolve().parents[1] / "scripts/v891_gate_certification.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

STAMP = "2026-10-20T00:00:00+00:00"
CHECK = "2026-10-19T12:00:00+00:00"

class GateAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"tw-market-data"
        self.original=self.root/"evidence/v880/originals/6206_original.txt"
        self.original.parent.mkdir(parents=True,exist_ok=True)
        self.original.write_bytes(b"fixture original 6206 audited company page")
        self.file=self.root/"evidence/v880/review_packs/6206.json"
        self.file.parent.mkdir(parents=True,exist_ok=True)
        self.source=dict(url="https://mopsov.twse.com.tw/mops/web/ajax_t163sb04",
            sha256=hashlib.sha256(self.original.read_bytes()).hexdigest(),
            archive_path="evidence/v880/originals/6206_original.txt",
            available_at="2026-10-19T08:00:00+00:00",origin_authenticated=True)
        self.item=dict(code="6206",financial_period="2026-Q2",gates={
            "original_eight_quarter_statements":dict(
                issuer="6206",financial_period="2026-Q2",status="PASS",
                checked_at=CHECK,available_at="2026-10-19T08:00:00+00:00",
                expires_at="2026-11-20T00:00:00+00:00",
                review_completed=True,source_identity_reviewed=True,
                reviewer_id="reviewer_model_01",
                method="Independent full-note and eight-quarter reconciliation in review workpaper",
                review_note="Verified with eight original filing sets and full attachments for this synthetic test",
                sources=[self.source])})
        self.file.write_text(json.dumps(self.item),encoding="utf-8")
    def test_pass_only_with_archived_reviewed_original(self):
        r=mod.emit_certificates(self.root,mod.timestamp(STAMP),"2026-Q2")
        self.assertEqual(r[0]["status"],"CERTIFICATE_EMITTED")
        cert=mod.load(self.root/"evidence/v880/certificates/6206.json")
        self.assertEqual(len(cert["gates"]),1)
        status=mod.certify("6206",40,None,cert["gates"],STAMP,"2026-Q2")
        self.assertEqual(status["gates_passed"],["original_eight_quarter_statements"])
        self.assertEqual(len(status["gates_pending"]),12)
        self.assertFalse(status["formal_Aplus"])
        self.assertEqual(mod.emit_certificates(self.root,mod.timestamp(STAMP),"2026-Q2")[0]["status"],
                         "CERTIFICATE_UNCHANGED")
    def test_modified_bytes_are_rejected(self):
        self.original.write_bytes(b"tampered")
        r=mod.emit_certificates(self.root,mod.timestamp(STAMP),"2026-Q2")
        self.assertEqual(r[0]["status"],"REVIEW_PACK_REJECTED")
        self.assertIn("HASH_MISMATCH",r[0]["rejection"])
        self.assertFalse((self.root/"evidence/v880/certificates/6206.json").exists())
    def test_future_attestation_or_stale_period_rejected(self):
        self.item["gates"]["original_eight_quarter_statements"]["checked_at"]="2026-10-21T00:00:00+00:00"
        self.file.write_text(json.dumps(self.item))
        self.assertIn("TIME_EXPIRED_OR_FUTURE",
                      mod.emit_certificates(self.root,mod.timestamp(STAMP),"2026-Q2")[0]["rejection"])
        self.assertIn("FINANCIAL_PERIOD_STALE",
                      mod.emit_certificates(self.root,mod.timestamp(STAMP),"2026-Q3")[0]["rejection"])
    def test_review_is_required_even_with_hash_and_original(self):
        self.item["gates"]["original_eight_quarter_statements"]["review_completed"]=False
        self.file.write_text(json.dumps(self.item))
        r=mod.emit_certificates(self.root,mod.timestamp(STAMP),"2026-Q2")
        self.assertIn("NOT_REVIEWED",r[0]["rejection"])
    def test_path_traversal_rejected(self):
        self.item["gates"]["original_eight_quarter_statements"]["sources"][0]["archive_path"]="../escape.txt"
        self.file.write_text(json.dumps(self.item))
        self.assertIn("UNSAFE_ARCHIVE_PATH",
                      mod.emit_certificates(self.root,mod.timestamp(STAMP),"2026-Q2")[0]["rejection"])
    def test_reviewed_failure_is_not_promoted(self):
        self.item["gates"]["original_eight_quarter_statements"]["status"]="FAIL"
        self.file.write_text(json.dumps(self.item))
        mod.emit_certificates(self.root,mod.timestamp(STAMP),"2026-Q2")
        cert=mod.load(self.root/"evidence/v880/certificates/6206.json")
        r=mod.certify("6206",40,None,cert["gates"],STAMP,"2026-Q2")
        self.assertIn("original_eight_quarter_statements",r["gates_failed"])
        self.assertEqual(r["status"],"QUALITY_REVIEW_FAILED")
    def test_progress_distinguishes_8q_and_20sessions_from_formal_pass(self):
        d=self.root/"rankings"
        d.mkdir(parents=True)
        research=dict(model="V8.8.2",estimate_vintage=STAMP,financial_last_quarter="2026-Q2",
                      asof_price_date="2026-10-16",formal_Aplus_count=0,
                      data_scope={"model_rows":2})
        dispatch=dict(vintage=STAMP,price_date="2026-10-16",
                      tracked_issuer_count=2,eligible_research_count=1,
                      all_issuer_jobs=[
                         dict(code="6206",name="飛捷",market="TWSE",research_upside_pct=42),
                         dict(code="9802",name="鈺齊-KY",market="TWSE",research_upside_pct=None)])
        probe=dict(estimate_vintage=STAMP,asof_price_date="2026-10-16",
                   top_priority_evidence=[dict(code="6206",market="TWSE",
                     financial=dict(normalized_income_8q_count=8,normalized_cashflow_8q_count=8),
                     capital=dict(issued_share_master_present=True,unverified_bond_terms=[]),
                     issuer_historical_market_data=dict(twenty_day=dict(sessions=20)))])
        for name,obj in [("latest_research.json",research),
            ("v883_gate_dispatch.json",dispatch),("v884_evidence_progress.json",probe)]:
            (d/name).write_text(json.dumps(obj))
        results=mod.build_progress(self.root)
        self.assertEqual(results["high_upside_research_candidates"],1)
        self.assertEqual(results["formally_certified_Aplus_in_report"],0)
        stages=results["issuer_diagnostics"][0]["gate_stage"]
        self.assertEqual(stages["original_eight_quarter_statements"]["stage"],"MIRROR_CAPTURED")
        self.assertEqual(stages["tradability"]["stage"],"SOURCE_CAPTURED")
        self.assertFalse(stages["tradability"]["formal_pass"])

if __name__=="__main__":
    unittest.main()
