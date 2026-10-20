"""Offline safety tests for the research-only institutional retreat watch."""
import datetime as dt
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.tw_chip_diagnostic import flows, join_market_codes, summarize
from scripts.tw_institutional_retreat import assess_retreat, load_issued_shares


class InstitutionalRetreatTests(unittest.TestCase):
    def share(self, count=100_000_000):
        return {"issued_shares": count, "source_date": "2026-10-17",
                "receipt_hash": "a" * 64, "official_source_receipt_hash": "b" * 64}

    def flow(self, trust=-350_000):
        return {"sessions": 20, "trust_net_shares": trust,
                "first_session": "2026-09-21", "last_session": "2026-10-19"}

    def test_exact_030pct_boundary_and_units(self):
        at = assess_retreat(self.flow(-300_000), self.share())
        self.assertEqual(at["status"], "OBSERVED_RETREAT_REQUIRES_FUNDAMENTAL_REVIEW")
        self.assertEqual(at["trust_net_20d_pct_issued_shares"], -0.3)
        self.assertFalse(at["auto_exit"])
        self.assertFalse(at["formal_rating_changed"])
        self.assertEqual(at["fundamental_confirmation"], "REQUIRES_SEPARATE_PIT_ACCOUNTING_EVIDENCE")
        near = assess_retreat(self.flow(-299_999), self.share())
        self.assertEqual(near["status"], "OBSERVED_NO_THRESHOLD_BREACH")
        # Official flow unit is individual shares, not trading lots.
        little = assess_retreat(self.flow(-300), self.share())
        self.assertEqual(little["status"], "OBSERVED_NO_THRESHOLD_BREACH")

    def test_missing_history_and_denominator_fail_closed(self):
        self.assertEqual(assess_retreat(None, self.share())["status"],
                         "PENDING_20_SESSION_EVIDENCE")
        self.assertEqual(assess_retreat({"sessions": 19, "trust_net_shares": -500000}, self.share())["status"],
                         "PENDING_20_SESSION_EVIDENCE")
        self.assertEqual(assess_retreat(self.flow(), None)["status"],
                         "PENDING_DATED_ISSUED_SHARE_DENOMINATOR")
        self.assertEqual(assess_retreat(self.flow(), {"issued_shares": 0})["status"],
                         "PENDING_INVALID_SHARE_DENOMINATOR")
        self.assertEqual(assess_retreat(self.flow("800"), self.share())["status"],
                         "PENDING_INVALID_FLOW_UNITS")

    def make_snapshot(self, root, available="2026-10-18T08:00:00+00:00",
                      source_date="1151017", issued=200991673.0):
        p = root / "evidence/v880"
        p.mkdir(parents=True, exist_ok=True)
        snapshot = {"snapshot_available_at": available,
                    "master": {"9802": {"market": "TWSE", "date": source_date,
                                        "issued_shares": issued, "source_sha256": "c" * 64}}}
        raw = json.dumps(snapshot).encode()
        packed = gzip.compress(raw, mtime=0)
        (p / "snapshot.json.gz").write_bytes(packed)
        (p / "manifest.json").write_text(json.dumps({
            "path": "evidence/v880/snapshot.json.gz",
            "gzip_sha256": hashlib.sha256(packed).hexdigest(),
            "json_sha256": hashlib.sha256(raw).hexdigest(),
            "available_at": available,
        }))
        return p

    def test_master_official_float_roc_date_source_hash_and_pit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make_snapshot(root)
            records = load_issued_shares(root, "2026-10-19")
            s = records[("TWSE", "9802")]
            self.assertEqual(s["issued_shares"], 200991673)
            self.assertEqual(s["source_date"], "2026-10-17")
            self.assertEqual(s["official_source_receipt_hash"], "c" * 64)
            with self.assertRaisesRegex(ValueError, "NOT_AVAILABLE_AT_PRICE_DATE"):
                load_issued_shares(root, "2026-10-17")

    def test_master_hash_and_future_dated_rows_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = self.make_snapshot(root)
            (p / "snapshot.json.gz").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "ARCHIVE_HASH_MISMATCH"):
                load_issued_shares(root, "2026-10-19")
            self.make_snapshot(root, source_date="1151020")
            with self.assertRaisesRegex(ValueError, "NO_ELIGIBLE_DATED"):
                load_issued_shares(root, "2026-10-19")

    def test_report_gates_no_automatic_grade_or_exit(self):
        queue = {"model": "V8.8.2", "normalized_financial_issuers": 1,
                 "queues": [{"code": "9802", "market": "TWSE"}],
                 "normalized_not_yet_modeled": []}
        sessions = []
        for i in range(20):
            date = (dt.date(2026, 10, 19) - dt.timedelta(days=i)).isoformat()
            data = {"market": "TWSE", "code": "9802", "date": date,
                    "foreign_ex_dealer_net_shares": 0, "trust_net_shares": -20000,
                    "dealer_net_shares": 0, "official_total_net_shares": -20000}
            sessions.append((date, {("TWSE", "9802"): data}))
        shares = {("TWSE", "9802"): self.share()}
        report = summarize(queue, "2026-10-19", sessions, [], join_market_codes(queue), [], shares)
        signal = report["stocks"][0]["institutional_retreat_20d"]
        self.assertEqual(signal["status"], "OBSERVED_RETREAT_REQUIRES_FUNDAMENTAL_REVIEW")
        self.assertEqual(signal["trust_net_shares_20d"], -400000)
        self.assertFalse(report["ranking_safe"])
        self.assertEqual(report["formal_Aplus_count_derived_from_chip"], 0)
        prior = summarize(queue, "2026-10-18", sessions, [], join_market_codes(queue), [], shares)
        self.assertEqual(prior["stocks"][0]["institutional_retreat_20d"]["status"],
                         "PENDING_20_SESSION_EVIDENCE")

    def test_missing_individual_issuer_day_is_not_imputed(self):
        dated = [(f"2026-10-{d:02d}", {("TWSE", "9802"): {"trust_net_shares": -20000,
                      "foreign_ex_dealer_net_shares": 0, "dealer_net_shares": 0,
                      "official_total_net_shares": -20000}})
                 for d in range(20, 0, -1)]
        dated[9][1].clear()
        self.assertIsNone(flows(dated, ("TWSE", "9802"), 20))


if __name__ == "__main__":
    unittest.main()
