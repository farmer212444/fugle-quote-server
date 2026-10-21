"""Official-dated whole-market close backfill: no mixing dates or inventing data."""
import json
import tempfile
import unittest
from pathlib import Path
from scripts.v8a4_market_close_recovery import source_url, parse, recover

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

if __name__=="__main__":
    unittest.main()
