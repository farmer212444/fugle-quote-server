import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v8a6_etf_rotation_watch import (
    SOURCE_LEVEL, annotate_stock, build_report, chip_weakness,
    financial_downtrend, markdown, validate_ledger
)

LEDGER = Path(__file__).resolve().parents[1]/"tw-market-data/evidence/v880/etf_index_constituent_events.json"
ASOF = "2026-10-21T12:53:00+08:00"


def data():
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def fin():
    return {"code":"9802","period":"2026-Q3","disclosed_at":"2026-10-20",
            "q3_2026":{"revenue":5435935,"gross_profit":719347,"eps":0.68},
            "q3_2025":{"revenue":3819386,"gross_profit":670486,"eps":1.50},
            "source_url":"https://www.fulgentsun.com/img/News_Release/FY2026%203Q%20financial%20results%20CN.pdf"}


def chip():
    return {"asof_price_date":"2026-10-20",
            "stocks":[{"code":"9802","tdcc_weekly_change_pp":-0.7,
                       "institutional_retreat_20d":{"status":"OBSERVED_RETREAT_REQUIRES_FUNDAMENTAL_REVIEW",
                                                   "observation_end":"2026-10-20"}}]}


def model(asof=ASOF):
    return {"model":"V8.8.2","estimate_vintage":asof,"asof_price_date":"2026-10-20",
            "formal_Aplus_count":0,
            "top30_provisional":[{"code":"1714"},{"code":"6741"}]}


class ETFConstituentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_four_primary_original_notices_three_deletions_one_readdition(self):
        events=validate_ledger(data(),self.root,dt.datetime.fromisoformat(ASOF))
        self.assertEqual(len(events),4)
        self.assertEqual([(e["etf_code"],e["direction"]) for e in events],
                         [("00905","DELETE"),("00733","DELETE"),("00905","ADD"),
                          ("00905","DELETE")])
        self.assertTrue(all(not e["official_original_notice_bytes_checked_asof"] for e in events))
        result=build_report(data(),model(),chip(),fin(),self.root)
        company=result["stocks"]["9802"]
        self.assertEqual(company["deletes"],3)
        self.assertEqual(company["adds"],1)
        self.assertEqual(company["last_event"]["effective_date"],"2025-07-17")
        self.assertEqual(company["live_archived_deletions_120d"],0)
        self.assertFalse(company["three_way_convergence_observed"])
        self.assertEqual(company["earnings"]["status"],"PUBLISHED_SELF_REPORTED_FINANCIAL_SHADOW")
        self.assertTrue(company["earnings"]["declining"])
        self.assertEqual(result["formal_Aplus_created"],0)
        self.assertFalse(result["performance_or_win_rate_backtest_completed"])
        self.assertTrue(result["historical_source_coverage_complete"] is False)
        self.assertIn("00733",markdown(result))

    def test_absence_of_6206_events_does_not_mean_it_is_not_held(self):
        r=build_report(data(),model(),None,None,self.root)
        company=r["stocks"]["6206"]
        self.assertEqual(company["event_history_count"],0)
        self.assertEqual(company["research_review_status"],
                         "NO_EVENTS_IN_PARTIAL_COVERAGE_NOT_PROOF_OF_HOLDINGS")
        self.assertEqual(company["formal_13_gate_passes_added"],0)

    def test_retrospective_event_cannot_be_used_in_2025_pit_backtest(self):
        m=model("2025-07-17T09:00:00+08:00")
        m["asof_price_date"]="2025-07-16"
        with self.assertRaisesRegex(ValueError,"RETROSPECTIVE_EVENT_LEDGER_NOT_YET_CREATED"):
            build_report(data(),m,None,None,self.root)

    def test_future_and_fake_events_are_not_accepted(self):
        d=data()
        original=d["events"][0]
        d["events"].append(copy.deepcopy(original))
        with self.assertRaisesRegex(ValueError,"ETF_DUPLICATE"):
            validate_ledger(d,self.root,dt.datetime.fromisoformat(ASOF))
        d=data()
        d["events"][0]["primary_technical_notice_pdf"]="https://bad.example/notice"
        with self.assertRaisesRegex(ValueError,"ETF_SOURCE_NOT_EXACT_OFFICIAL_URL_pdf"):
            validate_ledger(d,self.root,dt.datetime.fromisoformat(ASOF))
        d=data()
        d["events"][0]["published_at"]="2024-10-22T09:00:00+08:00"
        with self.assertRaisesRegex(ValueError,"PUBLISHED_EFFECTIVE"):
            validate_ledger(d,self.root,dt.datetime.fromisoformat(ASOF))

    def test_missing_unarchived_recent_source_must_never_trigger_risk(self):
        d=data()
        e=copy.deepcopy(d["events"][0])
        e.update(id="TIP-00123-9802-20261021-DELETE",etf_code="00123",
                 effective_date="2026-10-21",published_at="2026-10-20T17:00:00+08:00",
                 notice_reference_date="2026-09-30",
                 first_system_observed_at=None)
        d["events"].append(e)
        out=build_report(d,model(),chip(),fin(),self.root)
        company=out["stocks"]["9802"]
        self.assertEqual(company["live_archived_deletions_120d"],0)
        self.assertFalse(company["three_way_convergence_observed"])

    def test_only_sha_verified_new_notice_can_trigger_three_factor_review(self):
        d=data()
        e=copy.deepcopy(d["events"][0])
        archive=self.root/"evidence/v880/etf_notices/future.pdf"
        archive.parent.mkdir(parents=True)
        raw=b"%PDF-1.7\n"+b"official event bytes!"*60+b"\n%%EOF\n"
        archive.write_bytes(raw)
        e.update(id="TIP-00123-9802-20261021-DELETE",etf_code="00123",
                 effective_date="2026-10-21",published_at="2026-10-20T17:00:00+08:00",
                 notice_reference_date="2026-09-30",
                 first_system_observed_at="2026-10-20T20:00:00+08:00",
                 archive_path="evidence/v880/etf_notices/future.pdf",
                 original_pdf_sha256=hashlib.sha256(raw).hexdigest())
        d["events"].append(e)
        m=model("2026-10-22T10:40:00+08:00")
        m["asof_price_date"]="2026-10-21"
        chips=chip()
        chips["asof_price_date"]="2026-10-21"
        chips["stocks"][0]["institutional_retreat_20d"]["observation_end"]="2026-10-21"
        out=build_report(d,m,chips,fin(),self.root)
        observed=out["stocks"]["9802"]
        self.assertEqual(observed["live_archived_deletions_120d"],1)
        self.assertEqual(observed["research_review_status"],
                         "THREE_WAY_ETF_CHIP_EARNINGS_REVIEW_ONLY")
        self.assertTrue(observed["three_way_convergence_observed"])
        self.assertEqual(observed["formal_13_gate_passes_added"],0)
        self.assertEqual(observed["formal_Aplus_added"],0)
        self.assertFalse(observed["automated_trade_or_exit"])
        # Confirm tampering cannot be disguised as a mere history omission.
        archive.write_bytes(b"%PDF-1.7\n"+b"tampered!"*70+b"\n%%EOF\n")
        with self.assertRaisesRegex(ValueError,"HASH_MISMATCH"):
            build_report(d,m,chips,fin(),self.root)

    def test_no_same_day_earnings_lookahead(self):
        same=dt.datetime.fromisoformat("2026-10-20T20:00:00+08:00")
        ret=financial_downtrend(fin(),same)
        self.assertFalse(ret["declining"])
        self.assertEqual(ret["status"],"UNAVAILABLE_OR_NOT_PIT_SAFE")
        later=financial_downtrend(fin(),dt.datetime.fromisoformat(ASOF))
        self.assertTrue(later["declining"])

    def test_invalid_chip_day_or_missing_inst_flow_is_not_a_confirmed_retreat(self):
        v=chip_weakness(chip(),"9802","2026-10-19")
        self.assertEqual(v["status"],"CHIP_HISTORY_INCOMPLETE")
        c=chip()
        c["stocks"][0]["tdcc_weekly_change_pp"]=None
        v=chip_weakness(c,"9802","2026-10-20")
        self.assertFalse(v["weakness_confirmed"] is False)  # 20d retreat is observed
        c["stocks"][0]["institutional_retreat_20d"]["observation_end"]="2026-10-21"
        v=chip_weakness(c,"9802","2026-10-20")
        self.assertFalse(v["weakness_confirmed"])


if __name__=="__main__":
    unittest.main()
