"""Offline regression tests: 0050 original-source continuity, never PIT certification."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.alphamax_0050_restore import prepare_workspace
from scripts.alphamax_pit_pk_gap_audit import stage_verified_0050_quote_cache
from scripts.history_archive import archive_original
from scripts.tw_history_backfill import combine


def make_month(root, month, day):
    rows = [{"date": day, "market": "TWSE", "code": "0050",
             "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}]
    raw = json.dumps({"stat": "OK", "source_test_month": month, "day": day}).encode()
    receipt = archive_original(
        root, "TWSE", "0050-" + month,
        "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date="
        + month.replace("-", "") + "01&stockNo=0050&response=json",
        raw, rows,
    )
    return {"original_archive": receipt,
            "original_response_sha256": receipt["original_response_sha256"],
            "rows": rows}


def write_packet(root, months, asof="2026-11-09"):
    packet = {"schema": "V889_OFFICIAL_TWSE_ISSUER_MONTHLY",
              "issuer": "0050", "market": "TWSE",
              "price_reference_asof": asof, "by_month": months,
              "sessions": combine({m: v["rows"] for m, v in months.items()}, asof, "0050")}
    file = Path(root) / "prices/issuer_history/TWSE/0050.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(packet))
    return file


def source_repo(root):
    repo = Path(root) / "repo"
    root = repo / "tw-market-data"
    (root / "prices").mkdir(parents=True)
    import hashlib
    raw = json.dumps([{"date": "2026-11-09", "market": "TWSE",
                       "code": "0050", "close": 100.0}]).encode()
    (root / "prices/2026-11-09.json").write_bytes(raw)
    (root / "prices/latest_manifest.json").write_text(json.dumps({
        "date": "2026-11-09",
        "path": "tw-market-data/prices/2026-11-09.json",
        "normalized_sha256": hashlib.sha256(raw).hexdigest(),
    }))
    baseline = {"2026-10": make_month(root, "2026-10", "2026-10-30")}
    base_file = write_packet(root, baseline)
    return repo, root, baseline, base_file


def prior_artifact(root, base, baseline):
    archived = Path(root) / "old_artifact/tw-market-data"
    (archived / "prices/originals/history/TWSE").mkdir(parents=True)
    origin = base / "prices/originals/history/TWSE/0050-2026-10"
    shutil.copytree(origin, archived / "prices/originals/history/TWSE/0050-2026-10")
    historical = make_month(archived, "2025-01", "2025-01-20")
    prior_file = write_packet(archived, {**baseline, "2025-01": historical})
    return prior_file.parents[4], prior_file


class Restored0050Tests(unittest.TestCase):
    def test_isolated_workspace_reuses_verified_prior_months(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, base, baseline, base_file = source_repo(tmp)
            previous, _ = prior_artifact(tmp, base, baseline)
            original = base_file.read_bytes()
            target = Path(tmp) / "alphamax-0050-data"
            result = prepare_workspace(repo, target, previous)
            self.assertEqual(result["months_restored"], 2)
            self.assertTrue(result["previous_success_artifact_restored"])
            packet = json.loads((target / "prices/issuer_history/TWSE/0050.json").read_text())
            self.assertEqual(set(packet["by_month"]), {"2025-01", "2026-10"})
            self.assertEqual(original, base_file.read_bytes())
            self.assertFalse(result["legacy_v8_files_modified"])
            self.assertFalse(result["investor_total_return_certified"])

    def test_independent_capture_same_hash_different_receipt_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, base, baseline, base_file = source_repo(tmp)
            previous, prior_file = prior_artifact(tmp, base, baseline)
            old_root = previous / "tw-market-data"
            packet = json.loads(prior_file.read_text())
            item = packet["by_month"]["2026-10"]
            ref = item["original_archive"]
            ref["captured_at_utc"] = "2026-11-10T00:00:00+00:00"
            receipt = old_root / ref["receipt_path"]
            receipt.write_text(json.dumps({k: v for k, v in ref.items()
                                           if k != "receipt_path"}))
            prior_file.write_text(json.dumps(packet))
            target = Path(tmp) / "isolated"
            source_bytes = (base / ref["receipt_path"]).read_bytes()
            self.assertNotEqual(source_bytes, receipt.read_bytes())
            result = prepare_workspace(repo, target, previous)
            self.assertEqual(result["months_restored"], 2)
            self.assertEqual((target / ref["receipt_path"]).read_bytes(), receipt.read_bytes())
            self.assertEqual((base / ref["receipt_path"]).read_bytes(), source_bytes)

    def test_independent_capture_tampered_raw_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, base, baseline, _ = source_repo(tmp)
            previous, prior_file = prior_artifact(tmp, base, baseline)
            packet = json.loads(prior_file.read_text())
            ref = packet["by_month"]["2026-10"]["original_archive"]
            archive = previous / "tw-market-data" / ref["archive_path"]
            archive.write_bytes(b"not gzip")
            with self.assertRaisesRegex(ValueError, "PREVIOUS_ARTIFACT_RAW_RECEIPT_INVALID"):
                prepare_workspace(repo, Path(tmp) / "isolated", previous)

    def test_fresh_partial_month_replaces_old_frozen_partial_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, base, baseline, _ = source_repo(tmp)
            previous, old_file = prior_artifact(tmp, base, baseline)
            old_root = previous / "tw-market-data"
            older = make_month(old_root, "2026-11", "2026-11-02")
            old_packet = json.loads(old_file.read_text())
            old_packet["by_month"]["2026-11"] = older
            old_packet["sessions"] = combine(
                {m: x["rows"] for m, x in old_packet["by_month"].items()},
                "2026-11-09", "0050")
            old_file.write_text(json.dumps(old_packet))
            newer = make_month(base, "2026-11", "2026-11-09")
            write_packet(base, {**baseline, "2026-11": newer})
            target = Path(tmp) / "isolated"
            result = prepare_workspace(repo, target, previous)
            self.assertTrue(result["previous_success_artifact_restored"])
            packet = json.loads((target / "prices/issuer_history/TWSE/0050.json").read_text())
            self.assertEqual(packet["by_month"]["2026-11"]["rows"][0]["date"], "2026-11-09")
            self.assertEqual(
                packet["by_month"]["2026-11"]["original_response_sha256"],
                newer["original_response_sha256"])

    def test_conflicting_completed_month_receipts_cannot_be_rebased(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, base, baseline, _ = source_repo(tmp)
            previous, old_file = prior_artifact(tmp, base, baseline)
            changed = make_month(previous / "tw-market-data", "2026-10", "2026-10-29")
            packet = json.loads(old_file.read_text())
            packet["by_month"]["2026-10"] = changed
            packet["sessions"] = combine({m: x["rows"] for m, x in packet["by_month"].items()},
                                         "2026-11-09", "0050")
            old_file.write_text(json.dumps(packet))
            with self.assertRaisesRegex(ValueError, "COMPLETED_MONTH_SOURCE_VINTAGE_CONFLICT"):
                prepare_workspace(repo, Path(tmp) / "isolated", previous)

    def test_without_previous_artifact_uses_branch_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, _, _ = source_repo(tmp)
            result = prepare_workspace(repo, Path(tmp) / "cache")
            self.assertEqual(result["months_restored"], 0)
            self.assertFalse(result["previous_success_artifact_restored"])

    def test_tampered_normalized_month_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, base, baseline, _ = source_repo(tmp)
            previous, prior_file = prior_artifact(tmp, base, baseline)
            packet = json.loads(prior_file.read_text())
            packet["by_month"]["2025-01"]["rows"][0]["close"] = 999
            packet["sessions"] = combine({m: x["rows"] for m, x in packet["by_month"].items()},
                                         "2026-11-09", "0050")
            prior_file.write_text(json.dumps(packet))
            with self.assertRaisesRegex(ValueError, "PARSED_ROWS_SHA256_MISMATCH"):
                prepare_workspace(repo, Path(tmp) / "cache", previous)

    def test_tampered_derived_session_list_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, base, baseline, _ = source_repo(tmp)
            previous, prior_file = prior_artifact(tmp, base, baseline)
            packet = json.loads(prior_file.read_text())
            packet["sessions"].pop()
            prior_file.write_text(json.dumps(packet))
            with self.assertRaisesRegex(ValueError, "DERIVED_SESSIONS_MISMATCH"):
                prepare_workspace(repo, Path(tmp) / "cache", previous)

    def test_gap_audit_stages_only_receipt_checked_0050_price_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "isolated-0050"
            jan = make_month(cache, "2025-01", "2025-01-20")
            octob = make_month(cache, "2026-10", "2026-10-30")
            original = write_packet(
                cache, {"2025-01": jan, "2026-10": octob}, asof="2026-11-09")
            dest = Path(tmp) / "gap-research"
            proof = stage_verified_0050_quote_cache(
                cache, dest, main_price_asof="2026-11-20")
            self.assertEqual(proof["monthly_receipts"], 2)
            self.assertTrue(proof["price_only_not_total_return"])
            self.assertFalse(proof["historical_pit_membership_certified"])
            self.assertFalse(proof["external_source_authentication_certified"])
            self.assertEqual((dest / "TWSE/0050.json").read_bytes(),
                             original.read_bytes())

    def test_gap_audit_rejects_future_or_tampered_0050_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "isolated-0050"
            jan = make_month(cache, "2025-01", "2025-01-20")
            packet_file = write_packet(cache, {"2025-01": jan}, asof="2026-11-09")
            dest = Path(tmp) / "gap-research"
            with self.assertRaisesRegex(
                    ValueError, "CACHE_AFTER_PINNED_MAIN_QUOTE_CUTOFF"):
                stage_verified_0050_quote_cache(
                    cache, dest, main_price_asof="2026-11-08")
            self.assertFalse((dest / "TWSE/0050.json").exists())
            packet = json.loads(packet_file.read_text())
            packet["sessions"][0]["close"] = 555
            packet_file.write_text(json.dumps(packet))
            with self.assertRaisesRegex(
                    ValueError, "CACHED_DERIVED_SESSIONS_MISMATCH"):
                stage_verified_0050_quote_cache(
                    cache, dest, main_price_asof="2026-11-20")
            self.assertFalse((dest / "TWSE/0050.json").exists())

    def test_cannot_use_v8_root_as_scratch_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, base, _, _ = source_repo(tmp)
            with self.assertRaisesRegex(ValueError, "MUST_NOT_OVERWRITE_LEGACY_V8"):
                prepare_workspace(repo, base)


if __name__ == "__main__":
    unittest.main()
