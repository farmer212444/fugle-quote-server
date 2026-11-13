"""Synthetic-only contract tests; artificial returns are not investment performance."""
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
import copy
import json
import tempfile
import unittest

from alphahunter.core import (
    EvidenceError, GATES, FEATURES, load_bundle,
    matured_cohort_diagnostics, rank_asof, validate_rows,
)
from scripts.alphahunter_run import readiness, research


def sample_rows():
    rows = []
    for month in range(1, 37):
        year, mo = 2022 + (month - 1) // 12, (month - 1) % 12 + 1
        signal = date(year, mo, 1)
        for i in range(5):
            rows.append({
                "code": str(2300 + i),
                "signal_date": signal.isoformat(),
                "reference_price": 100.0,
                "reference_price_available_at": signal.isoformat(),
                "forecast_available_at": signal.isoformat(),
                "execution_possible": True,
                "features": {
                    "revenue_yoy": 0.12 + i * 0.02,
                    "gross_margin_change_pp": float(i),
                    "cash_conversion": 1.0 - i * 0.04,
                    "net_debt_to_ebitda": 1.0,
                },
                "feature_available_at": {feature: signal.isoformat() for feature in FEATURES},
                "scenarios": {
                    "bear": {"eps": 5.0 + i * 0.1, "pe": 12.0, "dividend": 1.0},
                    "base": {"eps": 8.0 + i * 0.2, "pe": 14.0, "dividend": 2.0},
                    "bull": {"eps": 10.0 + i * 0.3, "pe": 17.0, "dividend": 3.0},
                },
                "realized_total_return_12m": 0.05 + i * 0.02,
                "label_available_at": (signal + timedelta(days=370)).isoformat(),
            })
    return rows


def create_bundle(root, rows=None, gates=None):
    root = Path(root) / "bundle"
    root.mkdir(parents=True, exist_ok=True)
    if rows is None:
        rows = sample_rows()
    raw = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8")
    (root / "observations.jsonl").write_bytes(raw)
    manifest = {
        "schema": "alphahunter-research-v1",
        "observations_sha256": sha256(raw).hexdigest(),
        "gates": gates if gates is not None else {g: True for g in GATES},
        "source_receipts": ["synthetic-only-not-real-source"],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


class AlphaHunterResearchTests(unittest.TestCase):
    def test_scores_sorted_and_explicitly_uncalibrated(self):
        report = rank_asof(sample_rows(), "2024-12-01")
        scores = [r["risk_adjusted_research_score"] for r in report["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertFalse(report["assumption_probability_calibrated"])
        self.assertTrue(report["not_a_buy_signal"])

    def test_future_labels_never_influence_rank_or_score(self):
        rows = sample_rows()
        first = rank_asof(rows, "2024-11-01")["candidates"]
        for row in rows:
            if row["label_available_at"] > "2024-11-01":
                row["realized_total_return_12m"] = 1000.0
        second = rank_asof(rows, "2024-11-01")["candidates"]
        self.assertEqual(first, second)

    def test_rank_excludes_unexecutable_quotes(self):
        rows = sample_rows()
        rows[-1]["execution_possible"] = False
        out = rank_asof(rows, "2024-12-01")
        self.assertEqual(out["candidate_count"], 4)

    def test_forecast_published_after_signal_is_rejected(self):
        rows = sample_rows()
        rows[0]["forecast_available_at"] = "2026-11-13"
        with self.assertRaisesRegex(EvidenceError, "FUTURE_FORECAST"):
            validate_rows(rows)

    def test_future_quote_rejected(self):
        rows = sample_rows()
        rows[0]["reference_price_available_at"] = "2026-11-13"
        with self.assertRaisesRegex(EvidenceError, "FUTURE_REFERENCE_PRICE"):
            validate_rows(rows)

    def test_future_financial_feature_rejected(self):
        rows = sample_rows()
        rows[0]["feature_available_at"]["gross_margin_change_pp"] = "2026-11-13"
        with self.assertRaisesRegex(EvidenceError, "FUTURE_FEATURE"):
            validate_rows(rows)

    def test_duplicate_issuer_signal_rejected(self):
        rows = sample_rows()
        rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(EvidenceError, "DUPLICATE"):
            validate_rows(rows)

    def test_premature_12m_label_rejected(self):
        rows = sample_rows()
        rows[0]["label_available_at"] = "2022-08-01"
        with self.assertRaisesRegex(EvidenceError, "PREMATURE"):
            validate_rows(rows)

    def test_12m_feb29_boundary(self):
        rows = sample_rows()
        rows[0]["signal_date"] = "2024-02-29"
        rows[0]["reference_price_available_at"] = "2024-02-29"
        rows[0]["forecast_available_at"] = "2024-02-29"
        rows[0]["feature_available_at"] = {feature: "2024-02-29" for feature in FEATURES}
        rows[0]["label_available_at"] = "2025-02-27"
        with self.assertRaisesRegex(EvidenceError, "PREMATURE"):
            validate_rows(rows)
        rows[0]["label_available_at"] = "2025-02-28"
        self.assertEqual(len(validate_rows(rows)), len(rows))

    def test_nonfinite_scenario_rejected(self):
        rows = sample_rows()
        rows[0]["scenarios"]["base"]["eps"] = float("nan")
        with self.assertRaisesRegex(EvidenceError, "NONFINITE"):
            validate_rows(rows)

    def test_scenarios_must_order_from_bear_to_bull(self):
        rows = sample_rows()
        rows[0]["scenarios"]["bear"]["eps"] = 50
        with self.assertRaisesRegex(EvidenceError, "SCENARIOS_NOT_ORDERED"):
            validate_rows(rows)

    def test_digest_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = create_bundle(temp)
            with (bundle / "observations.jsonl").open("ab") as output:
                output.write(b"{}\n")
            with self.assertRaisesRegex(EvidenceError, "SHA256_MISMATCH"):
                load_bundle(bundle)

    def test_undeclared_evidence_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = create_bundle(temp, gates={g: False for g in GATES})
            with self.assertRaisesRegex(EvidenceError, "UNVERIFIED_EVIDENCE_GATES"):
                load_bundle(bundle)

    def test_missing_production_bundle_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            out = readiness(Path(temp) / "production")
            self.assertEqual(out["status"], "BLOCKED")
            self.assertFalse(out["production_ranking_allowed"])

    def test_12m_diagnostics_exclude_unmatured_cohorts(self):
        out = matured_cohort_diagnostics(sample_rows(), "2024-12-01", top_n=2)
        self.assertTrue(out["cohorts"])
        self.assertLessEqual(max(x["signal_date"] for x in out["cohorts"]), "2023-11-01")
        self.assertNotIn("cagr", out)
        self.assertFalse(out["portfolio_cagr_certified"])

    def test_bundle_research_never_certs_investment(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = create_bundle(temp)
            out = research(bundle, "2024-12-01", top_n=3)
            self.assertEqual(out["candidate_count"], 5)
            self.assertEqual(len(out["candidates"]), 3)
            self.assertFalse(out["production_ranking_allowed"])
            self.assertEqual(readiness(bundle)["status"],
                             "INPUT_CONTRACT_PASSED_NOT_EXTERNALLY_AUDITED")


if __name__ == "__main__":
    unittest.main()
