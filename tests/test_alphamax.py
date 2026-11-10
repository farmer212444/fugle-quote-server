"""All fixtures here are artificial and are never published as investment returns."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from alphamax.core import (
    FEATURES, REQUIRED_GATES, ContractError, TradingCosts, fit_asof,
    load_bundle, rank_asof, walk_forward,
)
from scripts.alphamax_run import readiness, research


def sample_rows():
    rows = []
    for month in range(1, 49):
        year, m = 2020 + (month-1)//12, (month-1)%12+1
        signal = date(year, m, 1)
        for idx in range(12):
            features = {name: (idx-5)/15 + month/120 + (j%3)*idx/100
                        for j, name in enumerate(FEATURES)}
            row = {
                "code": str(1000+idx), "signal_date": signal.isoformat(),
                "feature_available_at": {name: signal.isoformat() for name in FEATURES},
                "features": features, "execution_possible": True,
                "total_return_12m": 0.04+idx/100+month/500,
                "label_available_at": (signal + timedelta(days=370)).isoformat()
            }
            rows.append(row)
    return rows


class AlphaMaxTests(unittest.TestCase):
    def test_costs_applied_to_both_sides(self):
        x = TradingCosts()
        self.assertLess(x.net(0), 0)
        self.assertLess(x.net(.20), .20)
        self.assertAlmostEqual(TradingCosts(0,0,0,0).net(.2), .2)

    def test_no_matured_labels_cannot_train(self):
        with self.assertRaisesRegex(ContractError, "INSUFFICIENT_MATURED"):
            fit_asof(sample_rows(), "2020-05-01")

    def test_model_uses_only_historical_matured_labels(self):
        rows = sample_rows()
        before = rank_asof(rows, "2023-09-01")
        # Change labels from post-cutoff records: results MUST remain unchanged.
        for row in rows:
            if row["label_available_at"] >= "2023-09-01":
                row["total_return_12m"] = 7.0
        after = rank_asof(rows, "2023-09-01")
        self.assertEqual(before["candidates"], after["candidates"])
        self.assertEqual(before["model"]["coefficients"], after["model"]["coefficients"])

    def test_signal_ranking_is_deterministic(self):
        out = rank_asof(sample_rows(), "2023-11-01")
        self.assertEqual(len(out["candidates"]), 12)
        self.assertEqual(out["status"], "UNCALIBRATED_RESEARCH_ONLY")
        scores = [r["predicted_net_return_12m"] for r in out["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_walk_forward_only_matured_full_cohorts(self):
        rows = sample_rows()
        out = walk_forward(rows, "2024-07-01", top_n=5)
        self.assertGreater(out["cohort_count"], 0)
        self.assertLessEqual(max(x["signal_date"] for x in out["cohorts"]), "2023-06-01")
        self.assertNotIn("cagr", out)

    def test_infeasible_stocks_are_not_bought(self):
        rows = sample_rows()
        rows[-1]["execution_possible"] = False
        rank = rank_asof(rows, "2023-12-01")
        self.assertEqual(len(rank["candidates"]), 11)

    def _bundle(self, root, rows=None, gates=None):
        folder = Path(root) / "data"
        folder.mkdir()
        raw = "".join(json.dumps(x, sort_keys=True)+"\n" for x in (rows or sample_rows())).encode()
        (folder/"observations.jsonl").write_bytes(raw)
        manifest = {
            "schema": "alphamax-research-v1",
            "gates": gates if gates is not None else {x:True for x in REQUIRED_GATES},
            "observations_sha256": hashlib.sha256(raw).hexdigest(),
            "source_receipts": ["synthetic-test-receipt"],
        }
        (folder/"manifest.json").write_text(json.dumps(manifest))
        return folder

    def test_manifest_gate_and_sha_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = self._bundle(temp, gates={x:False for x in REQUIRED_GATES})
            with self.assertRaisesRegex(ContractError, "UNCERTIFIED_DATA_GATES"):
                load_bundle(folder)
        with tempfile.TemporaryDirectory() as temp:
            folder = self._bundle(temp)
            (folder/"observations.jsonl").write_text("{}\n")
            with self.assertRaisesRegex(ContractError, "SHA256_MISMATCH"):
                load_bundle(folder)

    def test_future_feature_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            rows = sample_rows()
            rows[0]["feature_available_at"][FEATURES[0]] = "2020-02-01"
            folder = self._bundle(temp, rows=rows)
            with self.assertRaisesRegex(ContractError, "FUTURE_OR_INVALID_FEATURE"):
                load_bundle(folder)

    def test_duplicate_security_date_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            rows = sample_rows()
            rows.append(dict(rows[0]))
            folder = self._bundle(temp, rows=rows)
            with self.assertRaisesRegex(ContractError, "DUPLICATE"):
                load_bundle(folder)

    def test_research_runs_only_on_explicit_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = self._bundle(temp)
            result = research(folder, "2023-11-01", top_n=5)
            self.assertEqual(result["status"], "UNCALIBRATED_RESEARCH_ONLY")
            self.assertTrue(result["predictions"])

    def test_research_backtest_does_not_look_past_requested_asof(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = self._bundle(temp)
            result = research(folder, "2023-11-01", top_n=5)
            cohorts = result["backtest"].get("cohorts", [])
            self.assertTrue(all(x["signal_date"] < "2023-11-01" for x in cohorts))
            # All 12-month labels for the 2023 cohorts mature after this as-of.
            self.assertTrue(all(x["signal_date"] <= "2022-10-01" for x in cohorts))

    def test_live_repository_is_blocked_without_total_return_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prices = root/"tw-market-data/prices"
            prices.mkdir(parents=True)
            (prices/"latest_manifest.json").write_text(json.dumps({
                "date":"2026-11-09",
                "unadjusted_quotes":True,
                "security_master_verified":False,
            }))
            state = readiness(root, root/"alphamax/datasets/production")
            self.assertEqual(state["status"], "BLOCKED")
            self.assertIn("LEGACY_PRICES_NOT_TOTAL_RETURN_ADJUSTED", state["warnings"])
            self.assertIn("LEGACY_PIT_SECURITY_MASTER_NOT_VERIFIED", state["warnings"])


if __name__ == "__main__":
    unittest.main()
