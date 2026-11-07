"""SEC corroboration fixtures are synthetic, never real issuer evidence."""
import copy
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
