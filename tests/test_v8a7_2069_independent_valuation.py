import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v8a7_2069_independent_valuation import (
    SHARES, ASSUMPTIONS, analyze, margin_needed_for_return, markdown, scenario
)


def fixture(root):
    root = Path(root)
    for part in ("fundamentals/2026-Q1", "fundamentals/2026-Q2",
                 "fundamentals/2025-Q4", "prices"):
        (root / part).mkdir(parents=True,exist_ok=True)
    def save(relative,obj):
        p=root/relative
        p.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")
        return p
    def fin(quarter,kind,data):
        save(f"fundamentals/{quarter}/TWSE_{kind}.json",dict(
            period=quarter,market="TWSE",kind=kind,
            raw_sha256="a"*64,company_PIT_verified=False,rows=[
                dict(code="2069",period=quarter,year_to_date_values=True,**data)]))
    fin("2025-Q4","income",dict(revenue_ytd_k=10093068,
        gross_profit_ytd_k=944604,operating_profit_ytd_k=365967,
        basic_eps_ytd=1.62))
    fin("2026-Q1","income",dict(revenue_ytd_k=2302863,
        gross_profit_ytd_k=277674,operating_profit_ytd_k=137979,
        basic_eps_ytd=0.64))
    fin("2026-Q2","income",dict(revenue_ytd_k=4999074,
        gross_profit_ytd_k=733075,operating_profit_ytd_k=380494,
        basic_eps_ytd=1.66))
    fin("2026-Q2","cashflow",dict(operating_cashflow_ytd_k=-114454))
    save("fundamentals/latest_scan.json",dict(last_eligible_quarter="2026-Q2"))
    archive=save("prices/2026-10-20.json",[
        dict(code="2069",market="TWSE",date="2026-10-20",close=24.9)])
    save("prices/latest_manifest.json",dict(
        date="2026-10-20",
        path=f"{root.name}/prices/2026-10-20.json",
        normalized_sha256=hashlib.sha256(archive.read_bytes()).hexdigest()))
    return root


class OperatingBridge2069Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=fixture(Path(self.temp.name)/"tw-market-data")

    def test_real_halfyear_reconciliation_and_one_by_one_scenarios(self):
        report=analyze(self.root,27.35)
        h=report["historical"]
        self.assertAlmostEqual(h["reported_2026_h1_operating_expense_pct"],7.05,places=2)
        self.assertAlmostEqual(h["reported_2026_q2_operating_expense_pct"],7.90,places=2)
        self.assertEqual(h["reported_2026_h1_operating_cashflow_yi"],-1.14454)
        self.assertEqual(h["reported_2026_h1_eps"],1.66)
        self.assertEqual(report["official_reference_close"],24.9)
        self.assertEqual(report["comparison_reference_close"],27.35)
        self.assertEqual(report["scenarios"]["Base"]["fair_price_scenario"],27.37)
        self.assertEqual(report["scenarios"]["Base"]["eps_2027_scenario"],2.4882)
        self.assertEqual(report["scenarios"]["Base"]["reference_price_upside_pct"],0.07)
        self.assertEqual(report["scenarios"]["Bear"]["fair_price_scenario"],11.95)
        self.assertEqual(report["scenarios"]["Bull"]["fair_price_scenario"],50.48)
        self.assertAlmostEqual(report["margin_needed_for_30pct_upside_at_reference_pct"],13.97,places=2)
        self.assertEqual(report["formal_gates_passed_by_this_work"],0)
        self.assertEqual(report["formal_Aplus_added"],0)
        self.assertFalse(report["base_2027_model_auto_modified"])
        self.assertFalse(report["no_trade_or_automatic_exit"] is False)
        self.assertTrue(report["standard_fcf_after_only_ppe_purchase_not_derived_due_to_missing_capex"])
        self.assertIn("27.37",markdown(report))

    def test_reference_price_from_verifiable_daily_archive_is_distinct(self):
        r=analyze(self.root)
        self.assertEqual(r["official_reference_close"],24.9)
        self.assertEqual(r["comparison_source"],
                         "SHA_CHECKED_DAILY_ARCHIVE_NOT_A_BROKER_FILL")
        self.assertAlmostEqual(r["scenarios"]["Base"]["reference_price_upside_pct"],9.92,places=1)

    def test_forged_price_archive_is_rejected_and_never_imputed(self):
        price=self.root/"prices/2026-10-20.json"
        price.write_text(price.read_text()+" ",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"HASH_MISMATCH"):
            analyze(self.root)

    def test_stale_base_when_new_quarter_published_without_restating_eps(self):
        p=self.root/"fundamentals/latest_scan.json"
        p.write_text(json.dumps(dict(last_eligible_quarter="2026-Q3")))
        r=analyze(self.root)
        self.assertEqual(r["status"],
                         "HISTORICAL_2026_H1_BASIS_REQUIRES_NEW_QUARTER_REVIEW")
        self.assertIn("警告",markdown(r))
        self.assertEqual(r["formal_Aplus_added"],0)

    def test_wrong_income_or_cash_data_requires_new_reconciliation(self):
        p=self.root/"fundamentals/2026-Q2/TWSE_cashflow.json"
        j=json.loads(p.read_text())
        j["rows"][0]["operating_cashflow_ytd_k"]=999999
        p.write_text(json.dumps(j))
        with self.assertRaisesRegex(ValueError,"FINANCIAL_BASIS_CHANGED"):
            analyze(self.root)

    def test_margin_break_even_and_strictly_pit_separated_compare(self):
        self.assertEqual(margin_needed_for_return(27.35,30,ASSUMPTIONS["Base"]),13.97)
        with self.assertRaisesRegex(ValueError,"INVALID_USER_QUOTED_REFERENCE"):
            analyze(self.root,float("nan"))
        with self.assertRaisesRegex(ValueError,"INVALID_2069_VALUATION_INPUT"):
            scenario("fake",dict(ASSUMPTIONS["Base"],reasonable_pe=100),
                     27.35,SHARES)


if __name__=="__main__":unittest.main()
