import datetime as dt
import hashlib
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from scripts.v884_evidence_probe import price_archive,liquidity_probe,probe,financial_probe,capital_probe,issuer_backfill_probe,reconcile_issuer_reference_history

class OfficialEvidenceProbeTests(unittest.TestCase):
    def test_stale_monthly_history_merged_with_real_dated_official_reference(self):
        # This regression uses the exact preserved official 2026-10-19 TWSE
        # normalized price, and pre-existing monthly issuer-history snapshots
        # whose latest session is 2026-10-16. No invented fill-in dates.
        root=pathlib.Path(__file__).resolve().parents[1]/"tw-market-data"
        official=json.loads((root/"prices/2026-10-19.json").read_text())
        for code in ("6206","9802"):
            rows=[x for x in official if x.get("market")=="TWSE" and x.get("code")==code]
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["date"],"2026-10-19")
            sample=[("2026-10-19",{("TWSE",code):rows[0]["turnover_ntd"]})]
            older=issuer_backfill_probe(root,"2026-10-19","TWSE",code)
            self.assertEqual(older["status"],"PENDING_REFERENCE_SESSION_MISSING")
            merged=issuer_backfill_probe(root,"2026-10-19","TWSE",code,
                                          reference_archives=sample)
            self.assertEqual(merged["status"],"SOURCE_CAPTURED_NOT_FULL_TRADABILITY")
            self.assertEqual(merged["validated_archive_additions"],1)
            self.assertEqual(merged["twenty_day"]["sessions"],20)
            self.assertEqual(merged["twenty_day"]["last"],"2026-10-19")
            self.assertIsInstance(merged["twenty_day"]["median_turnover_ntd"],(int,float))
            self.assertEqual(merged["tradability_gate"],"PENDING_NOT_CERTIFIED")

    def test_contradictory_same_day_turnover_stays_pending(self):
        historical={"2026-10-16":100_000_000,"2026-10-19":20_000_000}
        ref=[("2026-10-19",{("TWSE","6206"):20_000_001})]
        result=reconcile_issuer_reference_history(historical,ref,"2026-10-19","TWSE","6206")
        self.assertEqual(result["status"],"SOURCE_CONFLICT_REVIEW_REQUIRED")
        self.assertIsNone(result["twenty_day"])
        self.assertEqual(result["turnover_conflicts"][0]["date"],"2026-10-19")
        self.assertEqual(result["tradability_gate"],"PENDING_NOT_CERTIFIED")

    def test_no_newer_reference_no_20day_fill_and_no_lookahead(self):
        historical={(dt.date(2026,9,1)+dt.timedelta(days=i)).isoformat():
                    5_000_000 for i in range(30)}
        result=reconcile_issuer_reference_history(historical,[],"2026-10-19","TWSE","9802")
        self.assertEqual(result["status"],"PENDING_REFERENCE_SESSION_MISSING")
        self.assertIsNone(result["twenty_day"])
        with self.assertRaisesRegex(ValueError,"DAILY_ARCHIVE_AFTER_PRICE_REFERENCE_DATE"):
            reconcile_issuer_reference_history(
                historical,[("2026-10-20",{("TWSE","9802"):1})],
                "2026-10-19","TWSE","9802")

    def test_hash_checked_20_sessions_and_no_false_gate_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);folder=root/"prices";folder.mkdir()
            start=dt.date(2026,9,21);last=None
            for day_index in range(20):
                day=(start+dt.timedelta(days=day_index)).isoformat()
                rows=[dict(market="TWSE",code="9802",date=day,close=60,turnover_ntd=10_000_000),
                      dict(market="TWSE",code="9904",date=day,close=30,turnover_ntd=6_000_000)]
                raw=(json.dumps(rows)+"\n").encode();(folder/(day+".json")).write_bytes(raw)
                if day_index==19:last=dict(date=day,normalized_sha256=hashlib.sha256(raw).hexdigest())
            dates,receipts=price_archive(root,last["date"],last,minimum_rows=2)
            self.assertEqual(len(dates),20)
            self.assertFalse(receipts[-1]["raw_official_bytes_independently_authenticated"])
            value=liquidity_probe(dates,("TWSE","9802"))
            self.assertEqual(value["twenty_day"]["median_turnover_ntd"],10_000_000)
            self.assertEqual(value["twenty_day"]["exit_sessions_at_median"],2.5)
            self.assertIsNone(value["sixty_day"])
            self.assertEqual(value["tradability_gate"],"PENDING_NOT_CERTIFIED")
            finance={("TWSE","9802"):{f"2025-Q{i}":{} for i in range(1,5)}}
            fake=SimpleNamespace(history=finance,cash={},required_periods=[f"2025-Q{i}" for i in range(1,5)]+[f"2026-Q{i}" for i in range(1,5)],
                                  evidence=dict(master={"9802":{}},bonds={"9802":[dict(code="98026",current_terms_verified=False)]}),
                                  root=root,primary=lambda c:None)
            row=dict(code="9802",market="TWSE",name="鈺齊",research_upside_pct=45,
                     source_status="CERTIFICATION_PENDING",evidence_state="PENDING_NOT_CERTIFIED",formal_Aplus=False,
                     pending_gates=["tradability","fully_diluted_shares","auditor_scope"])
            r=dict(model="V8.8.2",estimate_vintage="2026-10-19T12:00:00+08:00",asof_price_date=last["date"],
                   data_scope=dict(model_rows=1),formal_Aplus_count=0)
            d=dict(model="V8.8.2",vintage=r["estimate_vintage"],price_date=r["asof_price_date"],
                   tracked_issuer_count=1,all_issuer_jobs=[row])
            p=probe(r,d,fake,dates,receipts)
            self.assertEqual(p["counts"]["20_sessions_observed"],1)
            self.assertEqual(p["newly_verified_gates"],0)
            self.assertEqual(p["newly_certified_Aplus"],0)
            self.assertEqual(p["top_priority_evidence"][0]["financial"]["normalized_income_8q_count"],4)
            self.assertEqual(p["top_priority_evidence"][0]["capital"]["unverified_bond_terms"],["98026"])
            self.assertEqual(len(p["manual_review_queue"]),1)

    def test_all_high_upside_issuers_probed_even_when_top_is_one(self):
        # Previously the first top-N alone was probed. A high-upside issuer
        # outside the first N silently became NOT_PROBED in gate progress.
        from types import SimpleNamespace
        rows = [
            dict(code=code, name=code, market="TWSE", research_upside_pct=upside,
                 source_status="CERTIFICATION_PENDING",
                 evidence_state="PENDING_NOT_CERTIFIED", formal_Aplus=False,
                 pending_gates=["original_eight_quarter_statements", "forecast_bridge"])
            for code, upside in (("1714", 50.0), ("6494", 38.0),
                                 ("6206", 27.0), ("9802", 12.0))
        ]
        asof = "2026-10-20T22:00:00+08:00"
        research = dict(model="V8.8.2", estimate_vintage=asof,
                        asof_price_date="2026-10-19",
                        data_scope=dict(model_rows=len(rows)), formal_Aplus_count=0)
        dispatch = dict(model="V8.8.2", vintage=asof,
                        price_date="2026-10-19",
                        tracked_issuer_count=len(rows), all_issuer_jobs=rows)
        fake_data = SimpleNamespace(history={}, cash={}, required_periods=[],
                        evidence=dict(master={}, bonds={}), primary=lambda code: None,
                        root=pathlib.Path(__file__).resolve().parent)
        result = probe(research, dispatch, fake_data, [], [], top=1,
                       focus_codes=["9802"])
        self.assertEqual(result["high_upside_research_candidates"], 2)
        self.assertEqual(result["high_upside_profiles_probed"], 2)
        self.assertEqual(result["high_upside_not_probed"], 0)
        self.assertEqual([r["code"] for r in result["top_priority_evidence"]],
                         ["1714", "6494", "9802"])
        self.assertEqual(result["newly_certified_Aplus"], 0)
        self.assertEqual(result["newly_verified_gates"], 0)
        self.assertTrue(all(not p["ready_for_formal_certification"]
                            for p in result["top_priority_evidence"]))

    def test_tampered_price_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);p=root/"prices";p.mkdir()
            day="2026-10-16";f=p/(day+".json")
            f.write_text(json.dumps([dict(date=day,market="TWSE",code="9802",turnover_ntd=0)]))
            with self.assertRaisesRegex(ValueError,"HASH_MISMATCH"):
                price_archive(root,day,dict(date=day,normalized_sha256="0"*64),minimum_rows=1)

    def test_future_price_excluded_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);p=root/"prices";p.mkdir()
            day="2026-10-16"
            a=[dict(date=day,market="TWSE",code="9802",turnover_ntd=1)]
            raw=json.dumps(a).encode();(p/(day+".json")).write_bytes(raw)
            (p/"2026-10-17.json").write_text(json.dumps([dict(date="2026-10-17",market="TWSE",code="9802",turnover_ntd=999_999_999)]))
            dated,_=price_archive(root,day,dict(date=day,normalized_sha256=hashlib.sha256(raw).hexdigest()),minimum_rows=1)
            self.assertEqual(len(dated),1)
            self.assertIsNone(liquidity_probe(dated,("TWSE","9802"))["twenty_day"])
            b=a+a
            rb=json.dumps(b).encode();(p/(day+".json")).write_bytes(rb)
            with self.assertRaisesRegex(ValueError,"DUPLICATE_PRICE_ISSUER"):
                price_archive(root,day,dict(date=day,normalized_sha256=hashlib.sha256(rb).hexdigest()),minimum_rows=1)

    def test_bad_dispatch_cannot_be_treated_as_certification(self):
        fake=SimpleNamespace()
        research=dict(model="V8.8.2",estimate_vintage="2026-10-19T12:00:00+08:00",
                      asof_price_date="2026-10-16",data_scope=dict(model_rows=1),formal_Aplus_count=0)
        job=dict(code="9802",market="TWSE",formal_Aplus=True,evidence_state="PENDING_NOT_CERTIFIED")
        dispatch=dict(model="V8.8.2",vintage=research["estimate_vintage"],price_date="2026-10-16",
                      tracked_issuer_count=1,all_issuer_jobs=[job])
        with self.assertRaisesRegex(ValueError,"FALSE_PROMOTION"):
            probe(research,dispatch,fake,[],[])
        dispatch["vintage"]="2026-10-18T12:00:00+08:00"
        with self.assertRaisesRegex(ValueError,"VINTAGE_MISMATCH"):
            probe(research,dispatch,fake,[],[])

if __name__=="__main__":
    unittest.main()
