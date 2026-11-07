"""Reparse the actual issuer PDFs, not generated financial outcome fixtures."""
import copy
import datetime as dt
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from scripts import issuer_earnings_intake as m

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'


class OriginalPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads((ROOT/'config/issuer_pdf_downloads_v1.json').read_bytes())
        cls.records=m.imported_pdf_receipts(ROOT,cls.manifest)

    def test_reparse_six_actual_official_documents(self):
        expected={'2023-12-31':'9.21','2024-03-31':'8.70','2024-06-30':'9.56',
                  '2024-09-30':'12.54','2024-12-31':'14.45','2025-12-31':'19.50'}
        self.assertEqual(len(self.records),6)
        self.assertEqual({r['facts']['report_period']:r['facts']['diluted_eps_twd_per_ordinary_share']
                          for r in self.records},expected)
        for r in self.records:
            self.assertEqual(m.verify(ROOT,r),r['facts'])
            self.assertFalse(r['historical_version_at_publication_verified'])
            self.assertFalse(r['full_historical_financial_PIT_admitted'])

    def test_date_aware_replay_on_actual_originals(self):
        result=m.research_ttm(ROOT,self.records,'2024-10-18T00:00:00+08:00')
        self.assertEqual(result['sum_reported_diluted_eps_twd'],'40.01')
        self.assertFalse(result['eligible_for_expected_return_calibration'])
        self.assertNotIn('2025-12-31',result['report_periods'])
        with self.assertRaisesRegex(ValueError,'FOUR_RELEASED_QUARTERS'):
            m.research_ttm(ROOT,self.records,'2024-10-17T23:59:59+08:00')
        updated=m.research_ttm(ROOT,self.records,'2025-01-17T00:00:00+08:00')
        self.assertEqual(updated['sum_reported_diluted_eps_twd'],'45.25')

    def test_wrong_document_period_and_published_date_rejected(self):
        r=self.records[0];raw=gzip.decompress((ROOT/r['archive_path']).read_bytes())
        for update in [{'published_on':'2024-10-18'}, {'report_period':'2024-06-30'}]:
            with self.subTest(update=update),self.assertRaises(ValueError):
                m.parse_pdf(raw,{**r['requested_spec'],**update})

    def test_hash_url_scope_and_self_certification_tampering_rejected(self):
        first=self.manifest['records'][0]
        changes=[{'raw_sha256':'f'*64},{'source_url':'https://evil.example/x.pdf'},
                 {'archive_path':'../outside'}, {'source_page':'https://pr.tsmc.com/english/news/3101'},
                 {'historical_version_at_publication_verified':True},
                 {'first_captured_at_utc':'2099-01-01T00:00:00Z'}]
        for change in changes:
            bad=copy.deepcopy(self.manifest);bad['records'][0].update(change)
            with self.subTest(change=change),self.assertRaises((ValueError,OSError)):
                m.imported_pdf_receipts(ROOT,bad)

    def test_offline_command_replays_archives_without_network(self):
        pilot=json.loads((ROOT/'config/issuer_earnings_sources_v1.json').read_bytes())
        def forbidden(*args):raise AssertionError('Network not permitted in archive verification')
        r=m.collect(ROOT,pilot,fetcher=forbidden,offline=True)
        self.assertEqual(r['status'],'ISSUER_ORIGINALS_CAPTURED')
        self.assertEqual(r['verified_pdf_originals'],6)
        self.assertEqual(r['full_historical_financial_PIT_admitted'],0)
        self.assertEqual(r['calibrated_expected_returns_created'],0)


if __name__=='__main__':unittest.main()
