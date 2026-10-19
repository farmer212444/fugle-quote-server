import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.tw_6206_ir import collect, parse_listing, source_allowed, extract_pdf

URL="https://www.flytech.com.tw/data/investor_law/attached/1786525880605469429.pdf"
SITE="https://www.flytech.com.tw/investor.php?act=analyst&year=2026"
HTML=('<html><table><tr><td>2026/08/12</td><td>第二季法人說明會</td>'
      '<td><a href="/data/investor_law/attached/1786525880605469429.pdf">下載</a>'
      '</td></tr></table></html>').encode()

class OfficialInvestorTests(unittest.TestCase):
    def test_listed_pdf_url_with_correct_date(self):
        rows=parse_listing(HTML,SITE)
        self.assertEqual(rows[0]["date"],"2026-08-12")
        self.assertEqual(rows[0]["pdf_url"],URL)

    def test_source_domain_and_redirect_safety(self):
        self.assertTrue(source_allowed(URL))
        self.assertTrue(source_allowed("https://mopsov.twse.com.tw/nas/STR/620620260812M001.pdf"))
        for bad in ("https://evil.com/paper.pdf",
                    "http://www.flytech.com.tw/data/investor_law/attached/x.pdf",
                    "https://www.flytech.com.tw.attacker.com/data/investor_law/attached/x.pdf",
                    "https://www.flytech.com.tw/data/investor_law/attached/../danger.pdf",
                    "https://mopsov.twse.com.tw/nas/STR/980220260917M001.pdf"):
            # Path-traversal should be explicitly excluded, not only netloc.
            self.assertFalse(source_allowed(bad))

    def test_issuer_missing_rejected(self):
        with self.assertRaisesRegex(ValueError,"NOT_A_COMPLETE"):
            extract_pdf(b"<html>not PDF</html>")

    def test_manifest_does_not_churn_on_unchanged_pdf(self):
        calls=[]
        def fetch(url,limit):
            calls.append(url)
            if "year=2026" in url:return HTML
            if "year=2025" in url:return HTML.replace(b"2026/08/12",b"2025/08/12").replace(b"1786525880605469429",b"1779243843316457288")
            return b"%PDF-"+b"X"*6000
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/"ir";raw=Path(temp)/"raw"
            date=dt.datetime(2026,10,19,12,40,tzinfo=dt.timezone.utc)
            with patch("scripts.tw_6206_ir.extract_pdf",return_value=["飛捷 6206 2026年第二季法人說明會\nEPS 5.93 毛利率45.5%"]):
                first=collect(date,out,raw,fetch=fetch)
                original=(out/"manifest.json").read_bytes()
                second=collect(date+dt.timedelta(minutes=8),out,raw,fetch=fetch)
                self.assertEqual((out/"manifest.json").read_bytes(),original)
                self.assertEqual(len(first["presentations"]),2)
                self.assertEqual(len(second["presentations"]),2)
                self.assertIn("飛捷", (out/"latest.md").read_text())
                self.assertFalse(first["presentations"][0]["gate_pass"])
                self.assertFalse(first["presentations"][0]["original_company_filing_time_verified"])

    def test_no_unreachable_source_falsely_marks_success(self):
        def nope(url,limit):raise OSError("source offline")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,"UNREACHABLE"):
                collect(dt.datetime(2026,10,19,tzinfo=dt.timezone.utc),
                        Path(temp)/"x",Path(temp)/"r",fetch=nope)

if __name__=="__main__":unittest.main()
