"""Official-dated whole-market close backfill: no mixing dates or inventing data."""
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from scripts.v8a4_market_close_recovery import source_url, parse, recover, reconcile_sessions

def fixture(market="TWSE",date="2026-10-20"):
    if market=="TWSE":
        cols=["證券代號","證券名稱","成交股數","成交金額","收盤價"]
        records=[[str(x),"測試","12,000","1,200,000","100.00"] for x in range(1100,1420)]
        tables=[dict(title="價格指數",fields=["價格"],data=[["50"]]),
                dict(title="115年10月20日 每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))",
                     fields=cols,data=records)]
        stat="OK"
    else:
        cols=["代號","名稱","收盤","成交股數","成交金額(元)"]
        records=[[str(x),"測試","50.00","12,000","600,000"] for x in range(6000,6320)]
        tables=[dict(title="上櫃股票行情",fields=cols,data=records)]
        stat="ok"
    return json.dumps(dict(date=date.replace("-",""),stat=stat,tables=tables),
                      ensure_ascii=False).encode()

class DatedMarketRecoveryTests(unittest.TestCase):
    def test_valid_twse_bulk_recovery_preserves_source_bytes_and_exact_date(self):
        raw=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            rows,day,h,url=recover("TWSE","2026-10-20","2026-10-19",tmp,fetch=lambda u:raw)
            self.assertEqual((day,len(rows),rows[0]["close"],rows[0]["turnover_ntd"]),
                             ("2026-10-20",320,100.,1200000))
            self.assertEqual((Path(tmp)/"twse_dated_2026-10-20.json").read_bytes(),raw)
            self.assertIn("date=20261020",url)
    def test_valid_tpex_roc_format_and_strict_market_code(self):
        rows=parse("TPEX",fixture("TPEX"),"2026-10-20")
        self.assertEqual(len(rows),320)
        self.assertIn("date=115%2F10%2F20",source_url("TPEX","2026-10-20"))
    def test_reject_wrong_day_never_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"RESPONSE_DATE_MISMATCH"):
                recover("TWSE","2026-10-21","2026-10-20",tmp,
                        fetch=lambda u:fixture("TWSE","2026-10-20"))
            self.assertFalse(list(Path(tmp).glob("*")))
    def test_reject_repeated_or_missing_stock_and_regression(self):
        j=json.loads(fixture())
        j["tables"][1]["data"][5][0]=j["tables"][1]["data"][4][0]
        with self.assertRaisesRegex(ValueError,"DUPLICATE_STOCK"):
            parse("TWSE",json.dumps(j).encode(),"2026-10-20")
        with self.assertRaisesRegex(ValueError,"NOT_NEWER"):
            recover("TWSE","2026-10-19","2026-10-19","/tmp",lambda u:fixture())
        with self.assertRaisesRegex(ValueError,"INVALID_DATED"):
            source_url("TWSE","2026-10-20;DROP")
    def test_no_half_archive_with_failed_second_market(self):
        raw=fixture("TWSE")
        self.assertEqual(len(parse("TWSE",raw,"2026-10-20")),320)
        with self.assertRaises(ValueError):
            parse("TPEX",raw,"2026-10-20")

    def inputs(self,twse="2026-11-05",tpex="2026-11-05"):
        return {m:([dict(market=m,date=d)],d,m+"-old-sha")
                for m,d in (("TWSE",twse),("TPEX",tpex))}

    def test_both_stale_openapis_recover_today_from_exact_official_dates(self):
        gathered=self.inputs();before=copy.deepcopy(gathered);calls=[]
        def repair(market,day,previous,rawdir):
            calls.append((market,day,previous))
            return [dict(market=market,date=day)],day,market+"-new-sha",source_url(market,day)
        fixed,routes,recovered=reconcile_sessions(gathered,{},"/tmp",
            dt.datetime.fromisoformat("2026-11-06T15:00:00+08:00"),recover_fn=repair)
        self.assertEqual(recovered,["TWSE","TPEX"])
        self.assertEqual([x[1] for x in calls],["2026-11-06"]*2)
        self.assertEqual({x[1] for x in fixed.values()},{"2026-11-06"})
        self.assertEqual(gathered,before)
        self.assertIn("date=20261106",routes["TWSE"])

    def test_current_feeds_do_not_redownload_and_mismatched_feeds_repair_only_one(self):
        calls=[]
        def repair(market,day,previous,rawdir):
            calls.append(market)
            return [dict(market=market,date=day)],day,"sha",source_url(market,day)
        now=dt.datetime.fromisoformat("2026-11-06T16:00:00+08:00")
        reconcile_sessions(self.inputs("2026-11-06","2026-11-06"),{},"/tmp",now,recover_fn=repair)
        self.assertFalse(calls)
        reconcile_sessions(self.inputs("2026-11-06"),{},"/tmp",now,recover_fn=repair)
        self.assertEqual(calls,["TPEX"])

    def test_morning_and_weekend_recovery_do_not_request_an_unfinished_session(self):
        for clock in ("2026-11-06T08:10:00+08:00","2026-11-07T08:10:00+08:00"):
            expected="2026-11-05" if "11-06" in clock else "2026-11-06"
            calls=[]
            def repair(market,day,previous,rawdir):
                calls.append(day)
                return [dict(market=market,date=day)],day,"sha","url"
            reconcile_sessions(self.inputs("2026-11-04","2026-11-04"),{},"/tmp",
                dt.datetime.fromisoformat(clock),recover_fn=repair)
            self.assertEqual(calls,[expected]*2)

    def test_second_market_failure_never_returns_a_mixed_date_snapshot(self):
        gathered=self.inputs();before=copy.deepcopy(gathered)
        def repair(market,day,previous,rawdir):
            if market=="TPEX":raise ValueError("not final")
            return [dict(market=market,date=day)],day,"sha","url"
        with self.assertRaisesRegex(ValueError,"not final"):
            reconcile_sessions(gathered,{},"/tmp",dt.datetime.fromisoformat("2026-11-06T16:00:00+08:00"),recover_fn=repair)
        self.assertEqual(gathered,before)

    def test_known_closure_preserves_last_session_and_future_feed_is_rejected(self):
        now=dt.datetime.fromisoformat("2026-10-23T16:00:00+08:00")
        closed=[dict(date="2026-10-23",observed_public_at="2026-10-22T20:00:00+08:00")]
        fixed,_,repaired=reconcile_sessions(self.inputs("2026-10-22","2026-10-22"),{},"/tmp",now,closed)
        self.assertFalse(repaired)
        self.assertEqual(fixed["TWSE"][1],"2026-10-22")
        with self.assertRaisesRegex(ValueError,"AFTER_PUBLISHABLE_SESSION"):
            reconcile_sessions(self.inputs("2026-11-06","2026-11-06"),{},"/tmp",now)

if __name__=="__main__":
    unittest.main()
