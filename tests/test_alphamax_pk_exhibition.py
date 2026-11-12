"""Synthetic-only exhibition scorecard regression tests. Never real investment performance."""
from __future__ import annotations

import copy
from datetime import date, timedelta
import json
from pathlib import Path
import unittest

from alphamax.pk_exhibition import (
    BENCHMARK, PKContractError, evidence_scorecard,
    frozen_digest, observed_quotes, validate_freeze,
)

ROOT = Path(__file__).resolve().parents[1]


class ExhibitionPKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = ROOT / "alphamax/research/2026-11-11-v8-alphamax-pk-frozen.json"
        cls.frozen = json.loads(p.read_text(encoding="utf-8"))

    def quotes(self, multiplier=1.10):
        rows = []
        for lane in ("alpha_lane", "v8_lane"):
            for rec in self.frozen[lane]["rows"]:
                rows.append({
                    "market": rec["market"], "code": rec["code"],
                    "date": "2026-11-11",
                    "close": rec["reference_close"] * multiplier,
                    "fillability_verified": False,
                })
        rows.append({"market": "TWSE", "code": "0050",
                     "date": "2026-11-11", "close": 100,
                     "fillability_verified": False})
        return rows

    def evidence(self):
        days = [(date(2026, 11, 12) + timedelta(days=i)).isoformat()
                for i in range(22)]
        rows = []
        for lane in ("alpha_lane", "v8_lane"):
            for rec in self.frozen[lane]["rows"]:
                rows.append({
                    "market": rec["market"], "code": rec["code"],
                    "entry_session": days[0], "exit_session": days[-1],
                    "investor_total_return_factor": 1.10 if lane == "alpha_lane" else 0.90,
                    "corporate_actions_and_cash_dividends_reviewed": True,
                    "source_receipt_id": "synthetic-unreviewed",
                })
        rows.append({
            "market": BENCHMARK[0], "code": BENCHMARK[1],
            "entry_session": days[0], "exit_session": days[-1],
            "investor_total_return_factor": 1.02,
            "corporate_actions_and_cash_dividends_reviewed": True,
            "source_receipt_id": "synthetic-unreviewed",
        })
        return {
            "schema": "ALPHAMAX_PK_EXECUTIONS_V1",
            "holding_sessions": 21,
            "trading_sessions": days,
            "entry_session": days[0], "exit_session": days[-1],
            "data_matured_at": days[-1],
            "source_receipts": ["synthetic-unreviewed"],
            "total_return_factors": rows,
        }

    def test_frozen_input_is_immutable_contract(self):
        names = validate_freeze(self.frozen)
        self.assertEqual(len(names["alpha_lane"]), 10)
        self.assertEqual(len(names["v8_lane"]), 10)
        self.assertFalse(names["alpha_lane"] & names["v8_lane"])
        self.assertEqual(len(frozen_digest(self.frozen)), 64)

    def test_observed_daily_close_is_not_an_executable_pk_return(self):
        out = observed_quotes(self.frozen, self.quotes(), "2026-11-11",
                              {"date": "2026-11-11", "unadjusted_quotes": True})
        self.assertEqual(out["lanes"]["alpha_lane"]["quote_coverage"], 10)
        self.assertAlmostEqual(out["lanes"]["alpha_lane"]["raw_equal_weight_close_change_pct"], 10.0, places=4)
        self.assertIsNone(out["official_winner"])
        self.assertIsNone(out["verified_net_returns"])
        self.assertFalse(out["is_model_vs_model"])
        self.assertFalse(out["fair_executable_entry_approved"])

    def test_same_day_quotes_are_not_postfreeze_returns(self):
        rows = self.quotes()
        for row in rows:
            row["date"] = "2026-11-10"
        out = observed_quotes(self.frozen, rows, "2026-11-10")
        self.assertIsNone(out["lanes"]["alpha_lane"]["raw_equal_weight_close_change_pct"])
        self.assertIsNone(out["official_winner"])

    def test_missing_quote_fails_closed_as_full_basket(self):
        rows = self.quotes()
        rows = rows[1:]
        out = observed_quotes(self.frozen, rows, "2026-11-11")
        self.assertEqual(out["lanes"]["alpha_lane"]["quote_coverage"], 9)
        self.assertIsNone(out["lanes"]["alpha_lane"]["raw_equal_weight_close_change_pct"])

    def test_duplicate_or_wrong_date_price_rejected(self):
        rows = self.quotes()
        with self.assertRaisesRegex(PKContractError, "DUPLICATE_MARKET_CODE"):
            observed_quotes(self.frozen, rows + [rows[0]], "2026-11-11")
        rows[0]["date"] = "2026-11-10"
        with self.assertRaisesRegex(PKContractError, "MIXED_PRICE_SESSION_DATES"):
            observed_quotes(self.frozen, rows, "2026-11-11")

    def test_mismatched_snapshot_manifest_rejected(self):
        with self.assertRaisesRegex(PKContractError, "MANIFEST_SNAPSHOT_DATE_MISMATCH"):
            observed_quotes(self.frozen, self.quotes(), "2026-11-11",
                            {"date": "2026-11-10", "unadjusted_quotes": True})

    def test_bad_close_does_not_count_as_price(self):
        rows = self.quotes()
        rows[0]["close"] = True
        out = observed_quotes(self.frozen, rows, "2026-11-11")
        self.assertEqual(out["lanes"]["alpha_lane"]["quote_coverage"], 9)

    def test_tampered_frozen_names_rejected(self):
        frozen = copy.deepcopy(self.frozen)
        frozen["alpha_lane"]["rows"][0]["rank"] = 3
        with self.assertRaisesRegex(PKContractError, "FROZEN_RANK_ORDER_CHANGED"):
            validate_freeze(frozen)

    def test_future_evidence_is_illustrative_not_certified(self):
        out = evidence_scorecard(self.frozen, self.evidence())
        self.assertEqual(out["status"], "CONTRACT_ONLY_EXTERNAL_AUDIT_REQUIRED")
        self.assertFalse(out["is_model_vs_model"])
        self.assertIsNone(out["official_winner"])
        self.assertFalse(out["external_audit_complete"])
        a = out["lanes"]["alpha_lane"]["unverified_equal_weight_net_total_return_pct"]
        b = out["lanes"]["v8_lane"]["unverified_equal_weight_net_total_return_pct"]
        self.assertGreater(a, b)
        self.assertLess(a, 10.0)

    def test_no_backdated_fills(self):
        source = self.evidence()
        source["trading_sessions"][0] = "2026-11-11"
        source["entry_session"] = "2026-11-11"
        with self.assertRaisesRegex(PKContractError, "SESSION_START_NOT_STRICTLY_AFTER_FREEZE"):
            evidence_scorecard(self.frozen, source)

    def test_incomplete_holding_period_rejected(self):
        source = self.evidence()
        source["trading_sessions"].pop()
        with self.assertRaisesRegex(PKContractError, "UNVERIFIED_TRADING_SESSION_COUNT"):
            evidence_scorecard(self.frozen, source)

    def test_outcome_cannot_mature_before_exit(self):
        source = self.evidence()
        source["data_matured_at"] = source["entry_session"]
        with self.assertRaisesRegex(PKContractError, "FUTURE_OUTCOME_LEAKAGE"):
            evidence_scorecard(self.frozen, source)

    def test_benchmark_and_delisted_coverage_cannot_disappear(self):
        source = self.evidence()
        source["total_return_factors"].pop()
        with self.assertRaisesRegex(PKContractError, "TWENTY_STOCKS_PLUS_ETF_REQUIRED"):
            evidence_scorecard(self.frozen, source)

    def test_source_receipt_required(self):
        source = self.evidence()
        source["total_return_factors"][0]["source_receipt_id"] = ""
        with self.assertRaisesRegex(PKContractError, "UNRECONCILED_SOURCE_RECEIPT"):
            evidence_scorecard(self.frozen, source)

    def test_no_dividend_and_corporate_action_assumption(self):
        source = self.evidence()
        source["total_return_factors"][0]["corporate_actions_and_cash_dividends_reviewed"] = False
        with self.assertRaisesRegex(PKContractError, "CORPORATE_ACTIONS_OR_DIVIDENDS_MISSING"):
            evidence_scorecard(self.frozen, source)


if __name__ == "__main__":
    unittest.main()
