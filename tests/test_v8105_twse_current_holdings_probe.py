"""Synthetic current TWSE holdings probe tests; not retrospective alpha."""
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v8105_twse_current_holdings_probe import capture


class Resp:
    status = 200
    def __init__(self, content): self.content = content
    def getcode(self): return 200
    def read(self, n): return self.content[:n]
    def __enter__(self): return self
    def __exit__(self, *args): pass


def sample():
    return json.dumps([
        {"出表日期": "1151023", "資料年月": "11509", "公司代號": "9802",
         "職稱": "董事", "姓名": "AA", "目前持股": "20,000"},
        {"出表日期": "1151023", "資料年月": "11509", "公司代號": "6965",
         "職稱": "董事", "姓名": "BB", "目前持股": "10,000"},
        {"出表日期": "1151023", "資料年月": "11509", "公司代號": "2330",
         "職稱": "董事", "姓名": "CC", "目前持股": "1,000"}
    ], ensure_ascii=False).encode("utf-8")


class OfficialCurrentHoldingsTests(unittest.TestCase):
    def test_archive_current_original_and_filter_no_alpha(self):
        raw = sample()
        with tempfile.TemporaryDirectory() as folder:
            r = capture("t187ap11_L", folder, opener=lambda req, timeout: Resp(raw))
            self.assertEqual(r["target_issuer_count"], 2)
            self.assertEqual(r["target_row_count"], 2)
            self.assertFalse(r["historical_publication_month_reconstructed"])
            self.assertTrue(r["market_purchases_not_inferred_from_balances"])
            source=Path(folder)/"t187ap11_L"
            self.assertEqual(gzip.decompress((source/"original_response.gz").read_bytes()), raw)
            self.assertEqual(r["original_response_sha256"], hashlib.sha256(raw).hexdigest())
            picked=json.loads((source/"issuer_rows_unverified.json").read_bytes())
            self.assertFalse(picked["historical_PIT_validated"])
            self.assertEqual(len(picked["rows"]),2)

    def test_no_false_historical_empty_data(self):
        with tempfile.TemporaryDirectory() as folder:
            r = capture("t187ap03_L", folder, opener=lambda req, timeout: Resp(b"[]"))
            self.assertIsNone(r["target_row_count"])
            self.assertIsNotNone(r["parse_error"])
            self.assertFalse(r["original_2026_07_08_09_reconstruction_complete"])

    def test_nonapproved_endpoint_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_PUBLIC_TWSE_ENDPOINT"):
            capture("https://example.test", "/tmp")

    def test_unavailable_current_source_never_masquerades_as_zero(self):
        def failed(req, timeout): raise OSError("rate limited")
        with tempfile.TemporaryDirectory() as folder:
            rec = capture("t187ap11_L", folder, opener=failed)
            self.assertIsNone(rec["original_response_sha256"])
            self.assertIsNone(rec["target_row_count"])


if __name__ == "__main__":
    unittest.main()
