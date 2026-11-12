"""Focused synthetic checks: as-of isolation, sparse windows and no fake trade.""" 
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.recent_drawdown_guard import build, publish, markdown

VINTAGE = "2026-11-09T18:55:31+08:00"
DATES = ["2026-10-22","2026-10-27","2026-10-28","2026-10-29",
         "2026-10-30","2026-11-02","2026-11-03","2026-11-04",
         "2026-11-05","2026-11-06","2026-11-09"]

def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")

def fixture(root, closes, dates=None):
    dates=dates or DATES[-len(closes):]
    quality={"schema":"V8A5_QUALITY_DECISION_RESEARCH_SHADOW",
             "asof_price_date":"2026-11-09",
             "estimate_vintage":VINTAGE,"issuer_count":1,
             "formal_Aplus_added":0,
             "base_upside_order":[{"code":"2360","name":"致茂"}]}
    dump(root/"rankings/v8a5_quality_decision_lane.json",quality)
    for d,p in zip(dates,closes):
        dump(root/("prices/"+d+".json"),[
            dict(code="2360",market="TWSE",date=d,close=p,
                 close_at=d+"T13:30:00+08:00")])

def benchmark_month(root, month, dates, levels, captured="2026-11-09T07:30:00Z"):
    packet={"schema":"OFFICIAL_TAIEX_TR_SOURCE_V1","benchmark_id":"TAIEX_TR",
            "month":month,"captured_at":captured,
            "rows":[{"date":d,"level":p} for d,p in zip(dates,levels)]}
    raw=json.dumps(packet,sort_keys=True).encode("utf-8")
    location="benchmarks/TAIEX_TR/originals/"+month+"/original.json"
    path=root/location
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    dump(root/("benchmarks/TAIEX_TR/months/"+month+".json"),
         {"path":location,"sha256":hashlib.sha256(raw).hexdigest()})

class RecentDrawdownTests(unittest.TestCase):
    def test_sharp_five_observations_pause_without_automatic_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture(root,[100,99,98,95,90,80],DATES[-6:])
            dump(root/"prices/2026-11-10.json",[
                {"date":"2026-11-10","code":"2360","market":"TWSE","close":20}])
            doc=build(root)
            out=doc["outputs"][0]
            self.assertEqual(out["status"],"PAUSE_RECENT_SELL_OFF_REVIEW")
            self.assertTrue(out["risk_blocked"])
            self.assertEqual(out["return_5observations_pct"],-20)
            self.assertIsNone(out["return_10observations_pct"])
            self.assertEqual(out["current_unadjusted_close"],80)
            self.assertEqual(out["observed_max_drawdown_pct"],-20)
            self.assertEqual(doc["trade_signals_issued"],0)
            self.assertEqual(doc["formal_Aplus_added"],0)
            self.assertNotIn("2026-11-10",doc["source_sha256"]["price_snapshots"])
            published=publish(root)
            self.assertEqual(published["issuer_count"],1)
            self.assertTrue((root/"rankings/latest_recent_drawdown_shadow.md").exists())

    def test_intrawindow_trough_is_not_erased_by_rebound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture(root,[100,112,88,111,110],DATES[-5:])
            out=build(root)["outputs"][0]
            self.assertEqual(out["observed_max_drawdown_pct"],-21.43)
            self.assertEqual(out["peak_to_current_10observations_pct"],-1.79)
            self.assertEqual(out["status"],"PENDING_INCOMPLETE_OBSERVATION_WINDOW")
            self.assertFalse(out["risk_blocked"])
            self.assertFalse(out["complete_20_60_session_history_verified"])
            self.assertTrue(build(root)["observed_max_drawdown_is_not_full_session_or_intraday_drawdown"])

    def test_rebounded_deep_drawdown_gets_independent_watch_not_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture(root,[100,112,88,111,110,109],DATES[-6:])
            report=build(root)
            out=report["outputs"][0]
            self.assertEqual(out["observed_max_drawdown_pct"],-21.43)
            self.assertTrue(out["observed_deep_drawdown_watch"])
            self.assertEqual(out["status"],"WATCH_OBSERVED_DEEP_DRAWDOWN")
            self.assertFalse(out["risk_blocked"])
            self.assertEqual(report["formal_Aplus_added"],0)
            self.assertEqual(report["trade_signals_issued"],0)
            self.assertIn("深度回撤觀察",markdown(report))

    def test_insufficient_archive_is_pending_not_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture(root,[100,102],DATES[-2:])
            out=build(root)["outputs"][0]
            self.assertEqual(out["status"],"PENDING_INCOMPLETE_OBSERVATION_WINDOW")
            self.assertIsNone(out["return_5observations_pct"])
            self.assertEqual(out["observed_max_drawdown_pct"],0)
            self.assertIsNone(out["observed_deep_drawdown_watch"])
            self.assertFalse(out["complete_20_60_session_history_verified"])

    def test_relative_weakness_requires_dated_benchmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            prices=[100,99,98,97,96,95,94,93,92,91,90]
            fixture(root,prices)
            benchmark_month(root,"2026-10",DATES[:5],[100]*5)
            benchmark_month(root,"2026-11",DATES[5:],[100]*6)
            out=build(root)["outputs"][0]
            self.assertEqual(out["return_10observations_pct"],-10)
            self.assertEqual(out["relative_to_taiex_tr_pct"],-10)
            self.assertEqual(out["status"],"WATCH_MARKET_RELATIVE_WEAKNESS")
            self.assertFalse(out["risk_blocked"])
            benchmark_month(root,"2026-11",DATES[5:],[100]*6,
                            captured="2026-11-10T00:00:00Z")
            out=build(root)["outputs"][0]
            self.assertIsNone(out["relative_to_taiex_tr_pct"])
            self.assertEqual(out["status"],"NO_THRESHOLD_TRIGGER_IN_OBSERVED_SNAPSHOTS")

    def test_inconsistent_dates_or_duplicate_quote_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture(root,[100],DATES[-1:])
            path=root/"prices/2026-11-09.json"
            dup=json.loads(path.read_text())
            dup.append(dict(dup[0]))
            dump(path,dup)
            with self.assertRaisesRegex(ValueError,"DUPLICATE_QUOTE"):
                build(root)
            dup[0]["date"]="2026-11-06"
            dump(path,dup[:1])
            with self.assertRaisesRegex(ValueError,"QUOTE_DATE_CONFLICT"):
                build(root)

    def test_price_vintage_must_be_after_close_and_no_certified_pit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture(root,[100],DATES[-1:])
            path=root/"rankings/v8a5_quality_decision_lane.json"
            quality=json.loads(path.read_text())
            quality["estimate_vintage"]="2026-11-09T12:00:00+08:00"
            dump(path,quality)
            with self.assertRaisesRegex(ValueError,"QUOTE_NOT_YET_PUBLISHED"):
                build(root)
            quality["estimate_vintage"]=VINTAGE
            dump(path,quality)
            report=build(root)
            self.assertTrue(report["historical_capture_pit_not_verified"])
            self.assertTrue(report["unadjusted_prices_and_company_actions_unverified"])
            self.assertFalse(report["full_exchange_session_calendar_verified"])

if __name__ == "__main__":
    unittest.main()
