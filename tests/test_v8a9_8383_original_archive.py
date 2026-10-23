"""Bounded, offline-tested 8383 issuer-original PDF versioned SHA capture."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v8a9_8383_original_archive import (
    collect,verify_archive,validate_pdf,expected_sources)
from tw_model_v880.auditor_watch import load_scope_watches
from test_auditor_scope_watch import INCOME,CASH,RECEIPT


def sample_pdf(label):
    return b'%PDF-1.7\n'+label.encode('ascii')+b'\n'+b'0'*7000+b'\n%%EOF\n'


class IssuerOriginalArchiveTests(unittest.TestCase):
    def workspace(self):
        tmp=tempfile.TemporaryDirectory()
        root=Path(tmp.name)/'tw-market-data'
        watch_path=root/'evidence/v880/auditor_scope_watch/8383.json'
        watch_path.parent.mkdir(parents=True)
        watch=json.loads(RECEIPT.read_text(encoding='utf-8'))
        watch_path.write_text(json.dumps(watch,ensure_ascii=False),encoding='utf-8')
        return tmp,root,watch

    def test_two_quarters_stored_and_immutable_deduplicated(self):
        tmp,root,watch=self.workspace()
        with tmp:
            urls={p:url for p,url,_ in expected_sources(watch)}
            docs={urls['2026-Q1']:sample_pdf('Q1'),urls['2026-Q2']:sample_pdf('Q2')}
            fetcher=lambda url:docs[url]
            report=collect(root,asof_day='2026-10-23',
                           now='2026-10-23T15:30:00+00:00',fetcher=fetcher)
            self.assertTrue(report['original_pdf_bytes_hashed'])
            self.assertEqual(report['verified_periods'],['2026-Q1','2026-Q2'])
            manifest_path=root/'evidence/v880/originals/8383/manifest.json'
            before=manifest_path.read_bytes()
            again=collect(root,asof_day='2026-10-23',
                          now='2026-10-23T15:40:00+00:00',fetcher=fetcher)
            self.assertEqual(before,manifest_path.read_bytes())
            self.assertEqual(len(json.loads(before)['documents']),2)
            self.assertFalse(again['formal_auditor_scope_gate_pass'])
            self.assertFalse(again['MOPS_PIT_verified'])
            income={('TPEX','8383'):{'2026-Q2':INCOME}}
            cash={('TPEX','8383'):{'2026-Q2':CASH}}
            a,errors=load_scope_watches(root,'2026-10-23',income,cash)
            self.assertFalse(errors)
            self.assertTrue(a['8383']['issuer_original_pdf_bytes_hashed'])
            self.assertFalse(a['8383']['formal_auditor_scope_pass'])

    def test_original_revision_keeps_old_sha_version(self):
        tmp,root,watch=self.workspace()
        with tmp:
            urls={p:url for p,url,_ in expected_sources(watch)}
            docs={urls['2026-Q1']:sample_pdf('Q1'),urls['2026-Q2']:sample_pdf('Q2')}
            collect(root,asof_day='2026-10-23',
                    now='2026-10-23T15:30:00+00:00',fetcher=lambda url:docs[url])
            docs[urls['2026-Q2']]=sample_pdf('Q2_CHANGED')
            collect(root,asof_day='2026-10-23',
                    now='2026-10-23T15:40:00+00:00',fetcher=lambda url:docs[url])
            m=json.loads((root/'evidence/v880/originals/8383/manifest.json').read_text())
            self.assertEqual(len(m['documents']),3)
            self.assertEqual(sum(e['period']=='2026-Q2' for e in m['documents']),2)
            self.assertTrue(verify_archive(root,watch)['original_pdf_bytes_hashed'])

    def test_modified_original_bytes_fail_checksum_without_fake_pass(self):
        tmp,root,watch=self.workspace()
        with tmp:
            urls={p:url for p,url,_ in expected_sources(watch)}
            docs={urls['2026-Q1']:sample_pdf('Q1'),urls['2026-Q2']:sample_pdf('Q2')}
            collect(root,asof_day='2026-10-23',
                    now='2026-10-23T15:30:00+00:00',fetcher=lambda url:docs[url])
            m=json.loads((root/'evidence/v880/originals/8383/manifest.json').read_text())
            b=root/m['documents'][0]['archive_path']
            b.write_bytes(sample_pdf('CORRUPTED'))
            with self.assertRaisesRegex(ValueError,'8383_ARCHIVE_PDF_SHA_OR_LENGTH_MISMATCH'):
                verify_archive(root,watch)

    def test_unavailable_pdf_keeps_incomplete_status(self):
        tmp,root,watch=self.workspace()
        with tmp:
            urls={p:url for p,url,_ in expected_sources(watch)}
            def fetch(url):
                if url==urls['2026-Q1']:return sample_pdf('Q1')
                raise OSError('publisher not reachable')
            out=collect(root,asof_day='2026-10-23',
                        now='2026-10-23T15:30:00+00:00',fetcher=fetch)
            self.assertFalse(out['original_pdf_bytes_hashed'])
            self.assertEqual(out['verified_periods'],['2026-Q1'])

    def test_forged_issuer_url_cannot_be_archived(self):
        tmp,root,watch=self.workspace()
        with tmp:
            bad=copy.deepcopy(watch)
            bad['source_pdf_url']='https://example.com/fake.pdf'
            with self.assertRaisesRegex(ValueError,'8383_INVALID_ISSUER_PDF_SOURCE'):
                expected_sources(bad)
            with self.assertRaisesRegex(ValueError,'8383_ARCHIVE_CANNOT_BACKDATE'):
                collect(root,asof_day='2026-10-22',
                        now='2026-10-23T15:30:00+00:00',
                        fetcher=lambda _:sample_pdf('Q1'))

    def test_pdf_validation_rejects_nondoc(self):
        with self.assertRaisesRegex(ValueError,'8383_PDF_INVALID_OR_OVERSIZED'):
            validate_pdf(b'<html>status</html>')


if __name__=='__main__':
    unittest.main()
