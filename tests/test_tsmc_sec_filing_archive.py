"""SEC corroboration fixtures are synthetic, never real issuer evidence."""
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from scripts import tsmc_sec_filing_archive as mod


class SECIntakeTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name);self.calls=[]
        self.url_to_quarter={v:k for k,v in mod.FILING_URLS.items()}

    def fixture(self,quarter):
        y,q=int(quarter[:4]),int(quarter[-1])
        period=f'{mod.MONTHS[q]} {mod.DAYS[q]}, {y}'
        sections=' '.join([
            'Taiwan Semiconductor Manufacturing Company Limited and Subsidiaries',
            'Consolidated Balance Sheets',
            'Consolidated Statements of Comprehensive Income',
            'Consolidated Statements of Changes in Equity',
            'Consolidated Statements of Cash Flows',
            'Notes to Consolidated Financial Statements',period])
        return ('<html><body>'+sections+'<p>'+('Synthetic not issuer data. '*3900)+
                '</p></body></html>').encode('utf-8')

    def fetch(self,url):
        self.calls.append(url)
        return self.fixture(self.url_to_quarter[url])

    def collect(self,**k):
        return mod.collect(self.root,fetcher=k.get('fetcher',self.fetch),
                           pause=lambda n:None)

    def test_exact_seven_sec_exhibits_sha_stored_not_certified(self):
        out=self.collect()
        self.assertEqual(out['archived_quarters'],sorted(mod.FILING_URLS))
        self.assertEqual(out['sec_translated_exhibits_verified'],7)
        self.assertFalse(out['formal_gate_pass'])
        self.assertFalse(out['original_full_content_review_complete'])
        self.assertTrue(out['chinese_original_pdf_gate_unmodified'])
        self.calls.clear()
        again=self.collect()
        self.assertEqual(self.calls,[])
        self.assertEqual(again['archived_quarters'],out['archived_quarters'])

    def test_source_mismatch_does_not_create_false_original(self):
        def mismatch(url):
            if self.url_to_quarter[url]=='2025-Q3':
                return self.fixture('2025-Q2')
            return self.fetch(url)
        out=self.collect(fetcher=mismatch)
        self.assertEqual(out['missing_quarters'],['2025-Q3'])
        self.assertEqual(len(out['source_errors']),1)
        self.assertFalse(out['formal_gate_pass'])
        again=self.collect()
        self.assertFalse(again['missing_quarters'])

    def test_403_is_recorded_without_fake_coverage(self):
        def denied(url):
            raise OSError('HTTP 403 Forbidden')
        out=self.collect(fetcher=denied)
        self.assertEqual(out['sec_translated_exhibits_verified'],0)
        self.assertEqual(len(out['source_errors']),7)
        self.assertFalse(out['formal_gate_pass'])

    def test_403_cooldown_skips_repeated_requests_and_retries_after_one_day(self):
        start=dt.datetime(2026,11,8,12,0,tzinfo=dt.timezone.utc)
        calls=[]
        def denied(url):
            calls.append(url)
            raise OSError('HTTP 403 Forbidden')
        def attempt(when):
            return mod.collect(self.root,fetcher=denied,clock=lambda:when,pause=lambda n:None)
        first=attempt(start)
        self.assertEqual(len(calls),7)
        self.assertEqual(len(first['source_errors']),7)
        self.assertEqual(first['http403_retry_deferred_quarters'],[])
        calls.clear()
        repeat=attempt(start+dt.timedelta(hours=3))
        self.assertEqual(calls,[])
        self.assertEqual(len(repeat['source_errors']),7)
        self.assertEqual(repeat['http403_retry_deferred_quarters'],
                         sorted(mod.FILING_URLS))
        self.assertFalse(repeat['formal_gate_pass'])
        calls.clear()
        attempt(start+dt.timedelta(hours=23))
        self.assertEqual(calls,[])
        after=attempt(start+dt.timedelta(hours=24,minutes=1))
        self.assertEqual(len(calls),7)
        self.assertEqual(len(after['source_errors']),7)
        self.assertEqual(after['http403_retry_deferred_quarters'],[])

    def test_legacy_403_manifest_cooldown_does_not_extend_on_poll(self):
        start=dt.datetime(2026,11,8,12,0,tzinfo=dt.timezone.utc)
        def denied(url):
            raise OSError('HTTP 403 Forbidden')
        mod.collect(self.root,fetcher=denied,clock=lambda:start,pause=lambda n:None)
        manifest=self.root/mod.FOLDER/'manifest.json'
        data=json.loads(manifest.read_text())
        del data['last_network_attempt_at_utc']
        manifest.write_text(json.dumps(data))
        calls=[]
        def track(url):
            calls.append(url)
            return self.fixture(self.url_to_quarter[url])
        mod.collect(self.root,fetcher=track,
                    clock=lambda:start+dt.timedelta(hours=7),pause=lambda n:None)
        mod.collect(self.root,fetcher=track,
                    clock=lambda:start+dt.timedelta(hours=18),pause=lambda n:None)
        self.assertEqual(calls,[])
        recovered=mod.collect(self.root,fetcher=track,
                    clock=lambda:start+dt.timedelta(hours=25),pause=lambda n:None)
        self.assertEqual(len(calls),7)
        self.assertEqual(recovered['sec_translated_exhibits_verified'],7)
        self.assertFalse(recovered['formal_gate_pass'])

    def test_non403_source_error_is_retryable_without_cooldown(self):
        start=dt.datetime(2026,11,8,12,0,tzinfo=dt.timezone.utc)
        attempts=[]
        def down(url):
            attempts.append(url)
            raise OSError('HTTP Error 503: Service Unavailable')
        mod.collect(self.root,fetcher=down,clock=lambda:start,pause=lambda n:None)
        second=mod.collect(self.root,fetcher=down,
                    clock=lambda:start+dt.timedelta(minutes=2),pause=lambda n:None)
        self.assertEqual(len(attempts),14)
        self.assertEqual(second['http403_retry_deferred_quarters'],[])
        self.assertEqual(second['sec_translated_exhibits_verified'],0)

    def test_mutated_sha_archive_is_rejected(self):
        out=self.collect()
        file=self.root/out['documents'][0]['archive_path']
        file.write_bytes(file.read_bytes()+b'bad')
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):
            self.collect()

    def test_wrong_issuer_and_unlisted_url_not_admitted(self):
        for q in mod.FILING_URLS:
            wrong=self.fixture(q).replace(
                b'Taiwan Semiconductor Manufacturing Company Limited',
                b'Another Manufacturing Company Limited')
            with self.subTest(q=q),self.assertRaisesRegex(ValueError,'MISMATCH'):
                mod.identity(wrong,q)
        with self.assertRaisesRegex(ValueError,'URL_NOT_ALLOWLISTED'):
            mod.fetch('https://example.com/untrusted')


if __name__=='__main__':unittest.main()
