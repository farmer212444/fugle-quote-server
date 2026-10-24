import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tw_model_v880.buffett import (
    owner_earnings_from_reviewed_inputs,
    incremental_roic_from_reviewed_annual_inputs,
    owner_earnings_discounted_scenario,
    historical_free_cash_flow_proxy,build,render,
)
from scripts.buffett_owner_review import publish

VINTAGE="2026-10-24T17:28:16+08:00"
PRICE="2026-10-22"


def fixtures():
    def issuer(code):
        return dict(code=code,market="TWSE",name="issuer "+code,formal_Aplus=False,
                    recommendation_blocked=False,financial_period="2026-Q3" if code=="9802" else "2026-Q2",
                    cashflow_financial_period="2026-Q2",
                    base_upside_pct=40.9,
                    valuation_diagnostics=dict(forward_annual_profit_bridge_verified=False),
                    review_work=[dict(gate=str(i),decision="PENDING") for i in range(13)])
    main=dict(schema="V810_INSTITUTIONAL_RESEARCH_CONTROLS",
              model="V8.10.8",estimate_vintage=VINTAGE,asof_price_date=PRICE,
              formal_Aplus_count=0,issuer_reviews=[issuer("6206"),issuer("9802")])
    cash=dict(model="V8.10.8",estimate_vintage=VINTAGE,price_date=PRICE,
              code="9802",income_period="2026-Q3",cashflow_period="2026-Q2",
              research_only=True,changes_eps_or_target_price=False,
              grants_quality_certification=False,
              original_cash_review=dict(code="9802",period="2026-Q2",
                  status="ORIGINAL_9802_H1_CASH_AND_WC_ARITHMETIC_RECONCILED_NOT_FULL_CASH_GATE",
                  current_h1=dict(year=2026,days_in_h1=181),
                  prior_h1=dict(year=2025,days_in_h1=181),
                  formal_cash_and_working_capital_gate_pass=False,
                  reviewed_at="2026-10-24T07:00:00+00:00",
                  cashflow_signed_k=dict(ocf=[-274010,-287575],
                                         ppe=[-608517,-1154071],
                                         dividends_paid=[-401983,-380660]),
                  original_sources=[]))
    return main,cash


class BuffettMath(unittest.TestCase):
    def test_owner_earnings_is_net_profit_based_not_double_count_ocf(self):
        self.assertEqual(owner_earnings_from_reviewed_inputs(
            parent_net_profit=1000,depreciation=200,amortization=50,
            maintenance_capex=100,incremental_sustaining_working_capital=100),1050)
        with self.assertRaisesRegex(ValueError,"INVALID_MAINTENANCE_CAPEX"):
            owner_earnings_from_reviewed_inputs(
                parent_net_profit=1000,depreciation=20,amortization=10,
                maintenance_capex=-10,incremental_sustaining_working_capital=10)
        with self.assertRaisesRegex(ValueError,"INVALID"):
            owner_earnings_from_reviewed_inputs(
                parent_net_profit=True,depreciation=20,amortization=10,
                maintenance_capex=10,incremental_sustaining_working_capital=10)

    def test_incremental_roic_requires_positive_additional_capital(self):
        self.assertAlmostEqual(incremental_roic_from_reviewed_annual_inputs(
            prior_annual_nopat=100,current_annual_nopat=120,
            prior_invested_capital=1000,current_invested_capital=1200),0.1)
        with self.assertRaisesRegex(ValueError,"NONPOSITIVE"):
            incremental_roic_from_reviewed_annual_inputs(
                prior_annual_nopat=100,current_annual_nopat=120,
                prior_invested_capital=1200,current_invested_capital=1000)

    def test_long_term_requires_explicit_3_to_5_years_and_sensible_terminal(self):
        result=owner_earnings_discounted_scenario(
            annual_owner_earnings=[100,110,120],required_return=.10,
            terminal_growth=.02,diluted_shares=100)
        self.assertGreater(result["per_share_value"],10)
        with self.assertRaisesRegex(ValueError,"THREE_TO_FIVE"):
            owner_earnings_discounted_scenario(
                annual_owner_earnings=[100],required_return=.10,
                terminal_growth=.02,diluted_shares=100)
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_TERMINAL"):
            owner_earnings_discounted_scenario(
                annual_owner_earnings=[100,110,120],required_return=.10,
                terminal_growth=.11,diluted_shares=100)

    def test_fcf_proxy_is_not_owner_earnings_and_no_future_extrapolation(self):
        _,cash=fixtures()
        historical=historical_free_cash_flow_proxy(cash["original_cash_review"])
        self.assertEqual(historical["years"][0]["fcf_after_all_ppe_k"],-882527.)
        self.assertEqual(historical["years"][1]["fcf_after_all_ppe_k"],-1441646.)
        self.assertIsNone(historical["years"][0]["owner_earnings_k"])
        self.assertTrue(historical["historical_periods_do_not_predict_future_fcf"])


class BuffettResearch(unittest.TestCase):
    def test_readonly_and_no_false_moat_roic_or_owner_earnings(self):
        a,b=fixtures()
        olda,oldb=copy.deepcopy(a),copy.deepcopy(b)
        result=build(a,b)
        self.assertEqual((a,b),(olda,oldb))
        self.assertEqual(result["institutional_issuer_count"],2)
        self.assertEqual(result["verified_owner_earnings_count"],0)
        self.assertEqual(result["verified_incremental_roic_count"],0)
        self.assertEqual(result["new_certifications_issued"],0)
        self.assertTrue(result["original_13_gates_unchanged"])
        r=next(x for x in result["issuer_reviews"] if x["code"]=="9802")
        self.assertIsNone(r["three_to_five_year_owner_value"]["per_share_value"])
        self.assertIsNone(r["owner_earnings"]["amount_k"])
        self.assertEqual(r["owner_earnings"]["historical_fcf_proxy"]["years"][0]["fcf_after_all_ppe_k"],-882527)
        self.assertIn("2026H1",render(result))
        self.assertIn("-8.83",render(result))

    def test_vintage_and_issuer_match_required(self):
        a,b=fixtures()
        b["price_date"]="2026-10-21"
        with self.assertRaisesRegex(ValueError,"CASH_VINTAGE"):build(a,b)
        a,b=fixtures()
        a["issuer_reviews"][1]["financial_period"]="2026-Q2"
        with self.assertRaisesRegex(ValueError,"PERIOD_IDENTITY"):build(a,b)
        a,b=fixtures()
        a["issuer_reviews"][0]["formal_Aplus"]=True
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_FORMAL_A_PLUS"):build(a,b)

    def test_publisher_rechecks_two_actual_source_hashes(self):
        a,b=fixtures()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            ranks=root/"tw-market-data/rankings"
            ranks.mkdir(parents=True)
            sources=[]
            for year in (2025,2026):
                raw=b"%PDF-1.4\n%synthetic"+str(year).encode()
                path="evidence/v880/originals/9802/"+str(year)+"_test.pdf"
                file=root/"tw-market-data"/path
                file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(raw)
                sources.append(dict(period=f"{year}-Q2",archive_path=path,
                                    captured_at_utc="2026-10-22T12:00:00+00:00",
                                    sha256=hashlib.sha256(raw).hexdigest()))
            b["original_cash_review"]["original_sources"]=sources
            (root/"VERSION").write_text(a["model"])
            (ranks/"latest_institutional.json").write_text(json.dumps(a))
            (ranks/"latest_9802_cash_review.json").write_text(json.dumps(b))
            report=publish(root)
            self.assertEqual(len(report["checked_original_pdfs"]),2)
            self.assertEqual(report["new_certifications_issued"],0)
            self.assertTrue((ranks/"latest_buffett_review.md").exists())
            self.assertIn("price_scenario_upside_pct",json.loads((ranks/"latest_buffett_review.json").read_text())["issuer_reviews"][0])
            file.write_bytes(b"%PDF-tampered")
            quarantined=publish(root)
            self.assertEqual(len(quarantined["source_rejections"]),1)
            self.assertIn("PDF_HASH_MISMATCH",quarantined["source_rejections"][0]["reason"])
            self.assertEqual(quarantined["issuer_cash_original_case_count"],0)
            self.assertEqual(quarantined["checked_original_pdfs"],[])
            self.assertIsNone(next(x for x in quarantined["issuer_reviews"] if x["code"]=="9802")["owner_earnings"]["amount_k"])
            self.assertEqual(quarantined["institutional_issuer_count"],2)
            self.assertEqual(quarantined["new_certifications_issued"],0)
            self.assertIn("原始檔案被隔離",render(quarantined))


if __name__=="__main__":
    unittest.main()
