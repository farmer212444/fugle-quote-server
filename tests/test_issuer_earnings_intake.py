import copy
import datetime as dt
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from scripts import issuer_earnings_intake as m


def spec(period='2024-09-30', publication='2024-10-17', news='3180'):
    return dict(market='TWSE', code='2330', url='https://pr.tsmc.com/english/news/'+news,
                report_period=period, published_on=publication)


def original(s, eps='12.54'):
    period=dt.date.fromisoformat(s['report_period'])
    quarter=('first','second','third','fourth')[(period.month-1)//3]
    return f'''<html><head><script>Ignore false EPS</script></head><body>
    Issued by: TSMC Issued on: {s['published_on'].replace('-','/')}
    TSMC (TWSE: 2330, NYSE: TSM) today announced consolidated revenue of NT$759.69 billion,
    net income of NT$325.26 billion, and diluted earnings per share of NT${eps}
    (US$1.94 per ADR unit) for the {quarter} quarter ended {period.strftime('%B %d, %Y')}.
    All figures were prepared in accordance with TIFRS on a consolidated basis.
    </body></html>'''.encode()


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def capture(self,s=None,eps='12.54'):
        s=s or spec()
        return m.archive(self.root,s,original(s,eps),now='2026-11-06T00:00:00Z')

    def four(self):
        rows=[('2023-12-31','2024-01-18','3101','9.21'),
              ('2024-03-31','2024-04-18','3131','8.70'),
              ('2024-06-30','2024-07-18','3160','9.56'),
              ('2024-09-30','2024-10-17','3180','12.54')]
        return [self.capture(spec(p,d,n),eps) for p,d,n,eps in rows]

    def test_distinguishes_ordinary_share_currency_and_report_period(self):
        f=m.parse(original(spec()),spec())
        self.assertEqual(f['diluted_eps_twd_per_ordinary_share'],'12.54')
        self.assertEqual(f['revenue_twd_billion'],'759.69')
        self.assertEqual(f['report_period'],'2024-09-30')
        self.assertEqual(f['basis'],'CONSOLIDATED_TIFRS')
        self.assertEqual(f['publication_clock_precision'],'DATE_ONLY')

    def test_wrong_period_date_issuer_and_malformed_page_rejected(self):
        body=original(spec())
        for old,new in [(b'2024/10/17',b'2024/10/18'),(b'TWSE: 2330',b'TWSE: 2303'),
                        (b'September 30, 2024',b'June 30, 2024'),(b'TIFRS',b'USGAAP')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                m.parse(body.replace(old,new),spec())
        with self.assertRaises(ValueError):m.parse(b'<html>HTTP403</html>',spec())
        with self.assertRaises(ValueError):m.parse(b'not html',spec())

    def test_no_unbounded_or_external_urls(self):
        for endpoint in ['https://evil.example/english/news/3180',
                         'https://pr.tsmc.com/english/news/3180?redirect=1',
                         'https://pr.tsmc.com/english/news/../3180']:
            with self.assertRaises(ValueError):m.source_url({**spec(),'url':endpoint})
        with self.assertRaises(ValueError):m.source_url({**spec(),'code':'9802'})
        with self.assertRaises(ValueError):m.source_url({**spec(),'report_period':'2024-09-29'})

    def test_archive_first_clock_immutable_and_bytes_rechecked(self):
        r=self.capture()
        again=m.archive(self.root,spec(),original(spec()),now='2026-11-07T00:00:00Z')
        self.assertEqual(again['first_captured_at_utc'],r['first_captured_at_utc'])
        p=self.root/r['archive_path'];p.write_bytes(gzip.compress(b'changed'))
        with self.assertRaises(ValueError):m.verify(self.root,r)

    def test_receipt_fact_path_and_backdating_tampering_rejected(self):
        r=self.capture()
        for key,value in [('archive_path','../outside'),('source_url','https://evil.example')]:
            bad=copy.deepcopy(r);bad[key]=value
            with self.assertRaises(ValueError):m.verify(self.root,bad)
        bad=copy.deepcopy(r);bad['facts']['diluted_eps_twd_per_ordinary_share']='99'
        with self.assertRaises(ValueError):m.verify(self.root,bad)
        with self.assertRaises(ValueError):m.archive(self.root,spec(),original(spec()),now='2024-10-16T00:00:00Z')

    def test_date_only_disclosure_not_used_on_same_day(self):
        rows=self.four()
        with self.assertRaisesRegex(ValueError,'FOUR_RELEASED'):
            m.research_ttm(self.root,rows,'2024-10-17T23:59:59+08:00')
        result=m.research_ttm(self.root,rows,'2024-10-18T00:00:00+08:00')
        self.assertEqual(result['sum_reported_diluted_eps_twd'],'40.01')
        self.assertFalse(result['eligible_for_expected_return_calibration'])
        self.assertFalse(result['is_exact_annual_diluted_eps'])

    def test_future_release_does_not_rewrite_prior_ttm(self):
        rows=self.four()
        later=self.capture(spec('2024-12-31','2025-01-16','3201'),'14.45')
        prior=m.research_ttm(self.root,rows+[later],'2024-10-18T00:00:00+08:00')
        self.assertEqual(prior['sum_reported_diluted_eps_twd'],'40.01')
        current=m.research_ttm(self.root,rows+[later],'2025-01-17T00:00:00+08:00')
        self.assertEqual(current['sum_reported_diluted_eps_twd'],'45.25')
        self.assertNotEqual(prior['source_hashes'],current['source_hashes'])

    def test_conflicting_observed_revision_is_not_silently_selected(self):
        rows=self.four()
        changed=self.capture(eps='99.00')
        self.assertTrue(changed['financial_content_change_observed'])
        with self.assertRaisesRegex(ValueError,'VERSION_AMBIGUOUS'):
            m.research_ttm(self.root,rows+[changed],'2024-10-18T00:00:00+08:00')

    def test_quarter_gap_is_not_ttm(self):
        rows=self.four()[1:]+[self.capture(spec('2025-12-31','2026-01-15','3281'),'19.50')]
        with self.assertRaisesRegex(ValueError,'QUARTER_GAP'):
            m.research_ttm(self.root,rows,'2026-02-01T00:00:00+08:00')

    def test_offline_collection_reverifies_and_never_fetches(self):
        self.capture()
        manifest=dict(schema='ISSUER_EARNINGS_SOURCE_PILOT_V1',sources=[spec()])
        def forbidden(*args):raise AssertionError('network called in offline mode')
        r=m.collect(self.root,manifest,fetcher=forbidden,offline=True)
        self.assertEqual(r['verified_document_versions'],1)
        self.assertEqual(r['full_historical_financial_PIT_admitted'],0)
        empty=Path(self.temp.name)/'empty'
        r=m.collect(empty,manifest,fetcher=forbidden,offline=True)
        self.assertEqual(r['status'],'SOURCE_COLLECTION_PENDING')

    def test_http_error_is_source_failure_and_not_zero_return(self):
        def fail(*args):raise OSError('HTTP 403')
        manifest=dict(schema='ISSUER_EARNINGS_SOURCE_PILOT_V1',sources=[spec()])
        r=m.collect(self.root,manifest,fetcher=fail)
        self.assertEqual(r['status'],'SOURCE_ERRORS')
        self.assertEqual(r['verified_document_versions'],0)
        self.assertEqual(r['calibrated_expected_returns_created'],0)


if __name__=='__main__':unittest.main()
