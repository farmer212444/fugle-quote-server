import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.refresh_top10_sources import reconcile
from tw_model_v880.early_bulk import FOLDER


class Top10SourceRefreshTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'rankings').mkdir()
        (self.root / FOLDER).mkdir(parents=True)

    def ranking(self, codes):
        (self.root / 'rankings/latest_research.json').write_text(
            json.dumps(dict(top10_market_research=[dict(code=c) for c in codes])))

    def captured(self, codes):
        (self.root / FOLDER / 'manifest.json').write_text(
            json.dumps(dict(requested_issuers=[dict(code=c) for c in codes])))

    def test_already_covered_ranking_needs_no_network_or_recalculation(self):
        self.ranking(['1000']); self.captured(['1000'])
        result = reconcile(self.root, lambda _: self.fail('unnecessary network'),
                           lambda: self.fail('unnecessary recalculation'))
        self.assertEqual(result['source_refreshes'], 0)
        self.assertFalse(result['formal_quality_pass'])

    def test_new_candidates_are_rechecked_until_scope_covers_final_ranking(self):
        self.ranking(['2000']); self.captured(['1000'])
        calls = []
        def refresh(codes):
            calls.append(codes)
            self.captured(codes)
        def rerun():
            self.ranking(['3000'])
        result = reconcile(self.root, refresh, rerun)
        self.assertEqual(calls, [['1000', '2000'], ['1000', '2000', '3000']])
        self.assertEqual(result['codes'], ['3000'])
        self.assertEqual(result['source_refreshes'], 2)

    def test_failed_source_refresh_never_triggers_a_recalculation_or_completion(self):
        self.ranking(['2000']); self.captured(['1000'])
        def refresh(_):
            raise subprocess.CalledProcessError(1, ['source unavailable'])
        with self.assertRaises(subprocess.CalledProcessError):
            reconcile(self.root, refresh, lambda: self.fail('failed refresh cannot be used'))
        self.assertEqual(json.loads((self.root / FOLDER / 'manifest.json').read_bytes())['requested_issuers'],
                         [dict(code='1000')])

    def test_continually_changing_top10_stops_at_bound_instead_of_publishing_stale_scope(self):
        self.ranking(['2000']); self.captured(['1000'])
        count = 0
        def rerun():
            nonlocal count
            count += 1
            self.ranking([str(2000 + count)])
        with self.assertRaisesRegex(ValueError, 'NOT_STABLE_WITHIN_BOUND'):
            reconcile(self.root, self.captured, rerun, max_passes=2)
        self.assertEqual(count, 2)

    def test_empty_or_unbounded_requests_are_rejected(self):
        self.ranking([])
        with self.assertRaisesRegex(ValueError, 'EMPTY'):
            reconcile(self.root, self.captured, lambda: None)
        with self.assertRaisesRegex(ValueError, 'BOUND_INVALID'):
            reconcile(self.root, self.captured, lambda: None, max_passes=0)
