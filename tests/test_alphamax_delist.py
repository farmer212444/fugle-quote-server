"""Offline and synthetic-only tests for AlphaMax TWSE delisting receipts."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from alphamax.core import ContractError
from alphamax.delist_ledger import (
    SOURCE_CSV, SOURCE_HTML, capture_twse_delist, parse_twse_delist
)

NOW = "2026-11-10T14:00:00+00:00"
HEAD = "終止上市日期,公司名稱,上市編號\n"
ROWS = (
    "115年09月01日,三商壽,2867\n"
    "114年10月01日,京城銀,2809\n"
    "113年11月19日,廷鑫,2358\n"
    "110年12月13日,友佳-DR,912398\n"
    "097年09月01日,倚天資訊,2432\n"
)
CSV = (HEAD + ROWS).encode("utf-8-sig")
HTML = ("""<html><body><h1>終止上市公司</h1><table><tr>
<th>終止上市日期</th><th>公司名稱</th><th>上市編號</th></tr>"""
+ "".join("<tr><td>" + "</td><td>".join(x.split(",")) + "</td></tr>"
          for x in ROWS.strip().splitlines()) + "</table></body></html>").encode()


class DelistLedgerTests(unittest.TestCase):
    def test_csv_roc_and_6_digit_security_are_preserved(self):
        result = parse_twse_delist(CSV, SOURCE_CSV, NOW, min_events=5)
        self.assertEqual(result["event_count"], 5)
        self.assertEqual(result["events_4digit"], 4)
        self.assertEqual(result["events_6digit"], 1)
        self.assertEqual(result["first_effective_date"], "2008-09-01")
        self.assertEqual(result["last_effective_date"], "2026-09-01")
        self.assertEqual(result["raw_sha256"], sha256(CSV).hexdigest())
        self.assertIs(result["investment_certified"], False)
        self.assertFalse(result["historical_event_announcement_PIT_verified"])

    def test_html_original_parsing(self):
        result = parse_twse_delist(HTML, SOURCE_HTML, NOW, min_events=5)
        self.assertEqual(result["event_count"], 5)
        names = {x["code"]: x["company_name"] for x in result["events"]}
        self.assertEqual(names["2867"], "三商壽")

    def test_duplicate_is_rejected(self):
        raw = (HEAD + ROWS + "115年09月01日,三商壽,2867\n").encode()
        with self.assertRaisesRegex(ContractError, "DUPLICATE"):
            parse_twse_delist(raw, SOURCE_CSV, NOW, min_events=5)

    def test_future_event_rejected(self):
        raw = (HEAD + ROWS + "116年01月01日,未來股,1234\n").encode()
        with self.assertRaisesRegex(ContractError, "AFTER_CAPTURE"):
            parse_twse_delist(raw, SOURCE_CSV, NOW, min_events=5)

    def test_empty_source_rejected(self):
        with self.assertRaisesRegex(ContractError, "SOURCE_BYTES"):
            parse_twse_delist(b"x", SOURCE_CSV, NOW)

    def test_bad_row_never_silently_accepted(self):
        raw = (HEAD + ROWS + "115年10月01日,怪資料,NOTSECURITY\n").encode()
        with self.assertRaisesRegex(ContractError, "UNEXPECTED"):
            parse_twse_delist(raw, SOURCE_CSV, NOW, min_events=5)

    def test_untrusted_url_rejected(self):
        with self.assertRaisesRegex(ContractError, "UNTRUSTED"):
            parse_twse_delist(CSV, "https://other.invalid", NOW)

    def test_source_fallback_keeps_bytes_and_blocks_historical_certification(self):
        def download(url):
            if url == SOURCE_CSV:
                raise OSError("synthetic blocked CSV")
            return HTML
        with TemporaryDirectory() as tmp:
            out = capture_twse_delist(tmp, captured_at_utc=NOW,
                                     downloader=download, min_events=5)
            self.assertEqual(out["event_count"], 5)
            self.assertEqual(out["status"], "RETROSPECTIVE_TWSE_EVENTS_RECONSTRUCTED_NOT_PIT")
            self.assertFalse(out["complete_historical_trading_universe_verified"])
            self.assertFalse(out["investor_total_return_certified"])
            self.assertEqual(Path(tmp, "twse-delisted-original.html").read_bytes(), HTML)
            self.assertTrue(Path(tmp, "twse-delisted-events.json").exists())
            self.assertTrue(Path(tmp, "capture-manifest.json").exists())

    def test_official_source_outage_remains_blocked(self):
        with TemporaryDirectory() as tmp:
            out = capture_twse_delist(
                tmp, captured_at_utc=NOW, min_events=5,
                downloader=lambda _: (_ for _ in ()).throw(OSError("unavailable"))
            )
            self.assertEqual(out["status"], "BLOCKED_NO_OFFICIAL_TWSE_DELIST_EVENTS")
            self.assertEqual(out["event_count"], 0)
            self.assertFalse(out["investment_certified"])
            self.assertTrue(Path(tmp, "capture-manifest.json").exists())

    def test_naive_timestamp_rejected(self):
        with self.assertRaisesRegex(ContractError, "NEEDS_ZONE"):
            parse_twse_delist(CSV, SOURCE_CSV, "2026-11-10T11:00:00")

    def test_retrospective_effective_date_does_not_prove_prior_knowledge(self):
        result = parse_twse_delist(CSV, SOURCE_CSV, NOW)
        for row in result["events"]:
            self.assertIs(row["announcement_publication_time_verified"], False)
            self.assertIs(row["corporate_action_settlement_verified"], False)


if __name__ == "__main__":
    unittest.main()
