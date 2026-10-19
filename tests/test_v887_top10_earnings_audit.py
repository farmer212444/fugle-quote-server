import importlib.util
import unittest
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
    def test_runrate_not_extrapolated_when_year_to_date_loss(self):
        r=mod.analyze(self.row,self.prior,dict(self.now,basic_eps_ytd=-2),
                      self.cash,self.fy,{},2)
        self.assertIsNone(r["2027_eps_over_ytd_runrate"])

if __name__ == "__main__":
    unittest.main()
