"""Synthetic-only behavioral tests; never interpreted as historical Taiwan returns."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts import buyback_event_backtest as bb


def rows(start=date(2024, 1, 1), end=date(2026, 4, 30)):
    prices, benchmark = {}, {}
    day = start
    i = 0
    while day <= end:
        if day.weekday() < 5:
            # issuer +20% by 1 year, benchmark +10%, purely synthetic
            prices[day] = (100 + 20 * i / 260, True)
            benchmark[day] = (100 + 10 * i / 260, True)
            i += 1
        day += timedelta(days=1)
    return {"1234": prices}, benchmark


def event(date_="2024-01-08T16:00:00+08:00", kind="announce", rate=""):
    return {"event_id": "e1", "stock_id": "1234", "event_type": kind,
            "disclosed_at": date_, "source_url": "https://mops.twse.com.tw/",
            "source_sha256": "a" * 64, "execution_rate": rate}


class BuybackStudyTests(unittest.TestCase):
    def test_defensive_next_session_and_costs(self):
        prices, bench = rows()
        events = bb.load_events([event()])
        report = bb.study(events, prices, bench, date(2026, 4, 30))
        self.assertEqual(report["status"], "RESEARCH_OBSERVATIONS_UNCERTIFIED")
        self.assertEqual(report["observed_count"], 3)
        o = next(x for x in report["observations"] if x["horizon_months"] == 12)
        self.assertEqual(o["entry_date"], "2024-01-09")
        self.assertGreater(o["alpha_0050"], 0)
        self.assertGreater(o["return_0050"], 0)
        self.assertLess(o["net_return"], prices["1234"][date.fromisoformat(o["exit_date"])][0] /
                        prices["1234"][date.fromisoformat(o["entry_date"])][0] - 1)
        self.assertEqual(report["grouping"]["announce_OOS_2024_2025_12m"]["beat_0050_pct"], 100)

    def test_no_lookahead_completion_execution_rate(self):
        with self.assertRaisesRegex(ValueError, "FUTURE_EXECUTION_RATE"):
            bb.load_events([event(kind="announce", rate="0.95")])
        with self.assertRaisesRegex(ValueError, "COMPLETION_EXECUTION_RATE"):
            bb.load_events([event(kind="completion", rate="")])
        result = bb.load_events([event(kind="completion", rate="0.95")])
        self.assertEqual(result[0]["event_type"], "completion")
        self.assertNotIn("execution_rate", result[0])

    def test_naive_disclosure_time_rejected(self):
        with self.assertRaisesRegex(ValueError, "TIMEZONE_AWARE"):
            bb.load_events([event(date_="2024-01-08T16:00:00")])

    def test_nonmatured_12m_not_counted_as_loser(self):
        prices, bench = rows()
        events = bb.load_events([event(date_="2025-06-16T16:00:00+08:00")])
        report = bb.study(events, prices, bench, date(2025, 12, 31))
        self.assertEqual(report["immature_count"], 1)
        self.assertEqual(report["grouping"]["announce_OOS_2024_2025_12m"]["n"], 0)
        self.assertEqual(report["grouping"]["announce_OOS_2024_2025_12m"]["win_rate_pct"], None)

    def test_missing_stock_not_a_zero_return(self):
        prices, bench = rows()
        report = bb.study(bb.load_events([event()]), {}, bench, date(2026, 4, 30))
        self.assertEqual(report["observed_count"], 0)
        self.assertEqual(report["blocked_count"], 3)
        self.assertEqual(report["grouping"]["announce_OOS_2024_2025_3m"]["n"], 0)

    def test_unverified_total_return_blocks_results(self):
        prices, bench = rows()
        prices["1234"][date(2024, 1, 9)] = (100, False)
        report = bb.study(bb.load_events([event()]), prices, bench, date(2026, 4, 30))
        self.assertEqual(report["observed_count"], 0)
        self.assertTrue(all(x["reason"] == "UNVERIFIED_TOTAL_RETURN_OR_ACTIONS"
                            for x in report["blocked"]))

    def test_inconsistent_source_rows_rejected(self):
        p = [{"date": "2024-01-09", "stock_id": "1234",
              "total_return_close": "100", "corporate_actions_verified": "true",
              "source_id": "sourceX"}]
        with self.assertRaisesRegex(ValueError, "DUPLICATED_ISSUER"):
            bb.load_prices(p + p)
        with self.assertRaisesRegex(ValueError, "BAD_OR_DUPLICATE"):
            bb.load_events([event(), event()])

    def test_missing_source_cli_produces_no_fake_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "status.json"
            rc = bb.main(["--events", str(Path(tmp) / "missing.csv"),
                          "--prices", str(Path(tmp) / "missing_price.csv"),
                          "--benchmark", str(Path(tmp) / "missing_0050.csv"),
                          "--out", str(out)])
            self.assertEqual(rc, 2)
            data = json.loads(out.read_text())
            self.assertEqual(data["status"], "BLOCKED_MISSING_SOURCE_FILES")
            self.assertIsNone(data["win_rate_pct"])
            self.assertFalse(data["orders_created"])


if __name__ == "__main__":
    unittest.main()
