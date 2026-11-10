"""Marketwide history priority must advance without losing frozen cohorts."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.marketwide_history_priority import marketwide_uncovered
from scripts.tw_history_backfill import prioritized_candidates
from scripts.v893_tpex_daily_backfill import selected_codes

ASOF="2026-11-09"

def save(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")

def quotes(market, codes):
    return json.dumps([
        dict(market=market,code=code,close=50.0,
             turnover_ntd=turnover,date=ASOF)
        for code,turnover in codes],ensure_ascii=False).encode()

class HistoryBreadthTests(unittest.TestCase):
    def test_breadth_includes_unarchived_liquid_and_filters_zero_or_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            save(root/"prices/issuer_history/TWSE/2317.json",
                 dict(issuer="2317",market="TWSE"))
            raw=json.dumps([
                dict(market="TWSE",code="2317",date=ASOF,close=100,turnover_ntd=9000000),
                dict(market="TWSE",code="2330",date=ASOF,close=100,turnover_ntd=8000000),
                dict(market="TWSE",code="6206",date=ASOF,close=100,turnover_ntd=7000000),
                dict(market="TWSE",code="9802",date=ASOF,close=100,turnover_ntd=6000000),
                dict(market="TWSE",code="3020",date=ASOF,close=None,turnover_ntd=90000000),
                dict(market="TPEX",code="6781",date=ASOF,close=100,turnover_ntd=10000000)]).encode()
            self.assertEqual(marketwide_uncovered(root,raw,"TWSE",ASOF,excluded=["2330"],cap=2),
                             ["6206","9802"])
            self.assertEqual(marketwide_uncovered(root,raw,"TPEX",ASOF,cap=1),["6781"])

    def test_lookahead_dated_quote_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw=json.dumps([dict(market="TWSE",code="2317",
                                 close=100,date="2026-11-10")]).encode()
            with self.assertRaisesRegex(ValueError,"DATE_MISMATCH"):
                marketwide_uncovered(Path(tmp),raw,"TWSE",ASOF)

    def test_tpex_adds_six_unarchived_issuers_without_duplicate_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            save(root/"rankings/v891_gate_progress.json",
                 dict(asof_price_date=ASOF,issuer_diagnostics=[
                    dict(code="6494",market="TPEX",research_upside_pct=120)]))
            data=[("6494",1000000)]+[
                (f"{7000+i}",10000000-i*5000) for i in range(9)]
            chosen, latest=selected_codes(root,ASOF,quotes("TPEX",data))
            self.assertEqual(chosen[0],"6494")
            self.assertEqual(len(chosen),7)
            self.assertEqual(len(chosen),len(set(chosen)))
            self.assertEqual(len(latest),10)

    def test_twse_completed_history_does_not_recapture_every_new_asof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            base=dt.date(2026,11,9)
            sessions=[{"date":(base-dt.timedelta(days=i)).isoformat(),
                       "close":120.0} for i in range(61)]
            save(root/"prices/issuer_history/TWSE/6206.json",
                dict(issuer="6206",market="TWSE",
                     price_reference_asof="2026-11-06",
                     sessions=sessions,by_month={},liquidity={"20":{"sessions":20}}))
            raw=quotes("TWSE",[
                ("6206",50000000),("9802",40000000),
                ("2317",30000000),("2330",20000000),
                ("2739",19000000),("2454",18000000),
                ("2303",17000000),("3034",16000000)])
            with patch("scripts.tw_history_backfill.quote_source_ready",return_value=True):
                chosen=prioritized_candidates(raw,ASOF,6,root,execution_archive=True,months=4)
            self.assertNotIn("6206",chosen)
            self.assertEqual(chosen[0],"9802")
            self.assertEqual(len(chosen),6)
            self.assertTrue({"3034","2303"}.intersection(chosen))
            self.assertEqual(len(set(chosen)),6)

if __name__=="__main__":
    unittest.main()
