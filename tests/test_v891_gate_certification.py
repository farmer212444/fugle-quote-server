"""V8.9.1 reviewed evidence cannot be promoted without original bytes/signoff."""
import hashlib
import copy
import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def save_snapshot(self, research, dispatch, probe, rows=None):
        """A hashed published engine snapshot, not a raw certificate shortcut."""
        if rows is None:
            rows=[]
            for job in dispatch['all_issuer_jobs']:
                row=dict(code=job['code'],market=job['market'],name=job.get('name'),
                         financial_period=research['financial_last_quarter'],
                         scenario_upside_pct=job.get('research_upside_pct'),gates={})
                if job.get('research_upside_pct') is not None:
                    row['certification']=mod.certify(row['code'],row['scenario_upside_pct'],None,
                        {},research['estimate_vintage'],row['financial_period'])
                    row['status']=row['certification']['status']
                else:
                    row['status']='CURRENT_FINANCIAL_STATEMENT_MISSING'
                rows.append(row)
        full=dict(research,all_model_rows=rows)
        raw=json.dumps(full).encode()
        packed=gzip.compress(raw,mtime=0)
        research['full_results']=dict(path='v880_full_results.json.gz',
            sha256=hashlib.sha256(packed).hexdigest(),json_sha256=hashlib.sha256(raw).hexdigest())
        folder=self.root/'rankings'
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'v880_full_results.json.gz').write_bytes(packed)
        for name,obj in [('latest_research.json',research),('v883_gate_dispatch.json',dispatch),
                         ('v884_evidence_progress.json',probe)]:
            (folder/name).write_text(json.dumps(obj))

    def progress_fixture(self, rows=None):
        research=dict(model='V8.10.2',estimate_vintage=STAMP,financial_last_quarter='2026-Q2',
            asof_price_date='2026-10-19',formal_Aplus_count=0,data_scope={'model_rows':2})
        dispatch=dict(vintage=STAMP,price_date='2026-10-19',tracked_issuer_count=2,eligible_research_count=1,
            all_issuer_jobs=[dict(code='6206',name='飛捷',market='TWSE',research_upside_pct=42),
                            dict(code='9802',name='鈺齊-KY',market='TWSE',research_upside_pct=None)])
        probe=dict(estimate_vintage=STAMP,asof_price_date='2026-10-19',top_priority_evidence=[])
        self.save_snapshot(research,dispatch,probe,rows)

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

    def test_one_incomplete_gate_does_not_discard_a_valid_failure(self):
        valid=copy.deepcopy(self.item['gates']['original_eight_quarter_statements'])
        valid['status']='FAIL'
        self.item['gates']['original_eight_quarter_statements']=valid
        self.item['gates']['nonoperating_components']={'status':'PENDING'}
        self.file.write_text(json.dumps(self.item))
        report=mod.emit_certificates(self.root,mod.timestamp(STAMP),'2026-Q2')[0]
        self.assertEqual(report['status'],'CERTIFICATE_PARTIALLY_ADMITTED')
        self.assertIn('nonoperating_components',report['rejected_gates'])
        cert=mod.load(self.root/'evidence/v880/certificates/6206.json')
        status=mod.certify('6206',40,None,cert['gates'],STAMP,'2026-Q2')
        self.assertEqual(status['gates_failed'],['original_eight_quarter_statements'])
        self.assertFalse(status['formal_Aplus'])

    def test_rejected_replacement_revokes_previously_valid_certificate(self):
        mod.emit_certificates(self.root,mod.timestamp(STAMP),'2026-Q2')
        self.item['gates']['original_eight_quarter_statements']['review_completed']=False
        self.file.write_text(json.dumps(self.item))
        result=mod.emit_certificates(self.root,mod.timestamp(STAMP),'2026-Q2')[0]
        self.assertTrue(result['previous_certificate_revoked'])
        self.assertFalse((self.root/'evidence/v880/certificates/6206.json').exists())

    def test_partial_replacement_never_merges_old_pass_for_invalid_gate(self):
        self.item['gates']['nonoperating_components']=copy.deepcopy(
            self.item['gates']['original_eight_quarter_statements'])
        self.file.write_text(json.dumps(self.item))
        mod.emit_certificates(self.root,mod.timestamp(STAMP),'2026-Q2')
        self.item['gates']['nonoperating_components']['expires_at']='2026-10-19T13:00:00+00:00'
        self.file.write_text(json.dumps(self.item))
        result=mod.emit_certificates(self.root,mod.timestamp(STAMP),'2026-Q2')[0]
        self.assertEqual(result['status'],'CERTIFICATE_PARTIALLY_ADMITTED')
        cert=mod.load(self.root/'evidence/v880/certificates/6206.json')
        self.assertEqual(list(cert['gates']),['original_eight_quarter_statements'])

    def test_bad_company_does_not_block_another_company(self):
        other=copy.deepcopy(self.item)
        other['code']='9802'
        other['gates']['original_eight_quarter_statements']['issuer']='9802'
        (self.file.parent/'9802.json').write_text(json.dumps(other))
        self.file.write_text('invalid json')
        results=mod.emit_certificates(self.root,mod.timestamp(STAMP),'2026-Q2')
        self.assertEqual([r['status'] for r in results],['REVIEW_PACK_REJECTED','CERTIFICATE_EMITTED'])

    def test_report_uses_effective_model_gates_instead_of_raw_certificate(self):
        mod.emit_certificates(self.root,mod.timestamp(STAMP),'2026-Q2')
        # Raw certificate says PASS, but the published engine invalidated it
        # after a new unreviewed self-report. The report must keep PENDING.
        gates={'original_eight_quarter_statements':{'status':'PENDING',
                'reason':'LATEST_SELF_REPORT_IS_NOT_REVIEWED_QUARTERLY_STATEMENTS'}}
        row=dict(code='6206',market='TWSE',financial_period='2026-Q3',
                 reviewed_financial_period='2026-Q2',scenario_upside_pct=42,gates=gates)
        row['certification']=mod.certify('6206',42,None,gates,STAMP,'2026-Q3')
        missing=dict(code='9802',market='TWSE',scenario_upside_pct=None,
                     status='CURRENT_FINANCIAL_STATEMENT_MISSING')
        self.progress_fixture([row,missing])
        report=mod.build_progress(self.root)
        stock=next(x for x in report['issuer_diagnostics'] if x['code']=='6206')
        self.assertEqual(stock['financial_period'],'2026-Q3')
        self.assertEqual(stock['formally_passed_gates'],[])
        self.assertEqual(stock['gate_stage']['original_eight_quarter_statements']['model_reason'],
                         gates['original_eight_quarter_statements']['reason'])

    def test_report_includes_focus_issuer_without_valuation_as_not_evaluated(self):
        self.progress_fixture()
        report=mod.build_progress(self.root)
        missing=next(x for x in report['issuer_diagnostics'] if x['code']=='9802')
        self.assertIsNone(missing['research_upside_pct'])
        self.assertFalse(missing['model_evaluated'])
        self.assertEqual(report['not_evaluated_issuer_count'],1)
        self.assertEqual(report['gate_summary']['forecast_bridge']['NOT_EVALUATED'],1)
        self.assertIn('無可比估值',mod.render_md(report,[]))

    def test_progress_rejects_modified_full_snapshot(self):
        self.progress_fixture()
        (self.root/'rankings/v880_full_results.json.gz').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'CACHE_FULL_RESULTS_HASH_MISMATCH'):
            mod.build_progress(self.root)

    def test_corrupt_issuer_bundle_does_not_halt_other_issuers(self):
        self.progress_fixture()
        validate=mod.validate_bundle
        def checked(root,code):
            if code=='9802':raise ValueError('DURABLE_ORIGINAL_PDF_HASH_OR_SIZE_MISMATCH')
            return validate(root,code)
        with patch.object(mod,'validate_bundle',side_effect=checked):
            report=mod.build_progress(self.root)
        self.assertEqual(report['tracked_issuer_count'],2)
        self.assertEqual(report['source_rejections'][0]['code'],'9802')
        self.assertFalse(report['durable_original_archive_receipts']['9802']['original_archive_hashes_verified'])

    def test_changed_original_revokes_only_that_gate_in_current_audit(self):
        certificate=mod.validate_review_pack(self.item,self.file,self.root,mod.timestamp(STAMP),'2026-Q2')
        row=dict(code='6206',market='TWSE',financial_period='2026-Q2',scenario_upside_pct=42,
                 gates=certificate['gates'])
        row['certification']=mod.certify('6206',42,None,row['gates'],STAMP,'2026-Q2')
        missing=dict(code='9802',market='TWSE',scenario_upside_pct=None,
                     status='CURRENT_FINANCIAL_STATEMENT_MISSING')
        self.progress_fixture([row,missing])
        self.original.write_bytes(b'tampered after publication')
        report=mod.build_progress(self.root)
        stock=next(x for x in report['issuer_diagnostics'] if x['code']=='6206')
        self.assertEqual(stock['formally_passed_gates'],[])
        self.assertIn('original_eight_quarter_statements',stock['still_pending_gates'])
        self.assertTrue(report['requires_model_refresh_after_source_rejection'])

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
        self.save_snapshot(research,dispatch,probe)
        results=mod.build_progress(self.root)
        self.assertEqual(results["high_upside_research_candidates"],1)
        self.assertEqual(results["formally_certified_Aplus_in_report"],0)
        stages=results["issuer_diagnostics"][0]["gate_stage"]
        self.assertEqual(stages["original_eight_quarter_statements"]["stage"],"MIRROR_CAPTURED")
        self.assertEqual(stages["tradability"]["stage"],"SOURCE_CAPTURED")
        self.assertFalse(stages["tradability"]["formal_pass"])

    def test_durable_issuer_originals_advance_source_stage_but_never_formal_pass(self):
        from scripts.v896_original_archive import collect
        source_dir=self.root/"ir/6206"
        source_dir.mkdir(parents=True)
        pdf_url="https://www.flytech.com.tw/data/investor_law/attached/1786525880605469429.pdf"
        source_dir.joinpath("manifest.json").write_text(json.dumps({
            "code":"6206","presentations":[{
                "event_date":"2026-08-12","title":"飛捷官方簡報",
                "source_url":pdf_url,"pdf_sha256":"0"*64}]}),encoding="utf-8")
        dummy_pdf=b"%PDF-1.4\\n"+b"original-test"*600+b"\\n%%EOF\\n"
        captured=collect(self.root,"6206","2026-10-20",
                         "2026-10-20T12:00:00+00:00",
                         fetcher=lambda *_:dummy_pdf)
        self.assertEqual(captured["records"],1)
        rank=self.root/"rankings"
        rank.mkdir(parents=True)
        research=dict(model="V8.8.2",
                      estimate_vintage="2026-10-20T12:30:00+00:00",
                      financial_last_quarter="2026-Q2",
                      asof_price_date="2026-10-19",formal_Aplus_count=0,
                      data_scope={"model_rows":1})
        job=dict(code="6206",name="飛捷",market="TWSE",research_upside_pct=45)
        dispatch=dict(vintage=research["estimate_vintage"],
                      price_date=research["asof_price_date"],
                      tracked_issuer_count=1,eligible_research_count=1,
                      all_issuer_jobs=[job])
        probe=dict(estimate_vintage=research["estimate_vintage"],
                   asof_price_date=research["asof_price_date"],
                   top_priority_evidence=[dict(
                       code="6206",market="TWSE",
                       financial=dict(normalized_income_8q_count=8,
                                      normalized_cashflow_8q_count=8),
                       capital=dict(issued_share_master_present=True,unverified_bond_terms=[]),
                       market_history=dict(twenty_day=None))])
        self.save_snapshot(research,dispatch,probe)
        report=mod.build_progress(self.root)
        stock=report["issuer_diagnostics"][0]
        self.assertEqual(stock["gate_stage"]["management_promises"]["stage"],"SOURCE_CAPTURED")
        self.assertFalse(stock["gate_stage"]["management_promises"]["formal_pass"])
        self.assertEqual(report["durable_original_archive_receipts"]["6206"]["records"],1)
        self.assertEqual(report["formally_certified_Aplus_in_report"],0)
        self.assertEqual(stock["formally_passed_gates"],[])

if __name__=="__main__":
    unittest.main()
