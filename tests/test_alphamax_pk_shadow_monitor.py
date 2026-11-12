"""Synthetic-only shadow monitoring tests; outputs cannot authorize actual investing."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from alphamax.pk_shadow_monitor import (
    PKContractError, git_blob_sha, shadow_price_only,
)

FREEZE = Path(__file__).resolve().parents[1] / "alphamax/research/2026-11-11-v8-alphamax-pk-frozen.json"


class ShadowPKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = json.loads(FREEZE.read_text(encoding="utf-8"))

    def rows(self, dt="2026-11-12", multiplier=1.0):
        out = []
        for lane in ("alpha_lane", "v8_lane"):
            for row in self.frozen[lane]["rows"]:
                value = row["reference_close"]
                out.append({
                    "market": row["market"], "code": row["code"], "date": dt,
                    "open": value, "close": value * multiplier,
                    "fillability_verified": False,
                })
        out.append({"market": "TWSE", "code": "0050", "date": dt,
                    "open": 100, "close": 100 * multiplier,
                    "fillability_verified": False})
        return out

    @staticmethod
    def raw(rows):
        return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()

    def run_shadow(self, entries=None, latest=None, latest_date="2026-11-12", manifest=None):
        entry_data = self.raw(self.rows() if entries is None else entries)
        latest_data = self.raw(self.rows(dt=latest_date, multiplier=1.1) if latest is None else latest)
        m = manifest or {"date": latest_date, "unadjusted_quotes": True,
                         "path": "tw-market-data/prices/" + latest_date + ".json"}
        return shadow_price_only(self.frozen, entry_data, latest_data, m,
                                 expected_entry_blob_sha=git_blob_sha(entry_data))

    def test_same_day_paper_open_close_is_raw_only(self):
        r = self.run_shadow()
        self.assertEqual(r["lanes"]["alpha_lane"]["complete_quote_count"], 10)
        self.assertEqual(r["lanes"]["v8_lane"]["complete_quote_count"], 10)
        self.assertAlmostEqual(r["lanes"]["alpha_lane"]["equal_initial_capital_unadjusted_price_change_pct"], 10)
        self.assertAlmostEqual(r["benchmark_0050"]["raw_price_only_change_pct"], 10)
        self.assertIsNone(r["official_winner"])
        self.assertIsNone(r["verified_after_cost_total_returns"])
        self.assertFalse(r["dividend_corporate_action_adjusted"])
        self.assertFalse(r["is_model_vs_model"])

    def test_fixed_entry_sha_rejects_revised_reference(self):
        data = self.raw(self.rows())
        changed = data + b" "
        with self.assertRaisesRegex(PKContractError, "SHADOW_ENTRY_BLOB_TAMPERED"):
            shadow_price_only(self.frozen, changed, data,
                              {"date": "2026-11-12", "path": "tw-market-data/prices/2026-11-12.json",
                               "unadjusted_quotes": True},
                              expected_entry_blob_sha=git_blob_sha(data))

    def test_missing_initial_quote_fails_closed(self):
        entries = self.rows()[1:]
        with self.assertRaisesRegex(PKContractError, "FROZEN_ENTRY_QUOTE_COVERAGE_INCOMPLETE"):
            self.run_shadow(entries=entries)

    def test_missing_latest_quote_blocks_full_basket(self):
        latest = self.rows(multiplier=1.1)[1:]
        r = self.run_shadow(latest=latest)
        self.assertEqual(r["lanes"]["alpha_lane"]["complete_quote_count"], 9)
        self.assertIsNone(r["lanes"]["alpha_lane"]["equal_initial_capital_unadjusted_price_change_pct"])
        self.assertIsNone(r["lanes"]["alpha_lane"]["unadjusted_excess_vs_0050_pct_points"])
        self.assertIsNone(r["official_winner"])

    def test_missing_latest_benchmark_blocks_excess_only(self):
        latest = self.rows(multiplier=1.1)[:-1]
        r = self.run_shadow(latest=latest)
        self.assertEqual(r["lanes"]["alpha_lane"]["complete_quote_count"], 10)
        self.assertIsNone(r["benchmark_0050"]["raw_price_only_change_pct"])
        self.assertIsNone(r["lanes"]["alpha_lane"]["unadjusted_excess_vs_0050_pct_points"])

    def test_mixed_date_or_duplicate_in_latest_rejected(self):
        d = self.rows()
        d[0]["date"] = "2026-11-11"
        with self.assertRaisesRegex(PKContractError, "MIXED_SNAPSHOT_DATES"):
            self.run_shadow(latest=d)
        d = self.rows()
        d.append(copy.deepcopy(d[0]))
        with self.assertRaisesRegex(PKContractError, "DUPLICATE_MARKET_CODE"):
            self.run_shadow(latest=d)

    def test_fake_broker_fill_does_not_promote_shadows(self):
        a = self.rows()
        b = self.rows(multiplier=1.1)
        for x in a + b:
            x["fillability_verified"] = True
        result = self.run_shadow(entries=a, latest=b)
        self.assertIsNone(result["official_winner"])
        self.assertFalse(result["dividend_corporate_action_adjusted"])
        self.assertFalse(result["is_model_vs_model"])

    def test_price_not_finite_does_not_create_a_return(self):
        latest = self.rows(multiplier=1.10)
        latest[0]["close"] = None
        r = self.run_shadow(latest=latest)
        self.assertIsNone(r["lanes"]["alpha_lane"]["equal_initial_capital_unadjusted_price_change_pct"])

    def test_entry_without_open_rejected(self):
        entry = self.rows()
        entry[0]["open"] = None
        with self.assertRaisesRegex(PKContractError, "FROZEN_ENTRY_QUOTE_COVERAGE_INCOMPLETE"):
            self.run_shadow(entries=entry)

    def test_future_date_and_unknown_adjustment_type_rejected(self):
        with self.assertRaisesRegex(PKContractError, "LATEST_BEFORE_FROZEN_ENTRY_DATE"):
            self.run_shadow(latest_date="2026-11-11")
        bad = {"date": "2026-11-12", "path": "tw-market-data/prices/2026-11-12.json",
               "unadjusted_quotes": False}
        with self.assertRaisesRegex(PKContractError, "LATEST_SNAPSHOT_ADJUSTMENT_STATUS_UNKNOWN"):
            self.run_shadow(manifest=bad)

    def test_latest_manifest_untrusted_path_rejected(self):
        bad = {"date": "2026-11-12", "path": "tw-market-data/prices/../secret.json",
               "unadjusted_quotes": True}
        with self.assertRaisesRegex(PKContractError, "LATEST_PRICE_MANIFEST_PATH_INVALID"):
            self.run_shadow(manifest=bad)


if __name__ == "__main__":
    unittest.main()
