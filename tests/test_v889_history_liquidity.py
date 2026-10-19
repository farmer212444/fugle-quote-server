import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from scripts.v884_evidence_probe import issuer_backfill_probe

def fixture(root):
    months={}
    a=dt.date(2026,9,14);end=dt.date(2026,10,16)
    date=a;rows=[]
    while date<=end:
        if date.weekday()<5:
            rows.append(dict(date=date.isoformat(),turnover_ntd=4_000_000,close=100))
        date+=dt.timedelta(days=1)
    for month in ("2026-09","2026-10"):
        segment=[x for x in rows if x["date"][:7]==month]
        months[month]=dict(source_url="https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date="+month.replace("-","")+"01&stockNo=6206&response=json",
             original_response_sha256="a"*64,rows=segment)
    snapshot=dict(schema="V889_OFFICIAL_TWSE_ISSUER_MONTHLY",
      issuer="6206",market="TWSE",price_reference_asof="2026-10-16",
      formal_tradability_gate="PENDING_NOT_CERTIFIED",by_month=months,
      sessions=sorted(rows,key=lambda x:x["date"],reverse=True))
    p=Path(root)/"prices/issuer_history/TWSE/6206.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(snapshot))
    return p

class IssuerHistoryBridgeTests(unittest.TestCase):
    def test_valid_original_months_add_20_observations_not_certification(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture(temp)
            r=issuer_backfill_probe(temp,"2026-10-16","TWSE","6206")
            self.assertIsNotNone(r["twenty_day"])
            self.assertEqual(r["twenty_day"]["sessions"],20)
            self.assertEqual(r["tradability_gate"],"PENDING_NOT_CERTIFIED")
            self.assertTrue(r["original_capture_is_not_authenticated_issuer_PIT"])
    def test_future_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture(temp)
            with self.assertRaisesRegex(ValueError,"FUTURE_ISSUER"):
                issuer_backfill_probe(temp,"2026-10-15","TWSE","6206")
    def test_tampering_stored_session_or_source_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=fixture(temp)
            j=json.loads(p.read_text())
            j["sessions"][0]["turnover_ntd"]=99
            p.write_text(json.dumps(j))
            with self.assertRaisesRegex(ValueError,"NORMALIZED_SOURCE_MISMATCH"):
                issuer_backfill_probe(temp,"2026-10-16","TWSE","6206")
        with tempfile.TemporaryDirectory() as temp:
            p=fixture(temp)
            j=json.loads(p.read_text())
            j["by_month"]["2026-10"]["source_url"]="https://example.com/forged"
            p.write_text(json.dumps(j))
            with self.assertRaisesRegex(ValueError,"UNTRUSTED"):
                issuer_backfill_probe(temp,"2026-10-16","TWSE","6206")
    def test_official_lag_does_not_create_fake_current_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture(temp)
            r=issuer_backfill_probe(temp,"2026-10-19","TWSE","6206")
            self.assertEqual(r["status"],"PENDING_REFERENCE_SESSION_MISSING")
            self.assertIsNone(r["twenty_day"])
    def test_no_file_means_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(issuer_backfill_probe(temp,"2026-10-16","TPEX","8390"))
if __name__=="__main__":unittest.main()
