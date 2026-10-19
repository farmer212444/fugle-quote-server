import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.tw_chip_diagnostic import flows, join_market_codes, summarize, validate_archive

class ChipDiagnosticTests(unittest.TestCase):
    def test_missing_sessions_are_not_zero_filled(self):
        dates = [(f"2026-10-{d:02d}", {("TWSE", "1234"): {
            "foreign_ex_dealer_net_shares": 100, "trust_net_shares": -20,
            "dealer_net_shares": 0, "official_total_net_shares": 80}})
            for d in (19, 16, 15, 14, 13)]
        self.assertEqual(flows(dates, ("TWSE", "1234"), 5)["foreign_ex_dealer_net_shares"], 500)
        self.assertIsNone(flows(dates, ("TWSE", "4321"), 5))
        self.assertIsNone(flows(dates, ("TWSE", "1234"), 20))

    def test_unverified_coverage_never_becomes_certified(self):
        queue = {
            "model": "V8.8.1", "normalized_financial_issuers": 2,
            "queues": [{"market": "TWSE", "code": "1234"}],
            "normalized_not_yet_modeled": [{"market": "TPEX", "code": "5678"}]}
        stock_list = join_market_codes(queue)
        status = summarize(queue, "2026-10-19", [], [], stock_list, [])
        self.assertEqual(status["financial_issuer_count"], 2)
        self.assertEqual(status["matched_current_institutional"], 0)
        self.assertFalse(status["official_marketwide_chip_certified"])
        self.assertTrue(all(r["chip_evidence_status"] == "PENDING_SOURCE_OR_HISTORY"
                            for r in status["stocks"]))

    def test_source_digest_checked_with_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            original = b'[{"hello":"official"}]'
            normalized = b'[{"market":"TWSE","code":"1234"}]\n'
            raw_p, norm_p = path/"raw.gz", path/"norm.json"
            raw_p.write_bytes(gzip.compress(original, mtime=0))
            norm_p.write_bytes(normalized)
            import hashlib
            sha = lambda x: hashlib.sha256(x).hexdigest()
            receipt = {"raw_archive": str(raw_p), "raw_sha256": sha(original),
                       "raw_gzip_sha256": sha(raw_p.read_bytes()),
                       "normalized_path": str(norm_p), "normalized_sha256": sha(normalized), "rows": 1}
            self.assertEqual(len(validate_archive(receipt)), 1)
            norm_p.write_bytes(b"[]")
            with self.assertRaisesRegex(ValueError, "NORMALIZED_HASH_MISMATCH"):
                validate_archive(receipt)

    def test_duplicate_issuer_market_fails_closed(self):
        queue = {"queues":[{"market":"TWSE","code":"1234"},{"market":"TWSE","code":"1234"}],
                 "normalized_not_yet_modeled":[]}
        with self.assertRaisesRegex(ValueError,"DUPLICATE_MARKET_CODE"):
            join_market_codes(queue)

if __name__ == "__main__":
    unittest.main()
