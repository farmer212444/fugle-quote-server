import json
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
                       model_source_state=model_source_state(self.root),input_receipts=[])
        self.write(self.meta)

    def write(self,meta):
        (self.root/'rankings/latest_research.json').write_text(json.dumps(meta))

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

    def test_bad_rebuild_is_not_reported_as_fixed(self):
        self.write(dict(self.meta,model='V8.8.2'))
        with self.assertRaisesRegex(ValueError,'STILL_STALE'):
            ensure_current(self.root,'2026-10-21T12:00:00+08:00',runner=Mock())

    def test_old_worker_dependency_state_does_not_poison_current_cache(self):
        old=dict(self.meta,runtime_dependencies={'PyMuPDF':'SYNTHETIC_OLD_ENVIRONMENT'})
        self.assertIn('RUNTIME_DEPENDENCIES_CHANGED',stale_reasons(self.root,old))


if __name__=='__main__':unittest.main()
