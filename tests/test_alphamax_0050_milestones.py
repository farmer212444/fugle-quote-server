"""Synthetic-only 0050 milestone checks. Never labels, P&L or PIT claims."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from alphamax.benchmark_0050_milestone_audit import audit_0050_milestones
from alphamax.benchmark_0050_notice_receipts import NOTICES, _url, capture_notices
from scripts.history_archive import archive_original
from tests.test_alphamax_0050_notice_receipts import source_html
from tests.test_alphamax_0050_restore import write_packet


EVENT_PRICES = {
    "2025-01": [("2025-01-17", 100.0)],
    "2025-06": [("2025-06-10", 200.0), ("2025-06-18", 50.0)],
    "2025-07": [("2025-07-21", 48.0)],
    "2026-01": [("2026-01-22", 60.0)],
    "2026-07": [("2026-07-21", 70.0)],
    "2026-11": [("2026-11-20", 84.45)],
}


def create_sources(folder, *, remove_event=None):
    price_root = Path(folder) / "quotes"
    notice_root = Path(folder) / "notices"
    months = {}
    for month, pairs in EVENT_PRICES.items():
        pairs = [(day, price) for day, price in pairs if day != remove_event]
        if not pairs:
            # Keep a genuine official-source-shaped monthly packet but omit
            # the expected event date so the independent coverage check fails.
            pairs = [(month + "-22", 42.0)]
        rows = [
            {"date": day, "market": "TWSE", "code": "0050",
             "open": price, "high": price, "low": price, "close": price}
            for day, price in pairs
        ]
        raw = json.dumps({"stat": "OK", "month": month, "rows": rows}).encode()
        receipt = archive_original(
            price_root, "TWSE", "0050-" + month,
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date="
            + month.replace("-", "") + "01&stockNo=0050&response=json",
            raw, rows)
        months[month] = {
            "original_archive": receipt,
            "original_response_sha256": receipt["original_response_sha256"],
            "rows": rows,
        }
    packet_file = write_packet(price_root, months, asof="2026-11-20")
    notices = {_url(e[1], e[2]): source_html(e) for e in NOTICES}
    capture_notices(notice_root, fetch=lambda url: notices[url],
                    captured_at="2026-11-22T11:30:00+00:00")
    return price_root, notice_root, packet_file


class MilestoneTests(unittest.TestCase):
    def test_split_boundary_is_unit_normalized_without_fake_stock_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            prices, notices, _ = create_sources(tmp)
            result = audit_0050_milestones(prices, notices)
            self.assertEqual(result["status"],
                             "RETROSPECTIVE_MILESTONE_PRICE_UNITS_ALIGNED_NOT_PIT")
            self.assertEqual(result["aligned_milestones"], 6)
            self.assertEqual(result["notices_rechecked"], 6)
            milestones = {m["event"]: m for m in result["milestones"]}
            before = milestones["LAST_PRE_SPLIT_SESSION"]
            after = milestones["FIRST_POST_SPLIT_SESSION"]
            self.assertEqual(before["reference_units_per_pre_split_unit"], 1)
            self.assertEqual(after["reference_units_per_pre_split_unit"], 4)
            self.assertEqual(before["mechanical_market_value_ntd_per_pre_split_unit"], "200.0")
            self.assertEqual(after["mechanical_market_value_ntd_per_pre_split_unit"], "200.0")
            self.assertEqual(
                milestones["EX_DIVIDEND_1"]["cash_reference"][
                    "reference_gross_cash_per_original_unit_ntd"], "2.7")
            self.assertEqual(
                milestones["EX_DIVIDEND_2"]["cash_reference"][
                    "reference_gross_cash_per_original_unit_ntd"], "1.44")
            self.assertFalse(result["investor_total_return_certified"])
            self.assertFalse(result["adjusted_benchmark_certified"])
            self.assertFalse(result["historical_pit_publication_copy_verified"])
            self.assertEqual(result["verified_12m_after_cost_oos_cohorts"], 0)
            self.assertIsNone(result["official_pk_winner"])

    def test_missing_exact_event_trading_day_is_explicitly_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            prices, notices, _ = create_sources(tmp, remove_event="2025-06-18")
            result = audit_0050_milestones(prices, notices)
            self.assertEqual(result["status"],
                             "BLOCKED_0050_MILESTONE_SOURCE_OR_PRICE_GAPS")
            self.assertIn("FIRST_POST_SPLIT_SESSION:2025-06-18",
                          result["missing_or_unverified_milestones"])
            self.assertFalse(result["investor_total_return_certified"])

    def test_tampered_quote_session_fails_source_receipt_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            prices, notices, packet_file = create_sources(tmp)
            doc = json.loads(packet_file.read_text())
            doc["sessions"][0]["close"] = 99999
            packet_file.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, "CACHED_DERIVED_SESSIONS_MISMATCH"):
                audit_0050_milestones(prices, notices)

    def test_unverified_notice_archive_can_never_align_milestones(self):
        with tempfile.TemporaryDirectory() as tmp:
            prices, notices, _ = create_sources(tmp)
            receipt = next((notices / "originals").glob("dividend_20260120-*.html"))
            receipt.write_bytes(receipt.read_bytes() + b"TAMPER")
            result = audit_0050_milestones(prices, notices)
            self.assertEqual(result["status"],
                             "BLOCKED_0050_MILESTONE_SOURCE_OR_PRICE_GAPS")
            self.assertIn("0050_NOTICE_RECEIPTS_INCOMPLETE",
                          result["missing_or_unverified_milestones"])
            self.assertEqual(result["aligned_milestones"], 0)


if __name__ == "__main__":
    unittest.main()
