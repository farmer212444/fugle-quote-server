import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from scripts.tw_history_backfill import (
    parse, process, iso_roc, historical_url, stats, combine, recent_months,
    candidates, prioritized_candidates
)

def response(month,dates):
    data=[]
    for n,date in enumerate(dates):
        y,m,d=map(int,date.split("-"))
        roc=f"{y-1911}/{m:02d}/{d:02d}"
        data.append([roc,f"{1000+n:,}","42",f"{1_000_000+n*1000:,}",
                     "20.5","21.5","20.2","21.0","0.5"])
    return json.dumps(dict(stat="OK",
        fields=["日期","交易股數","交易筆數","成交金額","開盤價","最高價","最低價","收盤價","漲跌價差"],
        data=data,title=f"115年{month[-2:]}月 6206 飛捷 各日成交資訊")).encode()

def days(month):
    y,m=map(int,month.split("-"))
    return [dt.date(y,m,d).isoformat() for d in range(1,29)
            if dt.date(y,m,d).weekday()<5]

class HistoricalTWSETests(unittest.TestCase):
    def test_official_roc_and_turnover_fields(self):
        raw=response("2026-09",days("2026-09"))
        records=parse(raw,"6206","2026-09")
        self.assertTrue(len(records)>=19)
        self.assertEqual(records[0]["date"],days("2026-09")[0])
        self.assertEqual(records[0]["turnover_ntd"],1000000)
        self.assertEqual(iso_roc("115/09/30"),"2026-09-30")
        self.assertIn("stockNo=6206",historical_url("6206","2026-09"))
    def test_bad_month_duplicate_and_invalid_amount_fail(self):
        raw=json.loads(response("2026-09",days("2026-09")))
        raw["data"][0][0]="115/08/01"
        with self.assertRaisesRegex(ValueError,"MONTH_MISMATCH"):
            parse(json.dumps(raw).encode(),"6206","2026-09")
        raw=json.loads(response("2026-09",days("2026-09")))
        raw["data"][1][0]=raw["data"][0][0]
        with self.assertRaisesRegex(ValueError,"DUPLICATED"):
            parse(json.dumps(raw).encode(),"6206","2026-09")
        raw=json.loads(response("2026-09",days("2026-09")))
        raw["data"][2][3]="X"
        with self.assertRaisesRegex(ValueError,"TURNOVER"):
            parse(json.dumps(raw).encode(),"6206","2026-09")
    def test_two_months_produce_20_day_evidence_but_not_gate_pass(self):
        sources={"2026-09":response("2026-09",days("2026-09")),
                 "2026-10":response("2026-10",days("2026-10"))}
        def fetch(url):
            return sources["2026-"+url.split("date=2026")[1][0:2]]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"out";r=Path(tmp)/"raw"
            x=process("6206","2026-10-16",["2026-10","2026-09"],fetch,p,r,sleep=0)
            self.assertTrue(x["twenty"])
            self.assertEqual(x["months"],2)
            doc=json.loads((p/"6206.json").read_text())
            self.assertEqual(doc["formal_tradability_gate"],"PENDING_NOT_CERTIFIED")
            self.assertFalse(doc["original_source_not_cryptographically_signed"] is False)
            self.assertTrue(all(row["date"]<="2026-10-16" for row in doc["sessions"]))
            old=(p/"6206.json").read_bytes()
            x2=process("6206","2026-10-16",["2026-10","2026-09"],fetch,p,r,sleep=0)
            self.assertEqual(x2["new_months"],0)
            self.assertEqual((p/"6206.json").read_bytes(),old)
            # Current-month arrival expands only future as-of values.
            y=process("6206","2026-10-20",["2026-10","2026-09"],fetch,p,r,sleep=0)
            self.assertTrue(y["twenty"])
            self.assertEqual(json.loads((p/"6206.json").read_text())["sessions"][0]["date"],"2026-10-20")
    def test_source_failure_keeps_previous_months(self):
        s=response("2026-09",days("2026-09"))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"out";r=Path(tmp)/"raw"
            process("6206","2026-10-16",["2026-09"],lambda url:s,p,r,sleep=0)
            def bad(url):raise TimeoutError("official data failed")
            info=process("6206","2026-10-16",["2026-10","2026-09"],bad,p,r,sleep=0)
            self.assertEqual(info["months"],1)
            self.assertEqual(len(info["source_errors"]),1)
    def test_selected_universe_is_official_twse(self):
        raw=json.dumps([
            dict(code="6206",market="TWSE"),dict(code="9802",market="TWSE"),
            dict(code="1714",market="TWSE"),dict(code="8390",market="TPEX")]).encode()
        self.assertEqual(candidates(raw,6),["6206","9802","1714"])
        self.assertEqual(recent_months(dt.date(2026,1,20),3),["2026-01","2025-12","2025-11"])
        self.assertIsNone(stats([], "2026-10-16")["20"])
    def test_priority_skips_completed_20_day_archive_and_keeps_high_upside(self):
        raw=json.dumps([
            dict(code="6206",market="TWSE"),dict(code="9802",market="TWSE"),
            dict(code="1714",market="TWSE"),dict(code="3305",market="TWSE"),
            dict(code="4739",market="TWSE"),dict(code="6494",market="TPEX")]).encode()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"rankings").mkdir()
            progress=dict(asof_price_date="2026-10-16",issuer_diagnostics=[
                dict(code="6494",market="TPEX",research_upside_pct=141),
                dict(code="1714",market="TWSE",research_upside_pct=140),
                dict(code="3305",market="TWSE",research_upside_pct=110),
                dict(code="4739",market="TWSE",research_upside_pct=106)])
            (root/"rankings/v891_gate_progress.json").write_text(json.dumps(progress))
            hist=root/"prices/issuer_history/TWSE"
            hist.mkdir(parents=True)
            (hist/"1714.json").write_text(json.dumps(dict(issuer="1714",market="TWSE",
                  price_reference_asof="2026-10-16",liquidity={"20":{"sessions":20}})))
            self.assertEqual(prioritized_candidates(raw,"2026-10-16",2,root),["3305","4739"])
            with self.assertRaisesRegex(ValueError,"PRICE_DATE_MISMATCH"):
                prioritized_candidates(raw,"2026-10-17",2,root)
    def test_future_date_never_included(self):
        rows={"2026-10":[dict(date="2026-10-18",turnover_ntd=3,close=12)]}
        self.assertEqual(combine(rows,"2026-10-16","6206"),[])
if __name__=="__main__":unittest.main()
