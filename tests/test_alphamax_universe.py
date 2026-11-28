"""Synthetic regression tests for AlphaMax PIT-universe evidence diagnostics."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from alphamax.universe_audit import audit_history


def build(root, *, history=None, packet=None, date="2026-11-10"):
    prices = root / "tw-market-data/prices"
    prices.mkdir(parents=True)
    (prices / "latest_manifest.json").write_text(json.dumps({
        "date": date, "unadjusted_quotes": True, "security_master_verified": False,
    }))
    (prices / (date + ".json")).write_text(json.dumps([
        {"code": "2330", "market": "TWSE", "date": date, "close": 100.0},
        {"code": "5274", "market": "TPEX", "date": date, "close": 200.0},
    ]))
    if history is None:
        history = [
            {"date": "2026-11-09", "close": 95.0, "turnover_ntd": 1_000_000},
            {"date": "2026-11-10", "close": 100.0, "turnover_ntd": 2_000_000},
        ]
    item = {
        "market": "TWSE", "issuer": "2330", "sessions": history,
        "issuer_PIT_history_verified": False,
        "share_adjusted_history": False,
        "formal_tradability_gate": "PENDING_NOT_CERTIFIED",
    }
    item.update(packet or {})
    directory = prices / "issuer_history/TWSE"
    directory.mkdir(parents=True)
    (directory / "2330.json").write_text(json.dumps(item))


class UniverseAuditTests(unittest.TestCase):
    def test_observed_quotes_do_not_certify_pit(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            a = audit_history(root, min_sessions=2)
            self.assertEqual(a["status"], "BLOCKED_NOT_A_PIT_SECURITY_MASTER")
            self.assertEqual(a["counts"]["history_files_ge_min_sessions"], 1)
            self.assertEqual(a["snapshot_without_well_formed_history"], 1)
            self.assertIn("TPEX:5274", a["missing_sample"])
            self.assertEqual(a["counts"]["history_files_with_independent_issuer_pit"], 0)

    def test_duplicate_historical_date_is_rejected_not_overcounted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hist = [{"date": "2026-11-09", "close": 99, "turnover_ntd": 1},
                    {"date": "2026-11-09", "close": 99, "turnover_ntd": 1}]
            build(root, history=hist)
            a = audit_history(root)
            self.assertEqual(a["counts"]["invalid_history_files"], 1)
            self.assertIn("DUPLICATE", a["invalid_sample"][0]["reason"])
            self.assertEqual(a["snapshot_without_well_formed_history"], 2)

    def test_future_session_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, history=[{"date": "2026-11-11", "close": 99, "turnover_ntd": 1}])
            a = audit_history(root)
            self.assertIn("FUTURE", a["invalid_sample"][0]["reason"])

    def test_market_and_issuer_mismatch_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, packet={"issuer": "2317"})
            a = audit_history(root)
            self.assertIn("IDENTITY_MISMATCH", a["invalid_sample"][0]["reason"])

    def test_security_in_history_but_not_snapshot_is_not_delisted_claim(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            history = root / "tw-market-data/prices/issuer_history/TWSE/2330.json"
            new = json.loads(history.read_text())
            new["issuer"] = "9999"
            (history.parent / "9999.json").write_text(json.dumps(new))
            a = audit_history(root)
            self.assertEqual(a["counts"]["history_files_not_in_snapshot"], 1)
            self.assertIn("TWSE:9999", a["history_not_in_latest_quote_sample"])
            self.assertIn("SURVIVORSHIP_BIAS_NOT_EXCLUDED", a["blocking_reasons"])

    def test_unsupported_price_gap_remains_blocked_even_if_count_sufficient(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, packet={
                "share_adjusted_history": True, "dividend_total_return_verified": True,
                "issuer_PIT_history_verified": True,
                "official_dated_security_master_receipt": "synthetic-only",
                "formal_tradability_gate": "VERIFIED_EXECUTABLE",
            })
            a = audit_history(root, min_sessions=2)
            self.assertEqual(a["status"], "BLOCKED_NOT_A_PIT_SECURITY_MASTER")
            self.assertEqual(a["counts"]["history_files_with_verified_corporate_actions"], 1)
            self.assertEqual(a["counts"]["history_files_with_independent_issuer_pit"], 1)

    def test_empty_snapshot_no_divide_by_zero(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            file = root / "tw-market-data/prices/2026-11-10.json"
            file.write_text("[]")
            a = audit_history(root)
            self.assertIsNone(a["snapshot_history_coverage_ratio"])
            self.assertEqual(a["status"], "BLOCKED_NOT_A_PIT_SECURITY_MASTER")

    def test_missing_or_invalid_manifest_blocks(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(audit_history(root)["reason"], "PRICE_MANIFEST_MISSING")
            build(root)
            (root / "tw-market-data/prices/latest_manifest.json").write_text("{}")
            self.assertEqual(audit_history(root)["status"], "BLOCKED")

    def test_duplicates_in_current_snapshot_block(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            file = root / "tw-market-data/prices/2026-11-10.json"
            arr = json.loads(file.read_text())
            arr.append(arr[0])
            file.write_text(json.dumps(arr))
            a = audit_history(root)
            self.assertEqual(a["status"], "BLOCKED")
            self.assertIn("DUPLICATE", a["reason"])

    def test_null_close_is_retained_as_unpriced_not_executable(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            file = root / "tw-market-data/prices/2026-11-10.json"
            rows = json.loads(file.read_text())
            rows[0]["close"] = None
            file.write_text(json.dumps(rows))
            a = audit_history(root, min_sessions=2)
            self.assertEqual(a["status"], "BLOCKED_NOT_A_PIT_SECURITY_MASTER")
            self.assertEqual(a["current_quote_snapshot_securities"], 2)
            self.assertEqual(a["current_quote_rows_without_positive_close"], 1)
            self.assertIn("TWSE:2330", a["current_quote_unpriced_sample"])

    def test_missing_snapshots_block(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            (root / "tw-market-data/prices/2026-11-10.json").unlink()
            self.assertEqual(audit_history(root)["reason"], "MATCHING_PRICE_SNAPSHOT_MISSING")

    def test_unpriced_history_is_kept_but_never_counted_as_valid_return(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, history=[{"date": "2026-11-09", "close": None, "turnover_ntd": 1},
                                 {"date": "2026-11-10", "close": 100, "turnover_ntd": 1}])
            a = audit_history(root, min_sessions=2)
            self.assertEqual(a["counts"]["invalid_history_files"], 0)
            self.assertEqual(a["counts"]["unpriced_historical_sessions"], 1)
            self.assertEqual(a["counts"]["history_files_with_unpriced_sessions"], 1)
            self.assertEqual(a["counts"]["history_files_ge_min_sessions"], 0)
            self.assertEqual(a["counts"]["present_in_snapshot_with_history"], 1)

    def test_all_unpriced_session_file_is_not_tradable_history(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root, history=[{"date": "2026-11-09", "close": None, "turnover_ntd": 0}])
            a = audit_history(root)
            self.assertEqual(a["counts"]["history_files_without_any_positive_close"], 1)
            self.assertEqual(a["counts"]["present_in_snapshot_with_history"], 0)
            self.assertEqual(a["snapshot_without_well_formed_history"], 2)

    def test_future_max_example_guard(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            self.assertEqual(audit_history(root, max_examples=0)["missing_sample"], [])


if __name__ == "__main__":
    unittest.main()
