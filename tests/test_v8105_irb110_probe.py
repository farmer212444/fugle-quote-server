"""Synthetic source-shape checks: IRB110 must not become a purchase signal."""
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v8105_twse_irb110_probe import capture_month, parse_irb110


def html_doc():
    return ('<html><head><title>IRB110 台灣證券交易所</title></head>'
            '<body><table><tr><td>9802鈺齊</td>'
            '<td>200,000,000</td><td>300,000</td><td>20,000</td>'
            '<td>50,000,000</td><td>0</td><td>1,000,000</td><td>5,000,000</td></tr>'
            '<tr><td>6965中傑</td><td>150,000,000</td>'
            '<td>100,000</td><td>0</td><td>30,000,000</td>'
            '<td>0</td><td>500,000</td><td>4,000,000</td></tr></table></body></html>').encode("big5")


class FakeResponse:
    status = 200
    def __init__(self, content): self.content = content
    def getcode(self): return 200
    def read(self, n): return self.content[:n]
    def __enter__(self): return self
    def __exit__(self, *args): return None


class IRB110ProbeTests(unittest.TestCase):
    def test_parse_issued_and_director_balance_but_not_market_trades(self):
        records = parse_irb110(html_doc())
        self.assertEqual(records["9802"]["issued_shares"], 200_000_000)
        self.assertEqual(records["9802"]["director_gross_increase_shares"], 300_000)
        self.assertEqual(records["6965"]["director_own_shares"], 30_000_000)
        self.assertTrue(records["9802"]["irb110_is_not_post_trade_market_buys"])

    def test_parse_strict_html_schema_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "NOT_EXPECTED_IRB110_PAGE"):
            parse_irb110(b"access denied")
        malformed = b"<html>IRB110<tr><td>9802</td><td>N/A</td>" + b"<td>0</td>" * 6 + b"</tr></html>"
        with self.assertRaisesRegex(ValueError, "NON_NUMERIC_IRB110"):
            parse_irb110(malformed)

    def test_capture_original_bytes_and_pit_pending(self):
        raw = html_doc()
        def opener(req, timeout):
            self.assertIn("115IRB110_9.HTM", req.full_url)
            return FakeResponse(raw)
        with tempfile.TemporaryDirectory() as temp:
            rec = capture_month("2026-09", temp, opener=opener)
            self.assertEqual(rec["http_status"], 200)
            self.assertEqual(set(rec["found_target_issuers"]), {"9802", "6965"})
            self.assertIsNone(rec["historical_first_publication_at"])
            self.assertFalse(rec["mops_market_trades_reconciled"])
            folder = Path(temp) / "2026-09"
            extracted = gzip.decompress((folder / "original_irb110_response.gz").read_bytes())
            self.assertEqual(raw, extracted)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), rec["raw_sha256"])
            data = json.loads((folder / "unverified_balance_summary.json").read_bytes())
            self.assertFalse(data["previously_public_asof_month_end"])

    def test_error_and_missing_month_are_not_zero_insider_purchase(self):
        def err(req, timeout):
            raise OSError("timeout")
        with tempfile.TemporaryDirectory() as temp:
            rec = capture_month("2026-09", temp, opener=err)
            self.assertIsNone(rec["raw_sha256"])
            self.assertEqual(rec["found_target_issuers"], [])
            self.assertFalse(rec["official_source_pit_certified"])

    def test_calendar_month_validation(self):
        with self.assertRaisesRegex(ValueError, "INVALID_MONTH"):
            capture_month("2026-13", "/tmp")


if __name__ == "__main__":
    unittest.main()
