"""Synthetic/monkeypatched 0050 source queue tests: no network and no return inference."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from scripts.alphamax_0050_backfill import preceding_months, run


class BenchmarkBackfillTests(unittest.TestCase):
    def test_missing_completed_months_queued_oldest_first(self):
        with tempfile.TemporaryDirectory() as root:
            result = preceding_months("2025-12", "2026-03-12", {}, 2, root)
            self.assertEqual(result["all_incomplete_months"], [
                "2025-12", "2026-01", "2026-02"])
            self.assertEqual(result["source_request_months"], ["2025-12", "2026-01"])
            self.assertEqual(result["pending_after_this_budget"], ["2026-02"])

    def test_durable_receipt_skip_only_not_self_claim(self):
        with tempfile.TemporaryDirectory() as root:
            saved = {"2025-12": {"saved": True}, "2026-01": {"saved": False}}
            with patch("scripts.alphamax_0050_backfill.quote_source_ready",
                       side_effect=lambda _root, item: item["saved"]):
                r = preceding_months("2025-12", "2026-03-12", saved, 2, root)
            self.assertEqual(r["source_request_months"], ["2026-01", "2026-02"])

    def test_bad_receipt_must_be_collected_again(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("scripts.alphamax_0050_backfill.quote_source_ready",
                       side_effect=ValueError("BROKEN_RAW_HASH")):
                r = preceding_months("2026-01", "2026-03-12",
                                     {"2026-01": {"fake_sha": "a"}}, 1, root)
            self.assertEqual(r["source_request_months"], ["2026-01"])

    def test_current_partial_month_is_never_claimed_complete(self):
        with tempfile.TemporaryDirectory() as root:
            r = preceding_months("2026-03", "2026-03-12", {}, 4, root)
            self.assertEqual(r["all_incomplete_months"], [])

    def test_noncompleted_future_start_and_invalid_budgets_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "START_AFTER"):
                preceding_months("2026-04", "2026-03-12", {}, 2, root)
            with self.assertRaisesRegex(ValueError, "REQUEST_BUDGET"):
                preceding_months("2026-01", "2026-03-12", {}, -1, root)
            with self.assertRaisesRegex(ValueError, "INVALID_MONTH_START"):
                preceding_months("2025-13", "2026-03-12", {}, 1, root)

    def make_root(self, root, *, close=100.0):
        root = Path(root)
        folder = root / "prices"
        folder.mkdir()
        rows = [{"date": "2026-03-12", "market": "TWSE",
                 "code": "0050", "open": 99.0, "close": close}]
        raw = json.dumps(rows).encode()
        (folder / "2026-03-12.json").write_bytes(raw)
        (folder / "latest_manifest.json").write_text(json.dumps({
            "date": "2026-03-12", "normalized_sha256": hashlib.sha256(raw).hexdigest()}))
        return root

    def test_bad_latest_receipt_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as work:
            root = self.make_root(work)
            (root / "prices/latest_manifest.json").write_text(
                json.dumps({"date": "2026-03-12", "normalized_sha256": "0" * 64}))
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                run(root, 2, "2026-01", sleep=0)

    def test_no_0050_official_row_blocks_even_if_other_prices_exist(self):
        with tempfile.TemporaryDirectory() as work:
            root = self.make_root(work, close=0)
            with self.assertRaisesRegex(ValueError, "MISSING_OFFICIAL_REFERENCE_QUOTE"):
                run(root, 2, "2026-01", sleep=0)

    def test_run_never_certifies_total_return(self):
        with tempfile.TemporaryDirectory() as work:
            root = self.make_root(work)
            dest = root / "prices/issuer_history/TWSE"
            def fake_process(code, asof, months, **kwargs):
                self.assertEqual(code, "0050")
                self.assertEqual(asof, "2026-03-12")
                self.assertEqual(months, ["2026-01"])
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "0050.json").write_text(json.dumps({
                    "issuer": "0050", "market": "TWSE",
                    "by_month": {"2026-01": {"original_archive": "synthetic"}},
                    "sessions": [{"date": "2026-01-02", "close": 100}]}))
                return {"code": "0050", "new_months": 1}
            with patch("scripts.alphamax_0050_backfill.process", side_effect=fake_process), \
                 patch("scripts.alphamax_0050_backfill.quote_source_ready",
                       side_effect=lambda root, item: True):
                out = run(root, 1, "2026-01", sleep=0)
            self.assertEqual(out["requested_months_this_run"], ["2026-01"])
            self.assertFalse(out["pit_training_certified"])
            self.assertFalse(out["investor_total_return_certified"])
            self.assertFalse(out["model_backtest_completed"])


if __name__ == "__main__":
    unittest.main()
