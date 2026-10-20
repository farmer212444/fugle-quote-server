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
    def test_valid_official_table_and_date(self):
        b=payload("2026-10-16")
        parsed=parse_daily(b,"2026-10-16")
        self.assertEqual(len(parsed),312)
        self.assertEqual(parsed["6494"]["turnover_ntd"],1000000)
        self.assertEqual(parsed["5439"]["close"],230.0)
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
if __name__=="__main__":unittest.main()
