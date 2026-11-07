"""Synthetic SGML fixtures; no fixture is a real regulatory filing."""
import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from scripts.sec_pit_intake import archive,collect,parse,source_url,verify

SPEC=dict(market='TWSE',code='2330',cik='1046179',conformed_name='SYNTHETIC FILER NOT REAL COMPANY',
          accession='0001046179-24-000116',form='6-K',report_period='20240930')
NOW='2026-11-07T00:00:00+00:00'


def fixture():
    return b'''<SEC-DOCUMENT>0001046179-24-000116.txt : 20241017
<SEC-HEADER>synthetic
<ACCEPTANCE-DATETIME>20241017061336
ACCESSION NUMBER: 0001046179-24-000116
CONFORMED SUBMISSION TYPE: 6-K
PUBLIC DOCUMENT COUNT: 2
CONFORMED PERIOD OF REPORT: 20240930
FILED AS OF DATE: 20241017
FILER:
\tCOMPANY DATA:
\t\tCOMPANY CONFORMED NAME: SYNTHETIC FILER NOT REAL COMPANY
\t\tCENTRAL INDEX KEY: 0001046179
</SEC-HEADER>
<DOCUMENT>
<TYPE>6-K
<SEQUENCE>1
<FILENAME>synthetic.htm
<TEXT>
<html>Engineering fixture only</html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-99.1
<SEQUENCE>2
<FILENAME>synthetic-exhibit.htm
<TEXT>
<html>Engineering fixture exhibit</html>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>
'''


class SubmissionIntake(unittest.TestCase):
    def test_header_proves_identity_period_clock_and_document_membership(self):
        p=parse(fixture(),SPEC)
        self.assertEqual(p['document_count'],2)
        self.assertEqual(p['accepted_at_utc'],'2024-10-17T10:13:36+00:00')
        self.assertEqual(p['documents'][1]['filename'],'synthetic-exhibit.htm')
        self.assertEqual(len(p['documents'][1]['segment_sha256']),64)

    def test_wrong_cik_accession_period_form_and_name_are_rejected(self):
        for key,value in [('cik','123'),('accession','0001046179-24-000999'),('report_period','20240630'),
                          ('form','20-F'),('conformed_name','OTHER')]:
            with self.subTest(key=key),self.assertRaises(ValueError):parse(fixture(),dict(SPEC,**{key:value}))

    def test_html_error_missing_header_and_mismatched_document_count_are_rejected(self):
        for raw in (b'<html>Access denied</html>',fixture().replace(b'PUBLIC DOCUMENT COUNT: 2',b'PUBLIC DOCUMENT COUNT: 3'),
                    fixture().replace(b'<ACCEPTANCE-DATETIME>20241017061336',b'')):
            with self.assertRaises(ValueError):parse(raw,SPEC)

    def test_duplicate_or_unsafe_documents_are_rejected(self):
        for raw in (fixture().replace(b'synthetic-exhibit.htm',b'synthetic.htm'),
                    fixture().replace(b'<SEQUENCE>2',b'<SEQUENCE>1'),
                    fixture().replace(b'synthetic-exhibit.htm',b'../escape.htm')):
            with self.assertRaises(ValueError):parse(raw,SPEC)

    def test_reuse_preserves_actual_first_capture_clock(self):
        with tempfile.TemporaryDirectory() as t:
            a=archive(t,SPEC,fixture(),NOW)
            b=archive(t,SPEC,fixture(),'2026-11-08T00:00:00+00:00')
            self.assertEqual(a,b);self.assertEqual(a['first_captured_at_utc'],NOW)
            self.assertFalse(a['full_historical_financial_PIT_admitted'])

    def test_changed_upstream_bytes_create_a_separate_version(self):
        with tempfile.TemporaryDirectory() as t:
            a=archive(t,SPEC,fixture(),NOW)
            b=archive(t,SPEC,fixture().replace(b'fixture exhibit',b'changed fixture exhibit'),NOW)
            self.assertNotEqual(a['raw_sha256'],b['raw_sha256'])
            self.assertTrue(b['post_acceptance_content_change_observed'])
            self.assertIn(a['raw_sha256'],b['prior_content_versions'])
            verify(t,a);verify(t,b)

    def test_tampered_archive_and_recomputed_metadata_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            a=archive(t,SPEC,fixture(),NOW);bad=copy.deepcopy(a);bad['parsed']['document_count']=9
            with self.assertRaisesRegex(ValueError,'PARSED_METADATA'):verify(t,bad)
            (Path(t)/a['archive_path']).write_bytes(gzip.compress(b'changed'))
            with self.assertRaisesRegex(ValueError,'BYTES_MISMATCH'):verify(t,a)

    def test_backdated_capture_and_path_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError,'AFTER_CAPTURE'):archive(t,SPEC,fixture(),'2020-01-01T00:00:00+00:00')
            a=archive(t,SPEC,fixture(),NOW);a['archive_path']='../escape.gz'
            with self.assertRaisesRegex(ValueError,'UNSAFE_PATH'):verify(t,a)

    def test_bounded_offline_mode_does_not_fetch_or_make_an_outcome(self):
        with tempfile.TemporaryDirectory() as t:
            def fail(_):raise AssertionError('offline HTTP call')
            r=collect(t,dict(schema='SEC_HISTORICAL_SOURCE_PILOT_V1',sources=[SPEC]),fail,True)
            self.assertEqual(r['verified_original_versions'],0)
            self.assertEqual(r['pending'],[SPEC['accession']])
            self.assertEqual(r['calibrated_expected_returns_created'],0)

    def test_capture_and_cache_reverify_original_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            manifest=dict(schema='SEC_HISTORICAL_SOURCE_PILOT_V1',sources=[SPEC]);calls=[]
            def fetch(url):calls.append(url);return fixture()
            a=collect(t,manifest,fetch);b=collect(t,manifest,fetch)
            self.assertEqual(len(calls),1);self.assertEqual(a['verified_original_versions'],1)
            self.assertEqual(b['original_documents'],2)

    def test_http_failure_is_not_zero_return_or_verified_source(self):
        with tempfile.TemporaryDirectory() as t:
            def fail(_):raise OSError('SYNTHETIC HTTP failure')
            r=collect(t,dict(schema='SEC_HISTORICAL_SOURCE_PILOT_V1',sources=[SPEC]),fail)
            self.assertEqual(r['status'],'SOURCE_ERRORS');self.assertEqual(r['verified_original_versions'],0)
            self.assertTrue(r['errors'])

    def test_invalid_manifest_and_ssrf_parameters_are_rejected(self):
        with self.assertRaises(ValueError):source_url(dict(SPEC,accession='../../escape'))
        with tempfile.TemporaryDirectory() as t:
            for sources in ([SPEC]*2,[dict(SPEC,accession=f'0001046179-24-{i:06d}') for i in range(9)]):
                with self.assertRaises(ValueError):collect(t,dict(schema='SEC_HISTORICAL_SOURCE_PILOT_V1',sources=sources))


if __name__=='__main__':unittest.main()
