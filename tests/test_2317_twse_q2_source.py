"""Synthetic contract tests for official TWSE 2317 Q2 PDF resolution.

Never treat mock bytes or a filing listing as a certified full statement.
"""
import copy
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from scripts import honhai_original_statements as h
from scripts import honhai_twse_q2_source as twse

PDF_PATH="/pdf/202602_2317_AI1_20260814_174754.pdf"
INDEX=(b'<tr><td>2317</td><td>115 Q2</td>'
       b'<td>202602_2317_AI1.pdf</td><td>4,018,369</td></tr>')
RESOLVER=(b'<html><a href="'+PDF_PATH.encode("ascii")+
          b'">202602_2317_AI1.pdf</a></html>')
PDF_URL=twse.PREFIX+PDF_PATH

class Response:
    def __init__(self,url,data):
        self.url=url
        self.status=200
        self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,cap):return self.data[:cap]

class FakeOpener:
    def __init__(self,index=INDEX,resolver=RESOLVER,pdf=None):
        self.index=index
        self.resolver=resolver
        self.pdf=b"Z"*twse.EXPECTED_BYTES if pdf is None else pdf
        self.calls=[]
    def open(self,request,timeout=30):
        self.calls.append((request.full_url,request.data))
        if request.full_url==twse.INDEX_URL:
            self.assert_get(request)
            return Response(twse.INDEX_URL,self.index)
        if request.full_url==twse.FORM_URL:
            vals=urllib.parse.parse_qs((request.data or b"").decode())
            if vals!=dict(step=["9"],kind=["A"],co_id=["2317"],filename=[twse.FILENAME]):
                raise AssertionError("wrong TWSE documented official resolver parameters")
            return Response(twse.FORM_URL,self.resolver)
        if request.full_url==PDF_URL:
            return Response(PDF_URL,self.pdf)
        raise AssertionError("unexpected source URL: "+request.full_url)
    def assert_get(self,request):
        if request.data is not None:raise AssertionError("index should be GET")

class TWSEQ2SourcesTests(unittest.TestCase):
    def test_official_index_exact_filename_and_session_resolver(self):
        fake=FakeOpener()
        pdf,proof=twse.download(opener=fake)
        self.assertEqual(len(pdf),4_018_369)
        self.assertEqual(proof["index_bytes"],INDEX)
        self.assertEqual(proof["resolution_bytes"],RESOLVER)
        self.assertEqual(proof["resolved_pdf_url"],PDF_URL)
        self.assertEqual([v[0] for v in fake.calls],
                         [twse.INDEX_URL,twse.FORM_URL,PDF_URL])

    def test_index_filename_must_not_be_invented(self):
        fake=FakeOpener(index=b"<td>2317</td><td>202601_2317_AI1.pdf</td>")
        with self.assertRaisesRegex(ValueError,"LISTING_REJECTED"):
            twse.download(opener=fake)
        self.assertEqual(len(fake.calls),1)

    def test_mismatched_resolver_and_oversized_link_rejected(self):
        for resolver in (
            b"<a href='https://evil.invalid/pdf/202602_2317_AI1.pdf'>pdf</a>",
            b"<a href='/pdf/202601_2317_AI1_20260814_174754.pdf'>pdf</a>",
            b"<a href='/pdf/202602_2317_AI1_20260814_174754.pdf'>pdf</a>"
            b"<a href='/pdf/202602_2317_AI1_20260816_174754.pdf'>other</a>"):
            with self.subTest(resolver=resolver):
                fake=FakeOpener(resolver=resolver)
                with self.assertRaisesRegex(ValueError,"RESOLVED_PDF_LINK"):
                    twse.download(opener=fake)
                self.assertEqual(len(fake.calls),2)

    def test_download_size_must_equal_actual_official_index(self):
        with self.assertRaisesRegex(ValueError,"SIZE_MISMATCH"):
            twse.download(opener=FakeOpener(pdf=b"not a full report"))

    def test_immutable_twse_index_and_resolver_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            entry=dict(bytes=twse.EXPECTED_BYTES)
            proof=h.archive_twse_provenance(root,dict(
                index_bytes=INDEX,resolution_bytes=RESOLVER,
                resolved_pdf_url=PDF_URL))
            entry["twse_provenance"]=proof
            h.validate_twse_provenance(root,entry)
            bad=copy.deepcopy(entry)
            bad["twse_provenance"]["resolved_pdf_url"]="https://evil.invalid/file.pdf"
            with self.assertRaisesRegex(ValueError,"PROVENANCE_MISMATCH"):
                h.validate_twse_provenance(root,bad)
            file=root/proof["index_archive_path"]
            file.write_bytes(file.read_bytes()+b"tampered")
            with self.assertRaisesRegex(ValueError,"PROVENANCE_REHASH_FAILED"):
                h.validate_twse_provenance(root,entry)

    def test_old_seven_quarters_do_not_claim_twse_q2_evidence(self):
        self.assertEqual(h.KNOWN["2026-Q2"],twse.INDEX_URL)
        self.assertEqual(len(h.KNOWN),8)
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(
                h.validate_archive(folder,"2026-Q2","2026-11-09T00:00:00+00:00")["coverage"])

if __name__=="__main__":
    unittest.main()
