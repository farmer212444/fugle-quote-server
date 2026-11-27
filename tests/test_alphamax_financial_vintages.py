"""Synthetic financial version-clock and original-byte regressions."""
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from alphamax.core import ContractError
from alphamax.financial_vintages import append_snapshot, canonical, digest, select_asof, verify_archive
from tests.test_alphamax_reported_income import row_fixture

FIRST = "2026-11-17T01:00:00+00:00"
SECOND = "2026-11-18T01:00:00+00:00"


def raw(row=None):
    return canonical([row_fixture() if row is None else row])


class FinancialVintageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def capture(self, data=None, stamp=FIRST):
        return append_snapshot(self.root, raw() if data is None else data,
                               codes=["0001"], observed_at=stamp)

    def edit_ledger(self, edit):
        path = self.root / "ledger.json"
        ledger = json.loads(path.read_bytes())
        edit(ledger)
        path.write_bytes(canonical(ledger))

    def test_first_original_and_capture_clock_never_claim_historical_admission(self):
        report = self.capture()
        ledger = verify_archive(self.root)
        snapshot = ledger["snapshots"][0]
        restored = gzip.decompress((self.root / snapshot["archive_path"]).read_bytes())
        self.assertEqual(restored, raw())
        self.assertEqual(report["new_versions"], 1)
        self.assertEqual(report["admitted_historical_PIT_batches"], 0)
        self.assertFalse(report["issuer_publication_timestamps_verified"])
        self.assertIsNone(ledger["versions"][0]["issuer_published_at"])

    def test_old_period_is_unavailable_before_actual_capture(self):
        self.capture()
        self.assertEqual(select_asof(self.root, "2026-11-17T00:59:59Z"), [])
        self.assertEqual(len(select_asof(self.root, FIRST)), 1)

    def test_value_change_preserves_old_version_and_supersession(self):
        self.capture()
        row = row_fixture()
        row["基本每股盈餘（元）"] = "2.70"
        self.capture(raw(row), SECOND)
        earlier = select_asof(self.root, "2026-11-18T00:59:59Z")[0]
        later = select_asof(self.root, SECOND)[0]
        self.assertEqual(earlier["payload"]["row"]["基本每股盈餘（元）"], "2.60")
        self.assertEqual(later["payload"]["row"]["基本每股盈餘（元）"], "2.70")
        self.assertEqual(later["previous_version_id"], earlier["version_id"])
        self.assertEqual(later["change_class"], "OBSERVED_VALUES_CHANGED_UNCLASSIFIED")

    def test_daily_batch_stamp_alone_is_not_a_financial_revision(self):
        self.capture()
        row = row_fixture()
        row["出表日期"] = "1151118"
        report = self.capture(raw(row), SECOND)
        self.assertEqual(report["new_versions"], 0)
        self.assertEqual(report["snapshot_count"], 2)
        self.assertEqual(len(verify_archive(self.root)["versions"]), 1)

    def test_different_quarter_has_a_separate_chain(self):
        self.capture()
        row = row_fixture()
        row["季別"] = "2"
        self.capture(raw(row), SECOND)
        selected = select_asof(self.root, SECOND)
        self.assertEqual({v["fiscal_period"] for v in selected}, {"2026Q2", "2026Q3"})
        self.assertTrue(all(v["previous_version_id"] is None for v in selected))

    def test_corrupt_original_is_rejected_before_selection_or_append(self):
        self.capture()
        receipt = verify_archive(self.root)["snapshots"][0]
        (self.root / receipt["archive_path"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ContractError, "ARCHIVE_HASH_MISMATCH"):
            select_asof(self.root, SECOND)
        with self.assertRaises(ContractError):
            self.capture(stamp=SECOND)

    def test_rehashed_payload_tampering_still_fails_original_reparse(self):
        self.capture()
        def edit(ledger):
            v = ledger["versions"][0]
            v["payload"]["row"]["基本每股盈餘（元）"] = "999"
            v["payload_sha256"] = digest(v["payload"])
            v["version_id"] = digest({k: x for k, x in v.items() if k != "version_id"})
        self.edit_ledger(edit)
        with self.assertRaisesRegex(ContractError, "DIFFERS_FROM_ORIGINAL"):
            verify_archive(self.root)

    def test_rehashed_backdated_availability_is_rejected(self):
        self.capture()
        def edit(ledger):
            v = ledger["versions"][0]
            v["available_at"] = "2026-01-01T00:00:00Z"
            v["version_id"] = digest({k: x for k, x in v.items() if k != "version_id"})
        self.edit_ledger(edit)
        with self.assertRaisesRegex(ContractError, "BACKDATED_AVAILABILITY"):
            verify_archive(self.root)

    def test_missing_raw_source_cannot_be_replaced_by_ledger_assertion(self):
        self.capture()
        receipt = verify_archive(self.root)["snapshots"][0]
        (self.root / receipt["archive_path"]).unlink()
        with self.assertRaises(OSError):
            verify_archive(self.root)

    def test_duplicate_or_missing_issuer_fails_without_writing_ledger(self):
        for rows in ([row_fixture(), row_fixture()], [dict(row_fixture(), 公司代號="0002")]):
            with self.assertRaisesRegex(ContractError, "MISSING_OR_DUPLICATE_ISSUER"):
                self.capture(canonical(rows))
        self.assertFalse((self.root / "ledger.json").exists())

    def test_naive_future_and_nonmonotonic_capture_clocks_are_rejected(self):
        with self.assertRaises(ContractError):
            self.capture(stamp="2026-11-17T01:00:00")
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with self.assertRaises(ContractError):
            self.capture(stamp=future)
        self.capture(stamp=SECOND)
        with self.assertRaisesRegex(ContractError, "CANNOT_BE_BACKDATED"):
            self.capture(stamp=FIRST)

    def test_future_fiscal_period_is_not_accepted(self):
        row = row_fixture()
        row["年度"] = "116"
        with self.assertRaisesRegex(ContractError, "PERIOD_HAS_NOT_ENDED"):
            self.capture(raw(row))

    def test_batch_day_from_the_future_is_not_accepted(self):
        row = row_fixture()
        row["出表日期"] = "1151118"
        with self.assertRaisesRegex(ContractError, "BATCH_AFTER_OBSERVATION"):
            self.capture(raw(row))

    def test_wrong_supersession_is_rejected_even_with_recomputed_version_hash(self):
        self.capture()
        row = row_fixture()
        row["基本每股盈餘（元）"] = "2.70"
        self.capture(raw(row), SECOND)
        def edit(ledger):
            v = ledger["versions"][-1]
            v["previous_version_id"] = None
            v["version_id"] = digest({k: x for k, x in v.items() if k != "version_id"})
        self.edit_ledger(edit)
        with self.assertRaisesRegex(ContractError, "BROKEN_FINANCIAL_VERSION_CHAIN"):
            verify_archive(self.root)

    def test_unsafe_source_path_fails_closed(self):
        self.capture()
        def edit(ledger):
            s = ledger["snapshots"][0]
            s["archive_path"] = "../outside.json.gz"
            s["snapshot_id"] = digest({k: v for k, v in s.items() if k != "snapshot_id"})
        self.edit_ledger(edit)
        with self.assertRaisesRegex(ContractError, "PATH_HASH_MISMATCH"):
            verify_archive(self.root)


if __name__ == "__main__":
    unittest.main()
