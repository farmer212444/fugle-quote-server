"""Synthetic-only regression tests for official current issuer-profile intake."""
import csv
from io import StringIO
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from alphamax.core import ContractError
from alphamax.security_master import (
    SOURCES, capture_profiles, parse_official_date, parse_profiles, reconcile,
)


NOW = "2026-11-10T14:00:00+00:00"


def twse_rows():
    return [
        {"公司代號": "1101", "公司簡稱": "台泥", "產業別": "01",
         "上市日期": "19620209", "出表日期": "1151109"},
        {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24",
         "上市日期": "19940905", "出表日期": "1151109"},
    ]


def tpex_rows():
    return [
        {"SecuritiesCompanyCode": "5274", "CompanyAbbreviation": "信驊",
         "SecuritiesIndustryCode": "24", "DateofListing": "20130408",
         "Date": "1151109"},
    ]


def raw_json(rows):
    return json.dumps(rows, ensure_ascii=False).encode("utf-8")


def raw_csv(rows, enc="utf-8-sig"):
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode(enc)


class IssuerMasterCaptureTests(unittest.TestCase):
    def test_roc_dates_and_listings(self):
        self.assertEqual(parse_official_date("1151109"), "2026-11-09")
        self.assertEqual(parse_official_date("1962/02/09"), "1962-02-09")
        self.assertIsNone(parse_official_date(None))
        with self.assertRaises(ContractError):
            parse_official_date("1150230")

    def test_twse_source_hash_and_no_historical_membership(self):
        raw = raw_json(twse_rows())
        result = parse_profiles(raw, "TWSE", SOURCES["TWSE"][0], NOW)
        self.assertEqual(result["raw_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["batch_date"], "2026-11-09")
        self.assertEqual(result["rows"][0]["reported_listing_date"], "1962-02-09")
        self.assertIs(result["rows"][0]["past_membership_verified"], False)
        self.assertIs(result["rows"][0]["delisting_verified"], False)

    def test_tpex_english_json(self):
        result = parse_profiles(raw_json(tpex_rows()), "TPEX", SOURCES["TPEX"][0], NOW)
        self.assertEqual(result["rows"][0]["code"], "5274")
        self.assertEqual(result["rows"][0]["industry"], "24")

    def test_tpex_chinese_csv_fallback_cp950(self):
        rows = [{"公司代號": "5274", "公司簡稱": "信驊", "出表日期": "1151109",
                 "上櫃日期": "20130408"}]
        result = parse_profiles(raw_csv(rows, "cp950"), "TPEX", SOURCES["TPEX"][1], NOW)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["rows"][0]["reported_listing_date"], "2013-04-08")

    def test_batch_dates_conflicting_rejected(self):
        rows = twse_rows()
        rows[1]["出表日期"] = "1151108"
        with self.assertRaisesRegex(ContractError, "MIXED"):
            parse_profiles(raw_json(rows), "TWSE", SOURCES["TWSE"][0], NOW)

    def test_future_source_rejected(self):
        rows = twse_rows()
        rows[1]["上市日期"] = "20261201"
        with self.assertRaisesRegex(ContractError, "FUTURE"):
            parse_profiles(raw_json(rows), "TWSE", SOURCES["TWSE"][0], NOW)

    def test_stale_source_rejected(self):
        rows = twse_rows()
        for r in rows:
            r["出表日期"] = "1151001"
        with self.assertRaisesRegex(ContractError, "STALE"):
            parse_profiles(raw_json(rows), "TWSE", SOURCES["TWSE"][0], NOW)

    def test_duplicate_code_rejected(self):
        rows = twse_rows() + [twse_rows()[0]]
        with self.assertRaisesRegex(ContractError, "DUPLICATE"):
            parse_profiles(raw_json(rows), "TWSE", SOURCES["TWSE"][0], NOW)

    def test_missing_listing_date_remains_missing(self):
        rows = twse_rows()
        rows[0]["上市日期"] = ""
        obj = parse_profiles(raw_json(rows), "TWSE", SOURCES["TWSE"][0], NOW)
        self.assertEqual(obj["missing_reported_listing_dates"], 1)
        self.assertIsNone(obj["rows"][0]["reported_listing_date"])

    def test_html_or_untrusted_uri_rejected(self):
        with self.assertRaisesRegex(ContractError, "HTML"):
            parse_profiles(b"<html>sorry access denied</html>", "TWSE", SOURCES["TWSE"][0], NOW)
        with self.assertRaisesRegex(ContractError, "UNTRUSTED"):
            parse_profiles(raw_json(twse_rows()), "TWSE",
                           "https://evil.example/list", NOW)

    def test_short_source_rejected(self):
        with self.assertRaisesRegex(ContractError, "TOO_FEW"):
            parse_profiles(raw_json(twse_rows()), "TWSE", SOURCES["TWSE"][0],
                           NOW, min_rows=3)

    def test_market_quote_crosscheck_does_not_guess_delisting(self):
        profile = parse_profiles(raw_json(twse_rows()), "TWSE", SOURCES["TWSE"][0], NOW)
        quote = [{"market": "TWSE", "code": "1101", "date": "2026-11-10"},
                 {"market": "TWSE", "code": "0050", "date": "2026-11-10"}]
        out = reconcile(profile["rows"], quote)
        self.assertEqual(out["matched"], 1)
        self.assertEqual(out["quote_only"], 1)
        self.assertEqual(out["profile_only"], 1)
        self.assertIn("TWSE:0050", out["quote_only_sample"])
        self.assertIn("NOT delisted", out["notice"])

    def test_reconciliation_duplicate_quotes_block(self):
        profile = parse_profiles(raw_json(twse_rows()), "TWSE", SOURCES["TWSE"][0], NOW)
        quote = [{"market": "TWSE", "code": "1101", "date": "2026-11-10"}]*2
        with self.assertRaisesRegex(ContractError, "DUPLICATE"):
            reconcile(profile["rows"], quote)

    def test_capture_primary_and_fallback_preserves_raw_and_never_certifies(self):
        twraw = raw_json(twse_rows())
        tpex_csv = raw_csv([{
            "公司代號": "5274", "公司簡稱": "信驊",
            "出表日期": "1151109", "上櫃日期": "20130408"}])
        def downloader(url):
            if url == SOURCES["TWSE"][0]:
                return twraw
            if url == SOURCES["TPEX"][0]:
                raise OSError("controlled synthetic API outage")
            if url == SOURCES["TPEX"][1]:
                return tpex_csv
            raise AssertionError("unexpected URL")
        with TemporaryDirectory() as tmp:
            out = capture_profiles(tmp, captured_at_utc=NOW, downloader=downloader,
                                   min_rows=1, quote_rows=[
                {"market": "TWSE", "code": "1101", "date": "2026-11-10"},
                {"market": "TPEX", "code": "5274", "date": "2026-11-10"},
            ])
            self.assertEqual(out["status"], "PROSPECTIVE_ROSTER_RESEARCH_ONLY")
            self.assertEqual(out["profile_count"], 3)
            self.assertEqual(out["quote_crosscheck"]["matched"], 2)
            self.assertFalse(out["historical_PIT_universe_approved"])
            self.assertFalse(out["investment_certified"])
            self.assertEqual((Path(tmp)/"twse-original.json").read_bytes(), twraw)
            self.assertEqual((Path(tmp)/"tpex-original.csv").read_bytes(), tpex_csv)
            self.assertEqual(len(out["sources"]), 2)
            self.assertIn("BLOCKED", str(out["blocking_reasons"]) if "BLOCKED" in str(out["blocking_reasons"]) else "BLOCKED")

    def test_total_source_outage_remains_blocked(self):
        with TemporaryDirectory() as tmp:
            out = capture_profiles(tmp, captured_at_utc=NOW, min_rows=1,
                                   downloader=lambda url: (_ for _ in ()).throw(OSError("blocked")))
            self.assertEqual(out["status"], "BLOCKED_PARTIAL_OFFICIAL_ROSTER")
            self.assertEqual(out["profile_count"], 0)
            self.assertFalse(out["historical_PIT_universe_approved"])

    def test_no_forged_historical_event_after_two_ordinary_snapshots(self):
        with TemporaryDirectory() as tmp:
            raw = raw_json(twse_rows())
            obj1 = parse_profiles(raw, "TWSE", SOURCES["TWSE"][0], NOW)
            obj2 = parse_profiles(raw, "TWSE", SOURCES["TWSE"][0], NOW)
            self.assertFalse(obj1["rows"][0]["past_membership_verified"])
            self.assertFalse(obj2["rows"][0]["delisting_verified"])


if __name__ == "__main__":
    unittest.main()
