"""6206 full-quarter original discovery and exact identity/PIT controls."""
import datetime as dt
import hashlib
import json
import urllib.error
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.flytech_full_original_statements import (
  DIRECTORY,discover,official_url,quarter_window,collect,verify_archive,
  identity,fetch,season_options,twse_index_url,twse_filename,twse_resolve,
  twse_pdf_with_retry,temporary_twse_failure)

def table(period_code,token):
    return ('<tr><td>第'+period_code+'季</td><td><a href="/data/investor_season/attached/'+
            str(token)+'.pdf">下載</a></td></tr>').encode()

def ident(raw,period):
    if raw!=b"%PDF-1.4 test pdf with signed synthetic hash %%EOF":
        raise ValueError("FLYTECH_FULL_REPORT_PDF_COMPANY_OR_QUARTER_MISMATCH")
    return dict(page_count=50,complete_statements_headings_observed=True,
       cover_issuer_and_quarter_match=True,full_notes_content_reviewed=False,
       auditor_opinion_certified=False,filing_publication_PIT_verified=False,
       formal_gate_pass=False)

def unavailable_twse(*args,**kwargs):
    raise ValueError("MOCK_TWSE_IS_UNAVAILABLE")

def mock_twse(url,cap,post=None):
    if post is not None:
        return b'<html><a href="/pdf/202602_6206_AI1_20260807_171921.pdf">202602_6206_AI1.pdf</a></html>'
    if '?step=1' in url and 'year=115' in url and 'seamon=2' in url:
        return b'<html>6206 IFRSs\xe5\x90\x88\xe4\xbd\xb5\xe8\xb2\xa1\xe5\xa0\xb1 202602_6206_AI1.pdf</html>'
    if url.startswith("https://doc.twse.com.tw/pdf/"):
        return b"%PDF-1.4 test pdf with signed synthetic hash %%EOF"
    raise ValueError("MOCK_TWSE_QUARTER_UNAVAILABLE")

def fake_fetch(url,cap):
    if url.endswith("&year=2026"):
        return b'<html>'+table("二","1234567890123456789")+b'</html>'
    if url.endswith("&year=2025"):
        return b'<html>'+table("三","1234567890123456790")+b'</html>'
    if url.endswith("&year=2024"):
        return b"<html><p> No quarterly links currently available </p></html>"
    if url.endswith(".pdf"):
        return b"%PDF-1.4 test pdf with signed synthetic hash %%EOF"
    raise ValueError("UNEXPECTED_NETWORK_TARGET")

class FlytechOriginalsTest(unittest.TestCase):
    def test_full_calendar_window_and_discovery(self):
        self.assertEqual(quarter_window()[:2],["2024-Q3","2024-Q4"])
        self.assertEqual(quarter_window()[-1],"2026-Q2")
        candidates,pending=discover(table("二","1234567890123456789"),2026)
        self.assertEqual(candidates,{"2026-Q2":"https://www.flytech.com.tw/data/investor_season/attached/1234567890123456789.pdf"})
        self.assertEqual(pending,[])
        self.assertTrue(official_url(next(iter(candidates.values()))))
        self.assertFalse(official_url("http://www.flytech.com.tw/data/investor_season/attached/1234567890123456789.pdf"))
        self.assertFalse(official_url("https://www.flytech.com.tw/data/investor_law/attached/1234567890123456789.pdf"))

    def test_official_dynamic_season_selector_and_posted_pdf_list(self):
        from scripts.flytech_full_original_statements import FOLDER
        selector=(b'<select name="season" id="season">'
                  b'<option value="17" selected>2026</option>'
                  b'<option value="16">2025</option>'
                  b'<option value="15">2024</option></select>')
        self.assertEqual(season_options(selector),{2026:17,2025:16,2024:15})
        def with_selector(url,cap):
            if "year=" in url:
                return b"<html><body>"+selector+b"</body></html>"
            return fake_fetch(url,cap)
        def ajaxer(season):
            if season==17:
                fragment=(b'<li><a href="data/investor_season/attached/'
                          b'1234567890123456789.pdf">\xe7\xac\xac\xe4\xba\x8c\xe5\xad\xa3</a></li>')
            elif season==16:
                fragment=(b'<li>\xe7\xac\xac\xe4\xb8\x89\xe5\xad\xa3<a href="/data/investor_season/attached/'
                          b'1234567890123456790.pdf">PDF</a></li>')
            else:fragment=b"<ul>No quarter available</ul>"
            raw=json.dumps({"error_code":0,"html":{"season_list":fragment.decode()}}).encode()
            return fragment,raw
        with tempfile.TemporaryDirectory() as tmp,patch(
            "scripts.flytech_full_original_statements.identity",side_effect=ident):
            root=Path(tmp)
            info=collect(root,max_new=3,fetcher=with_selector,ajaxer=ajaxer,twse_fetcher=unavailable_twse)
            self.assertEqual(info["source_period_links_discovered"],2)
            self.assertEqual(info["original_full_statements_archived"],2)
            m=json.loads((root/FOLDER/"manifest.json").read_text())
            self.assertEqual(len(m["ajax_receipts"]),3)
            self.assertTrue(all(len(x["sha256"])==64 for x in m["ajax_receipts"]))

    def test_only_verified_twse_filing_index_may_resolve_original_pdf(self):
        self.assertIn("co_id=6206",twse_index_url("2026-Q2"))
        html=b"<html>6206 IFRSs&#21512;&#20341;&#36001;&#22577; 202602_6206_AI1.pdf</html>"
        self.assertEqual(twse_filename(html,"2026-Q2"),"202602_6206_AI1.pdf")
        resolved=twse_resolve(
            b'<a href="/pdf/202602_6206_AI1_20260807_171921.pdf">202602_6206_AI1.pdf</a>',
            "202602_6206_AI1.pdf")
        self.assertTrue(resolved.startswith("https://doc.twse.com.tw/pdf/"))
        with self.assertRaisesRegex(ValueError,"TWSE_OFFICIAL_INDEX"):
            twse_filename(html.replace(b"6206",b"2330"),"2026-Q2")
        with self.assertRaisesRegex(ValueError,"TWSE_NO_UNIQUE"):
            twse_resolve(b'<a href="/pdf/202601_6206_AI1.pdf">other</a>',
                         "202602_6206_AI1.pdf")
        with tempfile.TemporaryDirectory() as tmp,patch(
            "scripts.flytech_full_original_statements.identity",side_effect=ident):
            def empty_index(url,cap):
                return b"<html>No quarterly PDF at this issuer static page</html>"
            results=collect(Path(tmp),max_new=1,
                fetcher=empty_index,twse_fetcher=mock_twse)
            self.assertEqual(results["original_full_statements_archived"],1)
            self.assertEqual(results["archived_quarters"],["2026-Q2"])
            manifest=json.loads((Path(tmp)/"evidence/v880/originals/6206/full_statements/manifest.json").read_text())
            row=manifest["documents"][0]
            self.assertEqual(row["source_url"],resolved)
            self.assertTrue(row["twse_source_receipt"]["response_link_checked"])
            self.assertFalse(row["first_publication_timestamp_verified"])
            self.assertEqual(results["formal_gate_passes_issued"],0)

    def test_ambiguous_html_link_never_archived(self):
        source=(b'<tr><td>First Second</td><td><a href="/data/investor_season/attached/'
                b'1234567890123456789.pdf">download</a></td></tr>')
        matched,missing=discover(source,2026)
        self.assertEqual(matched,{})
        self.assertEqual(len(missing),1)
        other=(b'<tr><td>\xe7\xac\xac\xe4\xb8\x80\xe5\xad\xa3 & \xe7\xac\xac\xe4\xba\x8c\xe5\xad\xa3</td><td><a href="'
               b'/data/investor_season/attached/1234567890123456789.pdf">PDF</a></td></tr>')
        matched,missing=discover(other,2026)
        self.assertEqual(matched,{})
        self.assertTrue(missing)

    def test_archived_pdf_receipt_and_idempotency_no_pass(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "scripts.flytech_full_original_statements.identity",side_effect=ident):
            root=Path(tmp)
            now=dt.datetime(2026,11,10,2,0,tzinfo=dt.timezone.utc)
            r=collect(root,now=now,max_new=3,fetcher=fake_fetch,twse_fetcher=unavailable_twse)
            self.assertEqual(r["original_full_statements_archived"],2)
            self.assertEqual(r["newly_downloaded_quarters"],2)
            self.assertIn("2025-Q3",r["archived_quarters"])
            self.assertIn("2026-Q2",r["archived_quarters"])
            self.assertEqual(r["formal_gate_passes_issued"],0)
            manifest=json.loads((root/"evidence/v880/originals/6206/full_statements/manifest.json").read_text())
            self.assertEqual(len(manifest["documents"]),2)
            self.assertTrue(all(x["formal_gate_pass"] is False and
               x["first_publication_timestamp_verified"] is False for x in manifest["documents"]))
            rerun=collect(root,now=now+dt.timedelta(hours=1),max_new=3,fetcher=fake_fetch,twse_fetcher=unavailable_twse)
            self.assertEqual(rerun["newly_downloaded_quarters"],0)
            self.assertEqual(rerun["original_full_statements_archived"],2)
            src=root/manifest["documents"][0]["archive_path"]
            src.write_bytes(b"tampered issuer PDF")
            with self.assertRaisesRegex(ValueError,"PDF_ARCHIVE_HASH_MISMATCH"):
                collect(root,now=now,fetcher=fake_fetch,twse_fetcher=unavailable_twse)

    def test_fake_period_pdf_not_saved_or_certified(self):
        def always_wrong(raw,period):
            raise ValueError("FLYTECH_FULL_REPORT_PDF_COMPANY_OR_QUARTER_MISMATCH")
        with tempfile.TemporaryDirectory() as tmp,patch(
            "scripts.flytech_full_original_statements.identity",side_effect=always_wrong):
            r=collect(Path(tmp),max_new=3,fetcher=fake_fetch,twse_fetcher=unavailable_twse)
            self.assertEqual(r["original_full_statements_archived"],0)
            self.assertEqual(r["formal_gate_passes_issued"],0)
            self.assertTrue(any(x["reason"].startswith("PDF_") for x in r["collection_errors"]))

    def test_transient_twse_pdf_retries_once_only_and_never_loosens_sha(self):
        url="https://doc.twse.com.tw/pdf/202502_6206_AI1_20261110_123117.pdf"
        attempts=[]
        delays=[]
        def flaky(u,cap):
            self.assertEqual(u,url)
            attempts.append(cap)
            if len(attempts)==1:
                raise urllib.error.URLError(ConnectionRefusedError(111,
                                         "Connection refused"))
            return b"%PDF-1.4 test bytes for source verification"
        raw=twse_pdf_with_retry(url,12_000_000,transport=flaky,
                                sleeper=delays.append)
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertEqual(len(attempts),2)
        self.assertEqual(delays,[2.0])
        self.assertTrue(temporary_twse_failure(urllib.error.URLError(
                        TimeoutError("timed out"))))

    def test_nontransient_pdf_failure_never_retries(self):
        url="https://doc.twse.com.tw/pdf/202502_6206_AI1_20261110_123117.pdf"
        calls=[]
        def missing(u,cap):
            calls.append((u,cap))
            raise urllib.error.HTTPError(u,404,"not found",{},None)
        with self.assertRaises(urllib.error.HTTPError):
            twse_pdf_with_retry(url,1000,transport=missing,
                                sleeper=lambda _:self.fail("no delay allowed"))
        self.assertEqual(len(calls),1)
        with self.assertRaisesRegex(ValueError,"UNBOUNDED_PDF_RETRY"):
            twse_pdf_with_retry(url,1000,max_attempts=3,
                                transport=missing,sleeper=lambda _:None)
        with self.assertRaisesRegex(ValueError,"URL_NOT_OFFICIAL"):
            twse_pdf_with_retry("http://example.org/issuer.pdf",1000,
                                transport=missing,sleeper=lambda _:None)

    def test_persistent_connection_refused_does_not_claim_pdf_download(self):
        url="https://doc.twse.com.tw/pdf/202501_6206_AI1_20261110_123120.pdf"
        calls=[]
        def blocked(u,cap):
            calls.append(u)
            raise urllib.error.URLError(ConnectionRefusedError(111,"Connection refused"))
        with self.assertRaises(urllib.error.URLError):
            twse_pdf_with_retry(url,1000,transport=blocked,
                                sleeper=lambda _:None)
        self.assertEqual(len(calls),2)

    def test_five_quarter_catchup_is_bounded_and_not_formal_pass(self):
        with tempfile.TemporaryDirectory() as tmp,patch(
            "scripts.flytech_full_original_statements.identity",side_effect=ident):
            root=Path(tmp)
            data=collect(root,max_new=5,twse_max_probes=5,
                         fetcher=fake_fetch,twse_fetcher=unavailable_twse)
            self.assertEqual(data["original_full_statements_archived"],2)
            self.assertEqual(data["formal_gate_passes_issued"],0)
            self.assertFalse(data["formal_Aplus"])
            with self.assertRaisesRegex(ValueError,"UNBOUNDED_FETCH_REQUEST"):
                collect(root,max_new=6,fetcher=fake_fetch,
                        twse_fetcher=unavailable_twse)

    def test_no_source_links_is_evidence_pending_not_zero_quality(self):
        def empty_index(url,cap):
            return b"<html>Year 2026, records not reachable in static HTML</html>"
        with tempfile.TemporaryDirectory() as tmp:
            r=collect(Path(tmp),max_new=2,fetcher=empty_index,twse_fetcher=unavailable_twse)
            self.assertEqual(len(r["original_quarters_missing"]),8)
            self.assertEqual(r["formal_gate_passes_issued"],0)
            self.assertFalse(r["original_publication_PIT_certified"])

if __name__=="__main__":
    unittest.main()
