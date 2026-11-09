"""Regression of marketwide reference-session coverage and strict as-of bounds."""
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts.marketwide_drawdown_coverage import build, publish

ASOF = "2026-11-09"
VINTAGE = "2026-11-09T23:19:31+08:00"

def put(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")

def days(n=61):
    d=dt.date.fromisoformat(ASOF)
    out=[]
    while len(out)<n:
        if d.weekday()<5:
            out.append(d.isoformat())
        d-=dt.timedelta(days=1)
    return list(reversed(out))

def setup(root, with_history=True):
    calendar=days()
    put(root/"rankings/v8a5_quality_decision_lane.json",
        dict(schema="V8A5_QUALITY_DECISION_RESEARCH_SHADOW",
             asof_price_date=ASOF,estimate_vintage=VINTAGE,
             formal_Aplus_added=0,base_upside_order=[
                 dict(code="2317",name="鴻海",base_upside_pct=100)]))
    # The price snapshot is authoritative for current membership.
    for day in calendar[-2:]:
        put(root/("prices/"+day+".json"),[
            dict(date=day,market="TWSE",code="2317",close=100.0),
            dict(date=day,market="TPEX",code="9802",close=50.0)])
    if with_history:
        put(root/"prices/issuer_history/TWSE/2317.json",
            dict(issuer="2317",market="TWSE",
                 price_reference_asof="2026-11-09",
                 sessions=[dict(date=d,close=100.0,code="2317",market="TWSE")
                           for d in reversed(calendar)]))
    bymonth={}
    for d in calendar:
        bymonth.setdefault(d[:7],[]).append(d)
    for month, dates in bymonth.items():
        packet=dict(benchmark_id="TAIEX_TR",month=month,
            captured_at="2026-11-09T13:40:00+08:00",
            rows=[dict(date=d,level=1000) for d in dates])
        raw=json.dumps(packet,sort_keys=True).encode()
        relative="benchmarks/TAIEX_TR/originals/"+month+"/packet.json"
        path=root/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
        put(root/("benchmarks/TAIEX_TR/months/"+month+".json"),
            dict(path=relative,sha256=hashlib.sha256(raw).hexdigest()))
    return calendar

class MarketwideTests(unittest.TestCase):
    def test_exact_20_60_coverage_and_full_market_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            calendar=setup(root)
            doc=build(root)
            self.assertEqual(doc["marketwide_current_quotes"],2)
            self.assertEqual(doc["coverage_counts"],{"5":1,"10":1,"20":1,"60":1})
            rows={(r["market"],r["code"]):r for r in doc["issuers"]}
            main=rows[("TWSE","2317")]
            self.assertTrue(main["session_coverage"]["60"])
            self.assertEqual(main["windows"]["20"]["reference_sessions"],21)
            self.assertFalse(main["current_company_actions_verified"])
            self.assertFalse(doc["historical_issuer_capture_point_in_time_verified"])
            other=rows[("TPEX","9802")]
            self.assertEqual(other["status"],"PENDING_PRICE_HISTORY_OR_COMPANY_ACTIONS")
            self.assertFalse(other["session_coverage"]["20"])
            self.assertEqual(doc["formal_Aplus_added"],0)
            self.assertEqual(doc["trade_signals_created"],0)
            pub=publish(root)
            self.assertEqual(pub["marketwide_current_quotes"],2)
            self.assertTrue((root/"rankings/latest_marketwide_drawdown_coverage.md").exists())

    def test_null_close_kept_in_full_universe_as_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            setup(root)
            path=root/"prices/2026-11-09.json"
            rows=json.loads(path.read_text())
            rows.append(dict(date=ASOF,market="TPEX",code="2724",close=None))
            put(path,rows)
            doc=build(root)
            self.assertEqual(doc["marketwide_snapshot_rows"],3)
            self.assertEqual(doc["marketwide_current_quotes"],2)
            self.assertEqual(doc["snapshot_rows_accounted_for"],3)
            self.assertEqual(doc["missing_or_invalid_current_close_count"],1)
            null=next(x for x in doc["issuers"] if x["code"]=="2724")
            self.assertEqual(null["status"],"PENDING_MISSING_CURRENT_CLOSE")
            self.assertFalse(null["provisional_pause"])
            self.assertFalse(null["session_coverage"]["20"])

    def test_no_history_is_not_inferred_safe_from_sparse_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            setup(root,with_history=False)
            doc=build(root)
            self.assertEqual(doc["coverage_counts"]["20"],0)
            self.assertEqual(doc["coverage_counts"]["60"],0)
            self.assertTrue(all(r["status"].startswith("PENDING") for r in doc["issuers"]))

    def test_conflicting_history_packet_does_not_synthesize_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            calendar=setup(root)
            path=root/"prices/issuer_history/TWSE/2317.json"
            obj=json.loads(path.read_text())
            obj["sessions"][0]["close"]=120 # snapshot has 100 for this date
            put(path,obj)
            row=next(r for r in build(root)["issuers"] if r["code"]=="2317")
            self.assertEqual(row["status"],"PENDING_CONFLICTING_HISTORY_VERSUS_DAILY")
            self.assertFalse(row["session_coverage"]["60"])
            self.assertTrue(row["price_conflict"])

    def test_future_reference_history_rejected_and_future_snapshots_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            setup(root)
            hist=root/"prices/issuer_history/TWSE/2317.json"
            obj=json.loads(hist.read_text())
            obj["price_reference_asof"]="2026-11-10"
            put(hist,obj)
            put(root/"prices/2026-11-10.json",
                [dict(date="2026-11-10",code="2317",market="TWSE",close=1)])
            doc=build(root)
            row=next(r for r in doc["issuers"] if r["code"]=="2317")
            self.assertEqual(row["status"],"PENDING_INVALID_HISTORY_PACKET")
            self.assertEqual(row["latest_close"],100.0)
            self.assertFalse(row["session_coverage"]["60"])
            self.assertNotIn("2026-11-10",doc["source_sha256"]["dated_prices"])

    def test_benchmark_captured_after_asof_vintage_cannot_fill_60days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            calendar=setup(root)
            month=calendar[-1][:7]
            manifest=root/("benchmarks/TAIEX_TR/months/"+month+".json")
            rel=json.loads(manifest.read_text())["path"]
            src=root/rel
            packet=json.loads(src.read_text())
            packet["captured_at"]="2026-11-10T09:00:00+08:00"
            raw=json.dumps(packet,sort_keys=True).encode()
            src.write_bytes(raw)
            put(manifest,dict(path=rel,sha256=hashlib.sha256(raw).hexdigest()))
            doc=build(root)
            self.assertEqual(doc["coverage_counts"]["20"],0)
            self.assertEqual(doc["coverage_counts"]["60"],0)
            self.assertTrue(all(r["status"]=="PENDING_VERIFIED_BENCHMARK_ASOF"
                                for r in doc["issuers"]))

    def test_sharp_decline_is_research_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            calendar=setup(root)
            hist=root/"prices/issuer_history/TWSE/2317.json"
            obj=json.loads(hist.read_text())
            for row in obj["sessions"]:
                if row["date"] < calendar[-6]:
                    row["close"]=160
            put(hist,obj)
            # Do not allow conflicting 100 snapshot to imply missing historical PIT.
            out=build(root)
            main=next(r for r in out["issuers"] if r["code"]=="2317")
            self.assertEqual(main["status"],"PAUSE_SHARP_DRAWDOWN_RESEARCH")
            self.assertTrue(main["provisional_pause"])
            self.assertEqual(out["trade_signals_created"],0)
            self.assertEqual(out["formal_Aplus_added"],0)

if __name__=="__main__":
    unittest.main()
