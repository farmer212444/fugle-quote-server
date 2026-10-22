import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from scripts.v893_tpex_daily_backfill import parse_daily, daily_url, run, build_issuer

FIELDS=["代號","名稱","收盤","漲跌","開盤","最高","最低","均價","成交股數","成交金額(元)","成交筆數"]
def payload(day,code="6494",rev=False):
    equities=[[code,"九齊","50.0","+1","50","50","49","49","10,000","1,000,000","25"],
        ["5439","高技","230.0","+1","230","234","225","230","5,000","3,000,000","15"]]
    equities.extend([[str(i),"其他","12.5","+0.1","12","12.5","11","12","10,000","120,000","3"]
                       for i in range(4000,4310)])
    table=dict(title="上櫃股票行情",fields=FIELDS,data=equities)
    return json.dumps({"stat":"ok","date":day.replace("-",""),"tables":[table]}).encode()

class ModernTpexTests(unittest.TestCase):
    def seed_reference(self,root,day,codes=('6494',)):
        from scripts.tw_history_backfill import sha
        (root/'prices').mkdir(exist_ok=True);(root/'rankings').mkdir(exist_ok=True)
        normalized=json.dumps([dict(code=code,market='TPEX',close=50. if code=='6494' else 230.) for code in codes]).encode()
        (root/'prices'/f'{day}.json').write_bytes(normalized)
        (root/'prices/latest_manifest.json').write_text(json.dumps(dict(date=day,normalized_sha256=sha(normalized))))
        (root/'rankings/v891_gate_progress.json').write_text(json.dumps(dict(asof_price_date=day,
            issuer_diagnostics=[dict(code=code,market='TPEX',research_upside_pct=140) for code in codes])))

    def test_valid_official_table_and_date(self):
        b=payload("2026-10-16")
        parsed=parse_daily(b,"2026-10-16")
        self.assertEqual(len(parsed),312)
        self.assertEqual(parsed["6494"]["turnover_ntd"],1000000)
        self.assertEqual(parsed["5439"]["close"],230.0)
        self.assertEqual(parsed['5439']['open'],230.0)
        self.assertEqual(parsed['5439']['high'],234.0)
        self.assertEqual(parsed['5439']['low'],225.0)
        self.assertFalse(parsed['5439']['fillability_verified'])
        with self.assertRaisesRegex(ValueError,"DATE_MISMATCH"):
            parse_daily(b,"2026-10-15")
        self.assertIn("date=115%2F10%2F16",daily_url("2026-10-16"))
    def test_20_day_issuer_never_becomes_formal_pass(self):
        samples={}
        for n in range(26):
            d=(dt.date(2026,10,16)-dt.timedelta(days=n))
            if d.weekday()<5:
                iso=d.isoformat()
                samples[iso]=dict(date=iso,source_url=daily_url(iso),
                    original_response_sha256="a"*64,row=dict(date=iso,turnover_ntd=1000000,close=50.0,volume_shares=10000))
        a=build_issuer("6494","2026-10-16",samples)
        self.assertIsNotNone(a["liquidity"]["20"])
        self.assertEqual(a["formal_tradability_gate"],"PENDING_NOT_CERTIFIED")
    def test_fixture_fails_missing_sources_without_forged_certification(self):
        a=build_issuer("6494","2026-10-16",{})
        self.assertIsNone(a["liquidity"]["20"])
        self.assertFalse(a["issuer_PIT_history_verified"])

    def test_already_collected_turnover_is_refetched_once_to_archive_original_open(self):
        from scripts.tw_history_backfill import sha
        from scripts.history_archive import verify_original
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'prices').mkdir();(root/'rankings').mkdir()
            day='2026-10-16'
            normalized=json.dumps([dict(code='6494',market='TPEX',close=50.0)]).encode()
            (root/'prices'/f'{day}.json').write_bytes(normalized)
            (root/'prices/latest_manifest.json').write_text(json.dumps(dict(date=day,normalized_sha256=sha(normalized))))
            (root/'rankings/v891_gate_progress.json').write_text(json.dumps(dict(asof_price_date=day,
                issuer_diagnostics=[dict(code='6494',market='TPEX',research_upside_pct=140)])))
            out=root/'prices/issuer_history/TPEX';out.mkdir(parents=True)
            old={}
            for n in range(28):
                d=(dt.date(2026,10,16)-dt.timedelta(days=n)).isoformat()
                old[d]=dict(row=dict(date=d,close=50,turnover_ntd=1000000))
            (out/'6494.json').write_text(json.dumps(build_issuer('6494',day,old)))
            requests=[]
            def fetch(url):
                requests.append(url);return payload(day)
            first=run(1,65,fetch,root,root/'raw',target_sessions=1)
            self.assertEqual(first['attempted_dates'],1)
            doc=json.loads((out/'6494.json').read_text())
            reference=doc['by_day'][day]['original_archive']
            self.assertEqual(verify_original(root,reference),payload(day))
            again=run(1,65,fetch,root,root/'raw',target_sessions=1)
            self.assertEqual(again['attempted_dates'],0)
            self.assertEqual(len(requests),1)

    def test_target_depth_does_not_stop_collection_of_the_next_reference_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.seed_reference(root,'2026-10-16')
            run(1,65,lambda _:payload('2026-10-16'),root,root/'raw',target_sessions=1)
            self.seed_reference(root,'2026-10-19')
            calls=[]
            report=run(1,65,lambda url:(calls.append(url) or payload('2026-10-19')),
                       root,root/'raw',target_sessions=1)
            self.assertEqual(len(calls),1)
            self.assertEqual(report['successful_session_dates'],['2026-10-19'])

    def test_new_candidate_reuses_the_full_market_original_without_refetching(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);day='2026-10-16'
            self.seed_reference(root,day)
            run(1,65,lambda _:payload(day),root,root/'raw',target_sessions=1)
            self.seed_reference(root,day,('5439',))
            report=run(1,65,lambda _:self.fail('re-fetched existing market original'),
                       root,root/'raw',target_sessions=1)
            self.assertEqual(report['attempted_dates'],0)
            doc=json.loads((root/'prices/issuer_history/TPEX/5439.json').read_text())
            self.assertEqual(doc['by_day'][day]['row']['open'],230.)
            self.assertFalse(doc['issuer_PIT_history_verified'])

    def test_failed_date_backs_off_allows_older_progress_and_is_later_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);day='2026-10-16';now=dt.datetime(2026,10,22,tzinfo=dt.timezone.utc)
            self.seed_reference(root,day)
            def failed(_):raise ValueError('SOURCE_UNAVAILABLE_NOT_A_VERIFIED_HOLIDAY')
            with self.assertRaisesRegex(RuntimeError,'NO_VALID_SOURCE_PROGRESS'):
                run(1,65,failed,root,root/'raw',target_sessions=2,now=now)
            state=root/'prices/history_backfill_state/TPEX.json'
            self.assertEqual(json.loads(state.read_text())['dates'][day]['status'],
                             'RETRY_REQUIRED_NOT_VERIFIED_AS_NONTRADING')
            report=run(1,65,lambda _:payload('2026-10-15'),root,root/'raw',target_sessions=2,
                       now=now+dt.timedelta(hours=1))
            self.assertEqual(report['successful_session_dates'],['2026-10-15'])
            self.assertIn(day,report['retry_deferred_dates'])
            report=run(1,65,lambda _:payload(day),root,root/'raw',target_sessions=2,
                       now=now+dt.timedelta(hours=7))
            self.assertEqual(report['successful_session_dates'],[day])
            self.assertNotIn(day,json.loads(state.read_text())['dates'])
if __name__=="__main__":unittest.main()
