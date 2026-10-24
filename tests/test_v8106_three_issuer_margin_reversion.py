"""Pure regression assertions for cyclic GM stress: no hindsight/A+."""
import copy
import json
import unittest

from scripts.v8106_three_issuer_margin_reversion import EVIDENCE, PRIORITY, GATE, prepare


def fixtures():
    return (
        json.loads(EVIDENCE.read_bytes()),
        json.loads(PRIORITY.read_bytes()),
        json.loads(GATE.read_bytes())
    )


def scenario(company, name):
    return next(r for r in company["tested_margin_scenarios"] if r["scenario"]==name)


class MarginReversionRiskTests(unittest.TestCase):
    def test_three_real_source_anchored_comparatives(self):
        out=prepare(*fixtures())
        self.assertEqual(out["evaluated_issuers"],["2027","4771","6206"])
        self.assertFalse(out["all_13_formal_quality_gates_completed"])
        self.assertFalse(out["model_2027_base_eps_or_PE_overwritten"])
        self.assertIsNone(out["realized_2027_return_vs_0050"])
        self.assertEqual(out["formal_Aplus_additions"],0)
        self.assertEqual(out["orders_placed"],0)
        self.assertEqual(out["issuers"]["2027"]["actual_2025q2_margin_pct_from_dated_public_reprint"],24.35)
        self.assertEqual(out["issuers"]["2027"]["actual_2026q2_margin_pct_from_dated_public_release"],30.49)
        self.assertEqual(out["issuers"]["4771"]["actual_2025q2_margin_pct_from_dated_public_reprint"],40.77)
        self.assertEqual(out["issuers"]["6206"]["actual_2026q2_margin_pct_from_dated_public_release"],45.4)

    def test_2027_dacheng_steel_base_plus47_disappears_on_old_margin(self):
        company=prepare(*fixtures())["issuers"]["2027"]
        base=scenario(company,"MODELED_2027_BASE_MARGIN")
        old=scenario(company,"HISTORIC_2025_Q2_MARGIN_NOT_2027_FORECAST")
        older=scenario(company,"HISTORIC_2025_H1_MARGIN_NOT_2027_FORECAST")
        self.assertAlmostEqual(base["hypothetical_upside_at_original_PE_pct"],47.65,delta=.02)
        self.assertGreater(old["hypothetical_upside_at_original_PE_pct"],0)
        self.assertLess(old["hypothetical_upside_at_original_PE_pct"],15)
        self.assertLess(old["hypothetical_upside_at_PE_20pct_discount_pct"],0)
        self.assertLess(older["hypothetical_upside_at_original_PE_pct"],old["hypothetical_upside_at_original_PE_pct"])
        self.assertFalse(old["issuer_2027_margin_forecast_certified"])
        self.assertGreater(company["gm_2027_required_for_30pct_upside_with_existing_PE_pct"],24.35)
        self.assertLess(company["gm_2027_required_for_30pct_upside_with_existing_PE_pct"],28.86)

    def test_2027_dacheng_inventory_receivables_expansion_is_review_not_fail(self):
        company=prepare(*fixtures())["issuers"]["2027"]
        metrics=company["balance_sheet_risk_metrics"]
        self.assertGreater(metrics["inventory_yoy_pct"],10)
        self.assertGreater(metrics["accounts_receivable_yoy_pct"],30)
        self.assertGreater(metrics["noncurrent_ppe_yoy_pct"],35)
        self.assertLess(metrics["inventory_qoq_pct"],0)
        self.assertGreater(company["latest_halfyear_ocf_k_normalized_not_filing_original"],0)
        self.assertFalse(company["ocf_sustainability_verified"])

    def test_6206_inventory_receivables_and_cash_quality_warning(self):
        company=prepare(*fixtures())["issuers"]["6206"]
        m=company["balance_sheet_risk_metrics"]
        self.assertGreater(m["inventory_yoy_pct"],90)
        self.assertGreater(m["accounts_receivable_yoy_pct"],30)
        self.assertLess(company["latest_halfyear_ocf_k_normalized_not_filing_original"],0)
        self.assertFalse(company["formal_Aplus_or_buy_signal"])

    def test_4771_positive_ocf_does_not_prove_valuation(self):
        company=prepare(*fixtures())["issuers"]["4771"]
        old=scenario(company,"HISTORIC_2025_Q2_MARGIN_NOT_2027_FORECAST")
        self.assertLess(old["hypothetical_upside_at_original_PE_pct"],41)
        self.assertGreater(company["latest_halfyear_ocf_k_normalized_not_filing_original"],0)
        self.assertFalse(company["ocf_sustainability_verified"])
        r=company["balance_sheet_risk_metrics"]
        self.assertGreater(r["accounts_receivable_yoy_pct"],58)
        self.assertGreater(r["inventory_yoy_pct"],30)
        self.assertGreater(r["noncurrent_ppe_yoy_pct"],49)
        self.assertTrue(r["receivable_growth_exceeds_Q2_revenue_growth"])
        self.assertTrue(r["PPE_yearly_growth_exceeds_40_pct"])

    def test_bogus_current_gross_margin_disagreement_is_blocked(self):
        data,p,g=fixtures()
        data["cases"]["2027"]["observation_2026q2"]["gm_pct"]=24.3
        with self.assertRaisesRegex(ValueError,"MOST_RECENT_ORIGINAL_GM_DIFFERS"):
            prepare(data,p,g)

    def test_reported_gross_profit_arithmetic_is_checked(self):
        data,p,g=fixtures()
        data["cases"]["4771"]["observation_2026q2"]["gross_profit_k"]=300000
        with self.assertRaisesRegex(ValueError,"PUBLIC_QUARTER_INCOME_STATEMENT_ARITHMETIC_MISMATCH"):
            prepare(data,p,g)

    def test_cashflow_source_disagreement_fails_closed(self):
        data,p,g=fixtures()
        data["cases"]["6206"]["cashflow_residual_review"]["normalized_2026h1_ocf_k"]=+97618
        with self.assertRaisesRegex(ValueError,"QUARTER_YTD_OCF_NOT_RECONCILED"):
            prepare(data,p,g)

    def test_source_historical_mops_original_not_fake_certified(self):
        data,p,g=fixtures()
        data["cases"]["2027"]["observation_2025q2"]["source_original_pdf_verified"]=True
        with self.assertRaisesRegex(ValueError,"ORIGINAL_REPORT_CERTIFICATION_MISSTATED"):
            prepare(data,p,g)

    def test_original_bbb_eps_and_multiples_not_mutated(self):
        data,p,g=fixtures()
        old=copy.deepcopy(p)
        result=prepare(data,p,g)
        self.assertEqual(old,p)
        self.assertAlmostEqual(result["issuers"]["2027"]["2027_base_eps_unverified"],6.866620,places=4)
        self.assertEqual(result["issuers"]["2027"]["formal_Aplus_or_buy_signal"],False)

    def test_formal_gate_or_future_reference_cannot_pass(self):
        data,p,g=fixtures()
        g["formally_certified_Aplus_in_report"]=1
        with self.assertRaisesRegex(ValueError,"MODEL_PRICE_OR_A_PLUS_VINTAGE_MISMATCH"):
            prepare(data,p,g)
        data,p,g=fixtures()
        data["last_price_reference_date"]="2026-10-23"
        with self.assertRaisesRegex(ValueError,"UNTRUSTED_COMPARATIVE_MARGIN_OBSERVATIONS"):
            prepare(data,p,g)


if __name__=="__main__":
    unittest.main()
