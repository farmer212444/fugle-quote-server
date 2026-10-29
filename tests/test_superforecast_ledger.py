import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tw_model_v880.superforecast import issue, resolve, report

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 10, 29, 2, 0, tzinfo=UTC)
T1 = dt.datetime(2028, 1, 31, 2, 0, tzinfo=UTC)
H = "a" * 64


class SuperforecastLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.mkdir(parents=True, exist_ok=True)
        for name, content in [("input.txt", b"previously observed data"),
                              ("baseline.txt", b"reference class method"),
                              ("outcome.txt", b"audited observed outcome")]:
            (self.root / name).write_bytes(content)

    def proof(self, name):
        return dict(path=name, sha256=hashlib.sha256((self.root / name).read_bytes()).hexdigest())

    def spec(self, fid="FCAST_001", p=.7, baseline=.5):
        return dict(forecast_id=fid, market="TWSE", code="9802",
                    event_definition="2027 audited revenue YoY exceeds 10 percent",
                    event_due_date="2027-12-31", model_method_sha256=H,
                    probability=p, baseline_probability=baseline,
                    evidence=self.proof("input.txt"),
                    baseline_evidence=self.proof("baseline.txt") if baseline is not None else None)

    def outcome(self, fid="FCAST_001", y=True):
        return dict(forecast_id=fid, outcome=y,
                    verification_evidence=self.proof("outcome.txt"))

    def test_scoring_requires_preissue_and_matured_verified_outcome(self):
        issued = issue(self.root, self.spec(), now=T0)
        self.assertEqual(issued["issued_at_utc"], T0.isoformat())
        self.assertEqual(report(self.root, asof=T0, minimum=1)["status"], "UNCALIBRATED_INSUFFICIENT_OUTCOMES")
        with self.assertRaisesRegex(ValueError, "EVENT_NOT_YET_DUE"):
            resolve(self.root, self.outcome(), now=T0 + dt.timedelta(days=2))
        resolve(self.root, self.outcome(), now=T1)
        self.assertEqual(report(self.root, asof=T0, minimum=1)["scored_count"], 0)
        result = report(self.root, asof=T1, minimum=1)
        self.assertEqual(result["scored_count"], 1)
        self.assertAlmostEqual(result["brier_score"], .09)
        self.assertAlmostEqual(result["baseline_brier_score"], .25)
        self.assertAlmostEqual(result["brier_skill_score"], .64)
        self.assertFalse(result["promotes_Aplus"])
        self.assertFalse(result["investment_outperformance_proven"])

    def test_duplicate_issuance_and_outcome_cannot_overwrite(self):
        original = issue(self.root, self.spec(), now=T0)
        with self.assertRaises(FileExistsError):
            issue(self.root, self.spec(p=.9), now=T0 + dt.timedelta(hours=1))
        self.assertEqual(original, json.loads((self.root / "experiments/superforecast_v1/issued/FCAST_001.json").read_text()))
        resolve(self.root, self.outcome(), now=T1)
        with self.assertRaises(FileExistsError):
            resolve(self.root, self.outcome(y=False), now=T1 + dt.timedelta(days=1))

    def test_reject_retroactive_fake_probabilities_and_baselines(self):
        with self.assertRaisesRegex(ValueError, "FORECAST_MUST_PRECEDE_DUE_DATE"):
            issue(self.root, self.spec(), now=T1)
        with self.assertRaisesRegex(ValueError, "INVALID_PROBABILITY"):
            issue(self.root, self.spec(p=True), now=T0)
        with self.assertRaisesRegex(ValueError, "BASELINE_REQUIRES_PROVENANCE"):
            spec = self.spec()
            spec.pop("baseline_evidence")
            issue(self.root, spec, now=T0)
        with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
            spec = self.spec()
            spec["evidence"]["sha256"] = H
            issue(self.root, spec, now=T0)
        self.assertFalse((self.root / "experiments/superforecast_v1/issued/FCAST_001.json").exists())

    def test_corrupted_record_or_original_rejects_entire_score(self):
        issue(self.root, self.spec(), now=T0)
        resolve(self.root, self.outcome(), now=T1)
        (self.root / "input.txt").write_text("changed original")
        result = report(self.root, asof=T1, minimum=1)
        self.assertEqual(result["status"], "LEDGER_REJECTED")
        self.assertIsNone(result["brier_score"])

    def test_edited_probability_is_detected(self):
        issue(self.root, self.spec(), now=T0)
        path = self.root / "experiments/superforecast_v1/issued/FCAST_001.json"
        obj = json.loads(path.read_text())
        obj["probability"] = .99
        path.write_text(json.dumps(obj))
        self.assertEqual(report(self.root, asof=T1, minimum=1)["status"], "LEDGER_REJECTED")

    def test_missing_baseline_never_implies_outperformance(self):
        spec = self.spec(baseline=None)
        issue(self.root, spec, now=T0)
        resolve(self.root, self.outcome(), now=T1)
        scored = report(self.root, asof=T1, minimum=1)
        self.assertIsNotNone(scored["brier_score"])
        self.assertIsNone(scored["baseline_brier_score"])
        self.assertIsNone(scored["brier_skill_score"])

    def test_default_policy_requires_100_outcomes(self):
        issue(self.root, self.spec(), now=T0)
        resolve(self.root, self.outcome(), now=T1)
        res = report(self.root, asof=T1)
        self.assertEqual(res["status"], "UNCALIBRATED_INSUFFICIENT_OUTCOMES")
        self.assertIsNone(res["brier_score"])

    def test_orphan_outcome_is_rejected(self):
        folder = self.root / "experiments/superforecast_v1/resolved"
        folder.mkdir(parents=True)
        (folder / "FCAST_001.json").write_text("{}")
        self.assertEqual(report(self.root, asof=T1)["status"], "LEDGER_REJECTED")

    def test_preissue_time_is_not_user_supplied(self):
        spec = self.spec()
        spec["issued_at_utc"] = "2020-01-01T00:00:00+00:00"
        res = issue(self.root, spec, now=T0)
        self.assertEqual(res["issued_at_utc"], T0.isoformat())


if __name__ == "__main__":
    unittest.main()
