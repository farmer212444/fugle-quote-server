"""Synthetic-only tests: past raw prices and 0050 cannot certify training labels."""
from __future__ import annotations

import copy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from alphamax.pit_pk_gap_audit import audit_frozen_pit_gaps, _priced_sessions, PKContractError

FREEZE = Path(__file__).resolve().parents[1] / "alphamax/research/2026-11-11-v8-alphamax-pk-frozen.json"


class PITPKGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
        cls.keys = sorted({(r["market"], r["code"]) for lane in ("alpha_lane", "v8_lane")
                           for r in cls.freeze[lane]["rows"]} | {("TWSE", "0050")})

    @staticmethod
    def packet(market, code, count=253, span=370):
        start = date(2025, 1, 2)
        days = [start + timedelta(days=round(i * span / (count - 1))) for i in range(count)]
        return {"issuer": code, "market": market,
                "sessions": [{"date": d.isoformat(), "market": market, "code": code,
                              "close": 101.0, "turnover_ntd": 3_000_000}
                             for d in days],
                "share_adjusted_history": False,
                "dividend_total_return_verified": False,
                "issuer_PIT_history_verified": False,
                "formal_tradability_gate": "PENDING_NOT_CERTIFIED"}

    def write_all(self, root, benchmark_short=True):
        for m, c in self.keys:
            p = Path(root) / m / (c + ".json")
            p.parent.mkdir(parents=True, exist_ok=True)
            packet = self.packet(m, c, 45, 65) if benchmark_short and c == "0050" else self.packet(m, c)
            p.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")

    def report(self, root, **kwargs):
        manifest = kwargs.get("price_manifest", {"date": "2026-11-12", "unadjusted_quotes": True})
        financial = kwargs.get("financial_manifest", {"issuer_exact_publication_time_verified": False})
        history = kwargs.get("historical_financial_status", {
            "admitted_historical_PIT_batches": 0, "original_publication_and_revision_PIT_verified": False})
        return audit_frozen_pit_gaps(self.freeze, root, manifest, financial, history)

    def test_0050_gap_blocks_even_when_all_twenty_stocks_have_long_raw_histories(self):
        with tempfile.TemporaryDirectory() as temp:
            self.write_all(temp)
            r = self.report(temp)
            self.assertEqual(r["benchmark_0050"]["priced_sessions"], 45)
            self.assertFalse(r["benchmark_0050"]["potential_12m_price_only_span"])
            self.assertEqual(r["lanes"]["alpha_lane"]["raw_quote_spans_at_least_12m"], 10)
            self.assertEqual(r["lanes"]["v8_lane"]["raw_quote_spans_at_least_12m"], 10)
            self.assertIn("0050_12M_QUOTE_BASELINE_INCOMPLETE", r["blockers"])
            self.assertFalse(r["independent_model_alpha_training_ready"])
            self.assertIsNone(r["winner"])

    def test_0050_long_raw_history_still_is_not_valid_dividend_adjusted_pit(self):
        with tempfile.TemporaryDirectory() as temp:
            self.write_all(temp, benchmark_short=False)
            r = self.report(temp)
            self.assertTrue(r["benchmark_0050"]["potential_12m_price_only_span"])
            self.assertNotIn("0050_12M_QUOTE_BASELINE_INCOMPLETE", r["blockers"])
            self.assertIn("ISSUER_PUBLICATION_AND_REVISION_PIT_NOT_ADMITTED", r["blockers"])
            self.assertIn("DIVIDENDS_SPLITS_DELISTING_TOTAL_RETURN_LEDGER_MISSING", r["blockers"])
            self.assertEqual(r["verified_12m_after_cost_walk_forward_cohorts"], 0)

    def test_missing_history_file_blocks_that_basket(self):
        with tempfile.TemporaryDirectory() as temp:
            self.write_all(temp)
            sample = self.freeze["alpha_lane"]["rows"][0]
            (Path(temp) / sample["market"] / (sample["code"] + ".json")).unlink()
            r = self.report(temp)
            self.assertEqual(r["lanes"]["alpha_lane"]["history_files"], 9)
            self.assertEqual(r["lanes"]["v8_lane"]["history_files"], 10)
            self.assertEqual(r["lanes"]["alpha_lane"]["raw_quote_spans_at_least_12m"], 9)
            self.assertEqual(r["lanes"]["alpha_lane"]["stocks"][0]["status"], "HISTORY_FILE_MISSING")

    def test_future_quote_or_duplicate_date_rejected(self):
        packet = self.packet("TWSE", "2330")
        packet["sessions"][0]["date"] = "2027-01-01"
        with self.assertRaisesRegex(PKContractError, "FUTURE_PRICE_OBSERVATION"):
            _priced_sessions(packet, "TWSE", "2330", date(2026, 11, 12))
        packet = self.packet("TWSE", "2330")
        packet["sessions"].append(copy.deepcopy(packet["sessions"][0]))
        with self.assertRaisesRegex(PKContractError, "DUPLICATE_HISTORICAL_SESSION"):
            _priced_sessions(packet, "TWSE", "2330", date(2026, 11, 12))

    def test_wrong_security_identity_rejected(self):
        packet = self.packet("TWSE", "2330")
        with self.assertRaisesRegex(PKContractError, "HISTORICAL_SECURITY_IDENTITY_MISMATCH"):
            _priced_sessions(packet, "TWSE", "9999", date(2026, 11, 12))

    def test_missing_issuer_pit_cannot_be_waived_by_batch_report(self):
        with tempfile.TemporaryDirectory() as temp:
            self.write_all(temp, benchmark_short=False)
            r = self.report(
                temp,
                financial_manifest={"issuer_exact_publication_time_verified": True},
                historical_financial_status={
                    "admitted_historical_PIT_batches": 0,
                    "original_publication_and_revision_PIT_verified": True},
            )
            self.assertFalse(r["issuer_publication_pit_admitted"])
            self.assertIsNone(r["winner"])

    def test_self_asserted_perfect_flags_do_not_complete_independent_external_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            self.write_all(temp, benchmark_short=False)
            for m, c in self.keys:
                path = Path(temp) / m / (c + ".json")
                packet = json.loads(path.read_text(encoding="utf-8"))
                packet.update({
                    "issuer_PIT_history_verified": True,
                    "official_dated_security_master_receipt": "synthetic-not-independent",
                    "share_adjusted_history": True,
                    "dividend_total_return_verified": True,
                    "corporate_actions_verified": True,
                    "formal_tradability_gate": "VERIFIED_EXECUTABLE",
                })
                path.write_text(json.dumps(packet), encoding="utf-8")
            r = self.report(temp, financial_manifest={"issuer_exact_publication_time_verified": True},
                            historical_financial_status={
                                "admitted_historical_PIT_batches": 2,
                                "original_publication_and_revision_PIT_verified": True})
            self.assertEqual(r["status"], "INPUT_FIELDS_SELF_REPORTED_REQUIRE_INDEPENDENT_AUDIT")
            self.assertFalse(r["independent_model_alpha_training_ready"])
            self.assertFalse(r["self_assertions_are_not_independent_audit"] is False)
            self.assertEqual(r["verified_12m_after_cost_walk_forward_cohorts"], 0)
            self.assertIsNone(r["winner"])

    def test_quote_manifest_must_be_postfreeze_and_unadjusted(self):
        with tempfile.TemporaryDirectory() as temp:
            self.write_all(temp)
            with self.assertRaisesRegex(PKContractError, "NO_POST_FREEZE_REFERENCE_SESSION"):
                self.report(temp, price_manifest={"date": "2026-11-11", "unadjusted_quotes": True})
            with self.assertRaisesRegex(PKContractError, "QUOTE_ADJUSTMENT_STATUS_UNKNOWN"):
                self.report(temp, price_manifest={"date": "2026-11-12", "unadjusted_quotes": None})


if __name__ == "__main__":
    unittest.main()
