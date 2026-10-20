import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from scripts.tw_tpex_history_backfill import parse, url_for, process, candidates
from scripts.v884_evidence_probe import issuer_backfill_probe

def source(month,code="6494"):
    y,m=map(int,month.split("-"))
    dates=[dt.date(y,m,d) for d in range(1,29) if dt.date(y,m,d).weekday()<5]
    rows=[[f"{y-1911}/{m:02d}/{d.day:02d}","1,000","1,000,000",
           "50.5","51.0","49.5","50.0","0","120"] for d in dates]
    return json.dumps({"aaData":rows},ensure_ascii=False).encode()

class TpexHistoryTests(unittest.TestCase):
    def test_monthly_parser_extracts_stated_turnover_and_month(self):
        a=parse(source("2026-09"),"2026-09")
        self.assertGreaterEqual(len(a),19)
        self.assertEqual(a[0]["turnover_ntd"],1000000)
        self.assertIn("stkno=6494",url_for("6494","2026-09"))
        with self.assertRaisesRegex(ValueError,"MONTH_DATE_MISMATCH"):
            parse(source("2026-09"),"2026-08")
        r=json.loads(source("2026-09"))
        r["aaData"][1][0]=r["aaData"][0][0]
        with self.assertRaisesRegex(ValueError,"DUPLICATE_DATE"):
            parse(json.dumps(r).encode(),"2026-09")
    def test_evidence_probe_keeps_tradability_pending(self):
        fake={"2026-10":source("2026-10"),"2026-09":source("2026-09")}
        def fetch(url):
            return fake["2026-"+url.split("d=115%2F")[1][:2]]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/"prices/issuer_history/TPEX";raw=root/"raw"
            result=process("6494","2026-10-16",["2026-10","2026-09"],fetch,out,raw,sleep=0,reference_close=50.0)
            self.assertTrue(result["twenty"])
            issuer=issuer_backfill_probe(root,"2026-10-16","TPEX","6494")
            self.assertEqual(issuer["twenty_day"]["sessions"],20)
            self.assertEqual(issuer["tradability_gate"],"PENDING_NOT_CERTIFIED")
            doc=json.loads((out/"6494.json").read_text())
            self.assertEqual(doc["formal_tradability_gate"],"PENDING_NOT_CERTIFIED")
            self.assertTrue(all(x["date"]<="2026-10-16" for x in doc["sessions"]))
    def test_high_upside_tpex_selection_excludes_twse_and_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"rankings").mkdir()
            (root/"rankings/v891_gate_progress.json").write_text(json.dumps({
                "asof_price_date":"2026-10-16","issuer_diagnostics":[
                 {"code":"6494","market":"TPEX","research_upside_pct":141},
                 {"code":"5439","market":"TPEX","research_upside_pct":112},
                 {"code":"6206","market":"TWSE","research_upside_pct":33}]}))
            raw=json.dumps([{"code":"6494","market":"TPEX"},{"code":"5439","market":"TPEX"},
                {"code":"6206","market":"TWSE"}]).encode()
            self.assertEqual(candidates(raw,"2026-10-16",5,root),["6494","5439"])
            h=root/"prices/issuer_history/TPEX";h.mkdir(parents=True)
            (h/"6494.json").write_text(json.dumps({"issuer":"6494","market":"TPEX",
                "price_reference_asof":"2026-10-16","liquidity":{"20":{"sessions":20}}}))
            self.assertEqual(candidates(raw,"2026-10-16",5,root),["5439"])

if __name__=="__main__":unittest.main()
