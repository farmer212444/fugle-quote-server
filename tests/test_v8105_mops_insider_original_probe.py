"""Pure offline assertions for bounded official MOPS report capture (not alpha)."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v8105_mops_insider_original_probe import (
    capture_single, digest, json_bytes, month_parts, parse_api,
)


def row():
    cells = ["0"] * 24
    cells[0], cells[1], cells[2] = "董事本人", "某公司", "普通股"
    cells[4], cells[8], cells[9], cells[13], cells[14], cells[18] = (
        "10,000", "1,000", "0", "200", "100", "10,700")
    return cells


def response(rows=None, code=200):
    return json.dumps({"code": code, "result": {"data": [row()] if rows is None else rows}},
                      ensure_ascii=False).encode("utf-8")


class FakeResponse:
    status = 200
    def __init__(self, payload): self.payload = payload
    def getcode(self): return 200
    def read(self, limit): return self.payload[:limit]
    def __enter__(self): return self
    def __exit__(self, *args): return False


class OriginalProbeTests(unittest.TestCase):
    def test_roc_month_conversion(self):
        self.assertEqual(month_parts("2026-09"), ("115", "9"))

    def test_original_response_is_shares_not_lots(self):
        r = parse_api(response(), "9802", "2026-09")
        self.assertEqual(r[0]["market_buy_shares"], 1000)
        self.assertEqual(r[0]["market_sell_shares"], 200)
        self.assertEqual(r[0]["market_net_shares"], 800)
        self.assertEqual(r[0]["other_sell_shares"], 100)

    def test_cannot_parse_monthly_balance_as_purchases(self):
        a = row()
        a[8], a[13] = "0", "0"
        a[18] = "100,000"
        r = parse_api(response([a]), "9802", "2026-09")
        self.assertEqual(r[0]["market_net_shares"], 0)

    def test_unexpected_schema_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_MOPS_REPORT_SCHEMA"):
            parse_api(response([["x"]]), "9802", "2026-09")

    def test_non_numeric_buys_not_accepted(self):
        a = row(); a[8] = "2.5"
        with self.assertRaisesRegex(ValueError, "NONINTEGER_OR_NEGATIVE"):
            parse_api(response([a]), "9802", "2026-09")

    def test_http_success_but_mops_error_is_not_rows(self):
        with self.assertRaisesRegex(ValueError, "API_DID_NOT_RETURN_SUCCESS"):
            parse_api(response(code=501), "9802", "2026-09")

    def test_html_challenge_not_misreported_as_official_rows(self):
        with self.assertRaisesRegex(ValueError, "NOT_VALID_UTF8_JSON"):
            parse_api(b"<html>Access denied</html>", "6965", "2026-09")

    def test_capture_archives_exact_response_and_explicit_no_pit_claim(self):
        raw = response()
        seen = {}
        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["payload"] = json.loads(request.data)
            return FakeResponse(raw)
        with tempfile.TemporaryDirectory() as folder:
            receipt = capture_single("9802", "2026-09", folder, opener=opener)
            self.assertEqual(seen["payload"]["year"], "115")
            self.assertEqual(seen["payload"]["month"], "9")
            self.assertEqual(receipt["http_status"], 200)
            self.assertEqual(receipt["original_response_sha256"], digest(raw))
            self.assertIsNone(receipt["official_historical_published_at"])
            self.assertEqual(receipt["raw_report_rows"], 1)
            self.assertFalse(receipt["holder_stable_account_identity_certified"])
            self.assertFalse(receipt["pit_backtest_admitted"])
            import gzip
            saved = Path(folder)/receipt["original_response_archive"]
            self.assertEqual(gzip.decompress(saved.read_bytes()), raw)
            normalized = json.loads((Path(folder)/"2026-09"/"9802"/"unverified_rows.json").read_text())
            self.assertTrue(normalized["net_sum_is_not_certified"])

    def test_network_failure_cannot_fake_original_hash(self):
        def opener(req, timeout):
            raise OSError("Network unavailable")
        with tempfile.TemporaryDirectory() as folder:
            receipt = capture_single("6965", "2026-09", folder, opener=opener)
            self.assertIsNone(receipt["original_response_sha256"])
            self.assertIsNone(receipt["raw_report_rows"])
            self.assertIsNone(receipt["official_historical_published_at"])

    def test_no_empty_results_mistaken_as_zero_trade(self):
        with self.assertRaisesRegex(ValueError, "API_HAS_NO_REPORT_ROWS"):
            parse_api(response([]), "9802", "2026-09")


if __name__ == "__main__":
    unittest.main()
