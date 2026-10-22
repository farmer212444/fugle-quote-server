"""Regression: forward shadow experiment must not backdate, mutate or invent returns."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import v8a8_forward_top30_0050 as challenge

ACTIVATE = "2026-10-23T00:00:00+08:00"


class ForwardTop30CompetitionTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name) / "tw-market-data"
        (self.root / "config").mkdir(parents=True)
        self.policy = {
            "schema": "V8A8_PREDECLARED_RESEARCH_SHADOW_COMPETITION_V1",
            "activation_at": ACTIVATE, "selected_count": 30,
            "weighting": "equal_weight",
            "selection_source": "top30_quality_priority",
            "formation": "first_verified_archive_per_local_calendar_month",
            "benchmark": ["0050_total_return", "TAIEX_total_return"],
            "monthly_rebalance_only": True,
            "capital_ntd": 10000000,
        }
        self.write(self.root / "config/forward_top30_0050_v1.json", self.policy)
        self.patch = patch.object(challenge, "verify_frozen_receipt", side_effect=lambda path: challenge.read(path))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def add_archive(self, ident, archived, *, rank_first="1000",
                    variant="current-information", day="2026-10-23"):
        folder = self.root / "pit_vintages" / day / ident
        receipt = {
            "estimate_vintage": archived,
            "archived_at_utc": archived,
            "strategy_variant": variant,
            "model_code_sha256": "a" * 64,
            "strategy_variant_sha256": "b" * 64,
        }
        self.write(folder / "receipt.json", receipt)
        selected = [{"code": f"{int(rank_first)+i:04d}", "name": f"Stock {i}",
                     "market": "TWSE", "source_tier": "ORIGINAL_CURRENT_ISSUER_NUMERICS",
                     "reference_close": 100, "base": {"eps": 2, "target_price": 150,
                     "price_upside_pct": 50}} for i in range(30)]
        self.write(folder / "latest_research.json", {
            "estimate_vintage": archived, "model": "V8.10.2",
            "asof_price_date": "2026-10-22", "formal_Aplus_count": 0,
            "top30_quality_priority": selected,
        })
        return folder

    def test_no_pre_activation_or_retroactive_score(self):
        self.add_archive("old", "2026-10-22T10:00:00+08:00", day="2026-10-22")
        before = challenge.run(self.root, dt.datetime.fromisoformat("2026-10-22T16:00:00+08:00"))
        self.assertEqual(before["status"], "WAITING_FOR_POLICY_ACTIVATION")
        self.assertIsNone(before["selection_path"])
        later = challenge.run(self.root, dt.datetime.fromisoformat("2026-10-23T12:00:00+08:00"))
        self.assertIsNone(later["selection_path"])
        self.assertIsNone(later["model_net_total_return_pct"])

    def test_first_eligible_signal_locks_30_and_no_false_win(self):
        self.add_archive("later", "2026-10-23T12:00:00+08:00", rank_first="3000")
        self.add_archive("earlier", "2026-10-23T09:00:00+08:00", rank_first="1000")
        self.add_archive("shadow", "2026-10-23T08:00:00+08:00",
                         rank_first="2000", variant="without-earnings-events")
        now = dt.datetime.fromisoformat("2026-10-23T16:00:00+08:00")
        report = challenge.run(self.root, now)
        self.assertEqual(report["research_top30_count"], 30)
        self.assertTrue(report["formal_Aplus_strategy_currently_in_cash"])
        self.assertIsNone(report["is_winner_vs_0050"])
        self.assertIsNone(report["model_alpha_vs_0050_pct_points"])
        lock_path = self.root / report["selection_path"]
        locked = challenge.read(lock_path)
        self.assertEqual(locked["research_top30"][0]["code"], "1000")
        self.assertEqual(locked["next_eligible_open_only_after"], now.astimezone(dt.timezone.utc).isoformat())
        self.assertTrue(all(s["research_only_not_formal_Aplus"] for s in locked["research_top30"]))
        second = challenge.run(self.root, dt.datetime.fromisoformat("2026-10-23T20:00:00+08:00"))
        self.assertEqual(second["selection_sha256"], report["selection_sha256"])
        self.assertEqual(challenge.read(lock_path), locked)

    def test_tampering_or_policy_change_is_rejected(self):
        self.add_archive("once", "2026-10-23T11:00:00+08:00")
        now = dt.datetime.fromisoformat("2026-10-23T15:00:00+08:00")
        report = challenge.run(self.root, now)
        path = self.root / report["selection_path"]
        bad = challenge.read(path)
        bad["research_top30"][0]["code"] = "9999"
        self.write(path, bad)
        with self.assertRaisesRegex(ValueError, "TAMPERED"):
            challenge.run(self.root, now)
        self.write(path, {**bad, "selection_sha256": challenge.digest({k: v for k, v in bad.items() if k != "selection_sha256"})})
        self.policy["capital_ntd"] = 20000000
        self.write(self.root / "config/forward_top30_0050_v1.json", self.policy)
        with self.assertRaisesRegex(ValueError, "POLICY_MUTATED"):
            challenge.run(self.root, now)

    def test_next_month_creates_new_snapshot_not_backfilled(self):
        self.add_archive("one", "2026-10-23T11:00:00+08:00")
        challenge.run(self.root, dt.datetime.fromisoformat("2026-10-23T15:00:00+08:00"))
        self.add_archive("nov", "2026-11-02T11:00:00+08:00", day="2026-11-02", rank_first="4000")
        report = challenge.run(self.root, dt.datetime.fromisoformat("2026-11-02T15:00:00+08:00"))
        self.assertIn("2026-11.json", report["selection_path"])
        self.assertTrue((self.root / "experiments/forward_top30_0050_v1/monthly/2026-10.json").exists())


if __name__ == "__main__":
    unittest.main()
