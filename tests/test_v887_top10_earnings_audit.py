import importlib.util
import unittest
import tempfile
import json
import hashlib
from pathlib import Path

SPEC=importlib.util.spec_from_file_location("v887",Path(__file__).resolve().parents[1]/"scripts/v887_top10_earnings_audit.py")
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

def income(code,eps,rev,gp,op,ni):
    return dict(code=code,basic_eps_ytd=eps,revenue_ytd_k=rev,gross_profit_ytd_k=gp,
                operating_profit_ytd_k=op,net_income_ytd_k=ni)

class EarningsAuditTests(unittest.TestCase):
    def setUp(self):
        self.row=dict(code="3305",name="昇貿",market="TWSE",reference_close=100.0,
                      base=dict(eps=10.0,pe=15.0,target_price=150.0),
                      original_current_issuer_numeric_checked=True)
        self.prior=income("3305",1.0,800000,120000,60000,30000)
        self.now=income("3305",2.5,1200000,230000,120000,100000)
        self.cash=dict(code="3305",operating_cashflow_ytd_k=-150000)
        self.fy=income("3305",3.5,1650000,280000,140000,120000)
    def test_negative_cash_does_not_turn_into_exit_or_certification(self):
        r=mod.analyze(self.row,self.prior,self.now,self.cash,self.fy,
                      {"unverified_bond_terms":["CB"]},2)
        self.assertIn("NEGATIVE_YTD_OPERATING_CASHFLOW_CHECK_WORKING_CAPITAL",r["flags"])
        self.assertIn("LISTED_CB_TERMS_UNVERIFIED",r["flags"])
        self.assertFalse(r["formal_Aplus"])
        self.assertEqual(r["double_10pct_stress_price"],121.5)
        self.assertEqual(r["double_20pct_stress_upside_pct"],-4.0)
        self.assertEqual(r["2027_eps_over_ytd_runrate"],2.0)
    def test_better_cash_and_current_numerics_not_formal_pass(self):
        self.cash["operating_cashflow_ytd_k"]=150000
        r=mod.analyze(self.row,self.prior,self.now,self.cash,self.fy,{},2)
        self.assertFalse(r["formal_Aplus"])
        self.assertEqual(r["status"],"EVIDENCE_TRIAGE_ONLY_NOT_CERTIFIED")
        self.assertEqual(r["gross_margin_latest_pct"],19.17)
    def test_missing_statements_fail_closed(self):
        r=mod.analyze(self.row,None,self.now,self.cash,self.fy,{},2)
        self.assertEqual(r["status"],"MISSING_REQUIRED_FINANCIAL_SOURCE")
        self.assertFalse(r["formal_Aplus"])
    def test_wrong_company_and_mutated_price_are_refused(self):
        with self.assertRaisesRegex(ValueError,"ISSUER_CODE"):
            mod.analyze(self.row,dict(self.prior,code="6494"),self.now,self.cash,self.fy,{},2)
        with self.assertRaisesRegex(ValueError,"VALUATION_BRIDGE_INCONSISTENT"):
            mod.analyze(dict(self.row,base=dict(eps=10,pe=15,target_price=145)),
                        self.prior,self.now,self.cash,self.fy,{},2)
    def _make_monthly_fixture(self, folder, captured="2026-10-19T16:59:00+00:00"):
        base=Path(folder)/"tw-market-data"
        shard=base/"2026-09/revenue_3.json"
        shard.parent.mkdir(parents=True,exist_ok=True)
        row=dict(code="3305",market="TWSE",report_month="11509",
                 ytd_revenue_k="2500000",last_year_ytd_revenue_k="1800000")
        payload=(json.dumps([row])+"\n").encode()
        shard.write_bytes(payload)
        doc=dict(period="2026-09",capture_utc=captured,
                 shards=[dict(path="tw-market-data/2026-09/revenue_3.json",
                              records=1,sha256=hashlib.sha256(payload).hexdigest())],
                 original_receipts=[])
        (base/"latest_manifest.json").write_text(json.dumps(doc),encoding="utf-8")
        research=dict(estimate_vintage="2026-10-20T03:25:00+08:00",
                      financial_last_quarter="2026-Q2")
        return base,shard,research
    def test_q3_ytd_subtraction_identifies_deceleration(self):
        with tempfile.TemporaryDirectory() as folder:
            base,shard,research=self._make_monthly_fixture(folder)
            out=mod.check_post_financial_quarter_revenue(base,research,
                {("TWSE","3305"):self.now},{("TWSE","3305"):self.prior},[self.row])
            self.assertEqual(out["status"],"NEXT_QUARTER_REVENUE_RECONCILED_BUT_MARGIN_UNVERIFIED")
            item=out["issuer_checks"][0]
            self.assertEqual(item["three_month_revenue_k"],1300000)
            self.assertEqual(item["prior_three_month_revenue_k"],1000000)
            self.assertEqual(item["next_quarter_revenue_yoy_pct"],30.0)
            self.assertEqual(item["current_financial_H1_yoy_pct"],50.0)
            self.assertTrue(item["growth_decelerated_over_20pp"])
            self.assertFalse(item["gross_margin_for_next_quarter_verified"])
    def test_monthly_revenue_tamper_or_future_capture_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            base,shard,research=self._make_monthly_fixture(folder)
            shard.write_text("tampered",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"SHARD_SHA_MISMATCH"):
                mod.check_post_financial_quarter_revenue(base,research,
                    {("TWSE","3305"):self.now},{("TWSE","3305"):self.prior},[self.row])
            base,shard,research=self._make_monthly_fixture(folder,"2026-10-21T16:59:00+00:00")
            with self.assertRaisesRegex(ValueError,"FUTURE_OR_UNZONED"):
                mod.check_post_financial_quarter_revenue(base,research,
                    {("TWSE","3305"):self.now},{("TWSE","3305"):self.prior},[self.row])
    def test_runrate_not_extrapolated_when_year_to_date_loss(self):
        r=mod.analyze(self.row,self.prior,dict(self.now,basic_eps_ytd=-2),
                      self.cash,self.fy,{},2)
        self.assertIsNone(r["2027_eps_over_ytd_runrate"])

if __name__ == "__main__":
    unittest.main()
