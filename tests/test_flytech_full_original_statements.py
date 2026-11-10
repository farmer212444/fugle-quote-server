"""6206 full-quarter original discovery and exact identity/PIT controls."""
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.flytech_full_original_statements import (
  DIRECTORY,discover,official_url,quarter_window,collect,verify_archive,
  identity,fetch,season_options)

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
            info=collect(root,max_new=3,fetcher=with_selector,ajaxer=ajaxer)
            self.assertEqual(info["source_period_links_discovered"],2)
            self.assertEqual(info["original_full_statements_archived"],2)
            m=json.loads((root/FOLDER/"manifest.json").read_text())
            self.assertEqual(len(m["ajax_receipts"]),3)
            self.assertTrue(all(len(x["sha256"])==64 for x in m["ajax_receipts"]))

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
            r=collect(root,now=now,max_new=3,fetcher=fake_fetch)
            self.assertEqual(r["original_full_statements_archived"],2)
            self.assertEqual(r["newly_downloaded_quarters"],2)
            self.assertIn("2025-Q3",r["archived_quarters"])
            self.assertIn("2026-Q2",r["archived_quarters"])
            self.assertEqual(r["formal_gate_passes_issued"],0)
            manifest=json.loads((root/"evidence/v880/originals/6206/full_statements/manifest.json").read_text())
            self.assertEqual(len(manifest["documents"]),2)
            self.assertTrue(all(x["formal_gate_pass"] is False and
               x["first_publication_timestamp_verified"] is False for x in manifest["documents"]))
            rerun=collect(root,now=now+dt.timedelta(hours=1),max_new=3,fetcher=fake_fetch)
            self.assertEqual(rerun["newly_downloaded_quarters"],0)
            self.assertEqual(rerun["original_full_statements_archived"],2)
            src=root/manifest["documents"][0]["archive_path"]
            src.write_bytes(b"tampered issuer PDF")
            with self.assertRaisesRegex(ValueError,"PDF_ARCHIVE_HASH_MISMATCH"):
                collect(root,now=now,fetcher=fake_fetch)

    def test_fake_period_pdf_not_saved_or_certified(self):
        def always_wrong(raw,period):
            raise ValueError("FLYTECH_FULL_REPORT_PDF_COMPANY_OR_QUARTER_MISMATCH")
        with tempfile.TemporaryDirectory() as tmp,patch(
            "scripts.flytech_full_original_statements.identity",side_effect=always_wrong):
            r=collect(Path(tmp),max_new=3,fetcher=fake_fetch)
            self.assertEqual(r["original_full_statements_archived"],0)
            self.assertEqual(r["formal_gate_passes_issued"],0)
            self.assertTrue(any(x["reason"].startswith("PDF_") for x in r["collection_errors"]))

    def test_no_source_links_is_evidence_pending_not_zero_quality(self):
        def empty_index(url,cap):
            return b"<html>Year 2026, records not reachable in static HTML</html>"
        with tempfile.TemporaryDirectory() as tmp:
            r=collect(Path(tmp),max_new=2,fetcher=empty_index)
            self.assertEqual(len(r["original_quarters_missing"]),8)
            self.assertEqual(r["formal_gate_passes_issued"],0)
            self.assertFalse(r["original_publication_PIT_certified"])

if __name__=="__main__":
    unittest.main()
