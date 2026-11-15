"""Fail-closed 6206 September-to-October revenue and stale-triage regressions."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import v888_6206_valuation as valuation
from scripts.v891_6206_gate_triage import pending_triage, render_md
from tw_model_v880.evidence import GATES


class OctoberRevenueReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "tw-market-data"
        self.data.mkdir()
        self._root = patch.object(valuation, "ROOT", self.root)
        self._data = patch.object(valuation, "DATA", self.data)
        self._root.start()
        self._data.start()
        self.addCleanup(self._root.stop)
        self.addCleanup(self._data.stop)

    def write(self, month, record):
        filename = f"tw-market-data/{month}/revenue_6.json"
        p = self.root / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps([record], ensure_ascii=False).encode()
        p.write_bytes(raw)
        (self.data / "latest_manifest.json").write_text(json.dumps({
            "period": month,
            "capture_utc": "2026-11-13T17:47:01+00:00",
            "shards": [{"path": filename, "sha256": hashlib.sha256(raw).hexdigest()}],
            "original_receipts": [{"url": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"}],
        }), encoding="utf-8")
        return p

    def test_october_ytd_minus_month_is_nine_month_baseline(self):
        self.write("2026-10", dict(code="6206", market="TWSE", report_month="11510",
            ytd_revenue_k="5639538", monthly_revenue_k="503860",
            prior_month_revenue_k="592080",
            last_year_ytd_revenue_k="4287070", last_year_month_revenue_k="338535"))
        res = valuation.official_revenue()
        self.assertAlmostEqual(res["revenue_9m_ntd_m"], 5135.678, places=3)
        self.assertAlmostEqual(res["september_2026_ntd_m"], 592.080, places=3)
        self.assertAlmostEqual(res["latest_reported_ytd_m"], 5639.538, places=3)
        self.assertAlmostEqual(res["ytd_yoy_pct"], (5135678/3948535-1)*100, places=6)
        self.assertTrue(res["provenance"]["latest_10m_minus_october_bridge"])
        self.assertNotIn("formal_Aplus", res)

    def test_september_snapshot_unchanged(self):
        self.write("2026-09", dict(code="6206", market="TWSE", report_month="11509",
            ytd_revenue_k="5135677", monthly_revenue_k="592080",
            prior_month_revenue_k="583281", last_year_ytd_revenue_k="3948535",
            last_year_month_revenue_k="455570", ytd_yoy_pct="30.065378678421236"))
        res = valuation.official_revenue()
        self.assertAlmostEqual(res["revenue_9m_ntd_m"], 5135.677, places=3)
        self.assertAlmostEqual(res["september_2026_ntd_m"], 592.080, places=3)
        self.assertFalse(res["provenance"]["latest_10m_minus_october_bridge"])

    def test_future_month_not_assumed_accurate(self):
        self.write("2026-11", dict(code="6206", market="TWSE", report_month="11511"))
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_MONTH"):
            valuation.official_revenue()

    def test_source_hash_changed_is_refused(self):
        file = self.write("2026-10", dict(code="6206", market="TWSE", report_month="11510",
            ytd_revenue_k="5639538", monthly_revenue_k="503860",
            prior_month_revenue_k="592080",
            last_year_ytd_revenue_k="4287070", last_year_month_revenue_k="338535"))
        file.write_bytes(file.read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError, "SHA_MISMATCH"):
            valuation.official_revenue()

    def test_wrong_report_period_is_rejected(self):
        self.write("2026-10", dict(code="6206", market="TWSE", report_month="11509",
            ytd_revenue_k="5639538", monthly_revenue_k="503860",
            prior_month_revenue_k="592080",
            last_year_ytd_revenue_k="4287070", last_year_month_revenue_k="338535"))
        with self.assertRaisesRegex(ValueError, "WRONG_MOPS_REPORT_MONTH"):
            valuation.official_revenue()


class Pending6206TriageTests(unittest.TestCase):
    def test_pending_preserves_all_thirteen_gates_and_current_vintage(self):
        progress=dict(estimate_vintage="2026-11-14T22:41:27+08:00",
                      asof_price_date="2026-11-13")
        value=dict(status="6206_EVIDENCE_OR_VINTAGE_PENDING",
                   error="ValueError:REVENUE_6206_UNSUPPORTED_MONTH_REQUIRES_DATED_BRIDGE",
                   original_common_model={"model_vintage": "2026-11-10T00:00:00+08:00"})
        result=pending_triage(progress,value,value["error"])
        self.assertEqual(result["estimate_vintage"],progress["estimate_vintage"])
        self.assertEqual(result["price_date"],progress["asof_price_date"])
        self.assertEqual(result["status"],"INDEPENDENT_6206_VALUATION_PENDING")
        self.assertEqual([g["gate"] for g in result["gates"]],list(GATES))
        self.assertTrue(all(g["formal_status"]=="PENDING" for g in result["gates"]))
        self.assertTrue(all(g["automatically_certified"] is False for g in result["gates"]))
        self.assertFalse(result["formal_Aplus"])
        self.assertEqual(result["newly_certified_gates"],0)
        self.assertIn("PENDING",render_md(result))


if __name__ == "__main__":
    unittest.main()
