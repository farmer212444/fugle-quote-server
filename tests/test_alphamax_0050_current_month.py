"""Offline isolated TWSE 0050 partial-month refresh tests (not PIT/total return)."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts.alphamax_0050_current_month import run_current_month
from scripts.history_archive import archive_original
from scripts.tw_history_backfill import historical_url, parse, combine

FIELDS = ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"]


def monthly_response(include_nov20):
    values = [["115/11/09", "1,000", "80,000", "80", "80", "80", "80"]]
    if include_nov20:
        values.append(["115/11/20", "2,000", "168,900", "84.45", "84.45",
                       "84.45", "84.45"])
    return json.dumps({"stat": "OK", "title": "0050 元大台灣50 115年11月",
                       "fields": FIELDS, "data": values},
                      ensure_ascii=False).encode("utf-8")


def fixture(root):
    root = Path(root)
    (root / "prices").mkdir(parents=True)
    asof = "2026-11-20"
    snapshot = json.dumps([{"date": asof, "market": "TWSE", "code": "0050",
                            "close": 84.45}]).encode()
    (root / "prices" / f"{asof}.json").write_bytes(snapshot)
    (root / "prices/latest_manifest.json").write_text(json.dumps({
        "date": asof, "path": f"tw-market-data/prices/{asof}.json",
        "normalized_sha256": sha256(snapshot).hexdigest(),
    }))
    raw = monthly_response(False)
    previous = parse(raw, "0050", "2026-11")
    url = historical_url("0050", "2026-11")
    receipt = archive_original(root, "TWSE", "0050-2026-11", url, raw, previous)
    saved = {"original_archive": receipt,
             "original_response_sha256": receipt["original_response_sha256"],
             "rows": previous}
    packet = {"issuer": "0050", "market": "TWSE", "price_reference_asof": asof,
              "by_month": {"2026-11": saved},
              "sessions": combine({"2026-11": previous}, asof, "0050")}
    dest = root / "prices/issuer_history/TWSE/0050.json"
    dest.parent.mkdir(parents=True)
    dest.write_text(json.dumps(packet))
    return root, dest


class CurrentMonth0050Tests(unittest.TestCase):
    def test_refresh_stale_current_month_from_original_twse_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root, packet_file = fixture(temp)
            new_raw = monthly_response(True)
            calls = []
            def fake_fetch(url):
                calls.append(url)
                return new_raw
            r = run_current_month(root, fetch=fake_fetch, sleep=0)
            self.assertEqual(r["status"],
                             "ISOLATED_CURRENT_MONTH_OFFICIAL_PRICE_SOURCE_ALIGNED_NOT_PIT")
            self.assertTrue(r["raw_current_month_verified"])
            self.assertTrue(r["reparsed_month_matches_saved_rows"])
            self.assertEqual(r["latest_current_month_quote_date"], "2026-11-20")
            self.assertEqual(r["normalized_session_count"], 2)
            self.assertEqual(calls, [historical_url("0050", "2026-11")])
            self.assertFalse(r["investor_total_return_certified"])
            self.assertEqual(r["after_cost_oos_12m_verified"], 0)
            packet = json.loads(packet_file.read_text())
            self.assertEqual(packet["sessions"][0]["date"], "2026-11-20")
            self.assertEqual(packet["sessions"][0]["close"], 84.45)
            self.assertTrue((root / "raw-current-month/TWSE/0050/2026-11.json").exists())

    def test_fetch_unavailable_keeps_stale_month_explicitly_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = fixture(temp)
            def fail(_url):
                raise OSError("exchange_temporarily_unavailable")
            r = run_current_month(root, fetch=fail, sleep=0)
            self.assertEqual(r["status"],
                             "BLOCKED_0050_CURRENT_MONTH_PRICE_SOURCE_STALE_OR_INVALID")
            self.assertFalse(r["raw_current_month_verified"])
            self.assertEqual(r["latest_current_month_quote_date"], "2026-11-09")
            self.assertFalse(r["investor_total_return_certified"])

    def test_wrong_official_quote_hash_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = fixture(temp)
            manifest = root / "prices/latest_manifest.json"
            doc = json.loads(manifest.read_text())
            doc["normalized_sha256"] = "0" * 64
            manifest.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, "REFERENCE_PRICE_HASH_MISMATCH"):
                run_current_month(root, fetch=lambda _: monthly_response(True), sleep=0)

    def test_source_with_wrong_daily_close_never_marks_aligned(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = fixture(temp)
            wrong = monthly_response(True).replace(b"84.45", b"85.45")
            r = run_current_month(root, fetch=lambda _: wrong, sleep=0)
            self.assertEqual(r["status"],
                             "BLOCKED_0050_CURRENT_MONTH_PRICE_SOURCE_STALE_OR_INVALID")
            self.assertFalse(r["raw_current_month_verified"])
            self.assertEqual(r["latest_current_month_quote_date"], "2026-11-09")


if __name__ == "__main__":
    unittest.main()
