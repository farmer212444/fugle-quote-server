import json
import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.ensure_research_current import ensure_current,stale_reasons
from tw_model_v880 import VERSION
from tw_model_v880.data import model_source_state
from tw_model_v880.provenance import code_fingerprint,runtime_dependencies


class CacheRefresh(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ('prices/latest_manifest.json','fundamentals/latest_scan.json','latest_manifest.json','evidence/v880/manifest.json'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
        (self.root/'rankings').mkdir()
        self.meta=dict(model=VERSION,model_code_sha256=code_fingerprint(),runtime_dependencies=runtime_dependencies(),target_date='2027-12-31',
                       estimate_vintage='2026-10-21T09:00:00+08:00',asof_price_date='2026-10-20',
                       model_source_state=model_source_state(self.root),input_receipts=[],data_scope=dict(model_rows=0))
        self.meta=self.write(self.meta)

    def write(self,meta):
        meta=dict(meta)
        full={k:v for k,v in meta.items() if k!='full_results'}
        full['all_model_rows']=[]
        raw=json.dumps(full).encode();packed=gzip.compress(raw,mtime=0)
        (self.root/'rankings/v880_full_results.json.gz').write_bytes(packed)
        meta['full_results']=dict(path='v880_full_results.json.gz',sha256=hashlib.sha256(packed).hexdigest(),
                                  json_sha256=hashlib.sha256(raw).hexdigest())
        (self.root/'rankings/latest_research.json').write_text(json.dumps(meta))
        return meta

    def test_current_model_and_source_cache_is_reused(self):
        runner=Mock()
        result=ensure_current(self.root,'2026-10-21T12:00:00+08:00',runner=runner)
        self.assertFalse(result['rebuilt']);runner.assert_not_called()

    def test_old_version_cache_is_recomputed_before_export(self):
        self.write(dict(self.meta,model='V8.8.2'))
        runner=Mock(side_effect=lambda *args:self.write(self.meta))
        result=ensure_current(self.root,'2026-10-21T12:00:00+08:00',runner=runner)
        self.assertTrue(result['rebuilt']);runner.assert_called_once()
        self.assertIn('MODEL_VERSION_CHANGED',result['reasons'])

    def test_same_period_source_revision_invalidates_cache(self):
        (self.root/'latest_manifest.json').write_text('{"correction":true}')
        self.assertIn('SOURCE_MANIFEST_OR_LEDGER_CHANGED',stale_reasons(self.root,self.meta))

    def test_new_company_ledger_is_not_missed_because_old_receipts_lack_it(self):
        p=self.root/'evidence/v880/issuer_bridges/1111.json';p.parent.mkdir(parents=True);p.write_text('{}')
        self.assertIn('SOURCE_MANIFEST_OR_LEDGER_CHANGED',stale_reasons(self.root,self.meta))

    def test_governance_event_and_archived_source_revision_invalidate_cache(self):
        p=self.root/'evidence/v880/governance/1111.json';p.parent.mkdir(parents=True)
        p.write_text(json.dumps(dict(events=[dict(updates=[dict(sources=[dict(archive_path='notice.html')])])])) )
        self.assertIn('SOURCE_MANIFEST_OR_LEDGER_CHANGED',stale_reasons(self.root,self.meta))
        prior=dict(self.meta,model_source_state=model_source_state(self.root))
        (self.root/'notice.html').write_text('new original source')
        self.assertIn('SOURCE_MANIFEST_OR_LEDGER_CHANGED',stale_reasons(self.root,prior))

    def test_bad_governance_archive_path_is_isolated_without_reading_outside_root(self):
        p=self.root/'evidence/v880/governance/1111.json';p.parent.mkdir(parents=True)
        p.write_text(json.dumps(dict(sources=[dict(archive_path='../outside.txt')])))
        state=model_source_state(self.root)
        self.assertIn('evidence/v880/governance/1111.json',state)
        self.assertNotIn('../outside.txt',state)

    def test_bad_rebuild_is_not_reported_as_fixed(self):
        self.write(dict(self.meta,model='V8.8.2'))
        with self.assertRaisesRegex(ValueError,'STILL_STALE'):
            ensure_current(self.root,'2026-10-21T12:00:00+08:00',runner=Mock())

    def test_old_worker_dependency_state_does_not_poison_current_cache(self):
        old=dict(self.meta,runtime_dependencies={'PyMuPDF':'SYNTHETIC_OLD_ENVIRONMENT'})
        self.assertIn('RUNTIME_DEPENDENCIES_CHANGED',stale_reasons(self.root,old))

    def test_explicit_target_change_rebuilds_instead_of_returning_last_year(self):
        runner=Mock(side_effect=lambda *args:self.write(dict(self.meta,target_date='2028-12-31')))
        result=ensure_current(self.root,'2026-10-21T12:00:00+08:00','2028-12-31',runner)
        self.assertTrue(result['rebuilt'])
        self.assertIn('FORECAST_TARGET_DATE_CHANGED',result['reasons'])
        self.assertEqual(runner.call_args.args[2],'2028-12-31')

    def test_rebuild_must_honor_the_requested_target(self):
        runner=Mock(side_effect=lambda *args:self.write(self.meta))
        with self.assertRaisesRegex(ValueError,'STILL_STALE'):
            ensure_current(self.root,'2026-10-21T12:00:00+08:00','2028-12-31',runner)

    def test_new_financial_detail_and_december_inputs_invalidate_cache(self):
        for name in ('fundamentals/2026-Q2/TWSE_income.json',
                     'financial_history/2025-Q4/TWSE_income_shard0.json','2025-12/revenue_0.json'):
            with self.subTest(name=name):
                path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
                self.assertIn('SOURCE_MANIFEST_OR_LEDGER_CHANGED',stale_reasons(self.root,self.meta))
                path.unlink()

    def test_changed_or_deleted_dynamic_input_is_detected_without_old_receipt(self):
        path=self.root/'fundamentals/2026-Q2/TWSE_cashflow.json';path.parent.mkdir(parents=True);path.write_text('{}')
        prior=dict(self.meta,model_source_state=model_source_state(self.root))
        path.write_text('{"restated":true}')
        self.assertIn('SOURCE_MANIFEST_OR_LEDGER_CHANGED',stale_reasons(self.root,prior))
        path.unlink()
        self.assertIn('SOURCE_MANIFEST_OR_LEDGER_CHANGED',stale_reasons(self.root,prior))

    def test_repaired_missing_original_or_changed_cb_bytes_invalidate_cache(self):
        ledger=self.root/'evidence/v880/capital_terms/1111.json';ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps(dict(sources=[dict(path='capital-original.json',sha256='a'*64)])))
        prior=dict(self.meta,model_source_state=model_source_state(self.root))
        self.assertIsNone(prior['model_source_state']['capital-original.json'])
        original=self.root/'capital-original.json';original.write_text('{}')
        self.assertIn('SOURCE_MANIFEST_OR_LEDGER_CHANGED',stale_reasons(self.root,prior))
        prior['model_source_state']=model_source_state(self.root)
        original.write_text('{"changed":true}')
        self.assertIn('SOURCE_MANIFEST_OR_LEDGER_CHANGED',stale_reasons(self.root,prior))

    def test_new_day_or_historical_cutoff_cannot_reuse_future_or_old_decisions(self):
        self.assertIn('EVALUATION_DATE_CHANGED',stale_reasons(self.root,self.meta,asof='2026-10-22T01:00:00+08:00'))
        self.assertIn('CACHE_ESTIMATE_FROM_FUTURE',stale_reasons(self.root,self.meta,asof='2026-10-21T08:59:59+08:00'))

    def test_crossing_price_publication_screen_within_day_rechecks_warning(self):
        self.assertIn('PRICE_FRESHNESS_CONTEXT_CHANGED',stale_reasons(self.root,self.meta,asof='2026-10-21T16:00:00+08:00'))

    def test_expiring_review_and_future_source_activation_in_same_day(self):
        path=self.root/'evidence/v880/certificates/1111.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(gates=dict(a=dict(expires_at='2026-10-21T10:00:00+08:00')))))
        prior=dict(self.meta,model_source_state=model_source_state(self.root))
        before=stale_reasons(self.root,prior,asof='2026-10-21T10:00:00+08:00')
        self.assertFalse(any(r.startswith('EVIDENCE_TIME_BOUNDARY_CROSSED') for r in before))
        after=stale_reasons(self.root,prior,asof='2026-10-21T10:00:00.000001+08:00')
        self.assertTrue(any(r.startswith('EVIDENCE_TIME_BOUNDARY_CROSSED') for r in after))
        path.write_text(json.dumps(dict(available_at='2026-10-21T10:00:00+08:00')))
        prior['model_source_state']=model_source_state(self.root)
        self.assertTrue(any(r.startswith('EVIDENCE_TIME_BOUNDARY_CROSSED') for r in
                            stale_reasons(self.root,prior,asof='2026-10-21T10:00:00+08:00')))

    def test_full_result_byte_change_is_not_a_current_cache(self):
        (self.root/'rankings/v880_full_results.json.gz').write_bytes(b'truncated')
        self.assertIn('CACHE_FULL_RESULTS_HASH_MISMATCH',stale_reasons(self.root,self.meta))

    def test_compact_target_change_cannot_hide_different_hashed_full_context(self):
        self.assertIn('CACHE_FULL_RESULTS_CONTEXT_MISMATCH',stale_reasons(self.root,dict(self.meta,target_date='2028-12-31')))

    def test_non_object_cache_rebuilds_and_unsafe_reference_is_rejected(self):
        self.assertEqual(stale_reasons(self.root,[]),['RESEARCH_CACHE_INVALID_DOCUMENT'])
        self.assertIn('CACHE_FULL_RESULTS_REFERENCE_INVALID',stale_reasons(self.root,dict(self.meta,full_results={'path':'../elsewhere.gz'})))

    def test_known_rejected_ledger_does_not_create_an_endless_global_rebuild(self):
        path=self.root/'evidence/v880/certificates/1111.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(available_at='INVALID_CLOCK_REJECTED_BY_MODEL')))
        prior=self.write(dict(self.meta,model_source_state=model_source_state(self.root)))
        self.assertEqual(stale_reasons(self.root,prior,asof='2026-10-21T12:00:00+08:00'),[])


if __name__=='__main__':unittest.main()
