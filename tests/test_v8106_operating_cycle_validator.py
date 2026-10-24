"""Turnover-days data model tests: trend direction, not file-verified A+."""
import copy
import json
import unittest

from scripts.v8106_operating_cycle_validator import INPUT, MARGINS, evaluate


def inputs():
    return json.loads(INPUT.read_bytes()),json.loads(MARGINS.read_bytes())


class V8106TurnoverDays(unittest.TestCase):
    def test_4771_both_sources_agree_on_direction_not_absolute_days(self):
        out=evaluate(*inputs())
        r=out["issuers"]["4771"]
        sources=r["published_turnover_sources"]
        company=sources["4771_company_deck_transcription"]["metrics"]
        vendor=sources["4771_financial_ratio_vendor"]["metrics"]
        self.assertEqual(company["dso"]["yoy_days"],8)
        self.assertEqual(company["dso"]["qoq_days"],-1)
        self.assertAlmostEqual(vendor["dso"]["yoy_days"],7.15,places=2)
        self.assertAlmostEqual(vendor["dso"]["qoq_days"],-4.46,places=2)
        self.assertAlmostEqual(vendor["ccc"]["yoy_days"],3.78,places=2)
        self.assertAlmostEqual(vendor["ccc"]["qoq_days"],-7.18,places=2)
        self.assertEqual(company["dio"]["yoy_days"],0)
        self.assertAlmostEqual(vendor["dio"]["yoy_days"],.03,places=2)
        self.assertTrue(r["cross_source_day_levels_not_directly_equal"])
        self.assertTrue(r["yoy_AR_grows_faster_than_quarter_revenue"])
        self.assertFalse(r["bad_debt_loss_or_inventory_impairment_concluded"])

    def test_6206_flytech_collection_improves_inventory_slows(self):
        out=evaluate(*inputs())
        r=out["issuers"]["6206"]
        d=r["published_turnover_sources"]["6206_company_deck_transcription"]["metrics"]
        self.assertEqual(d["dso"]["yoy_days"],-11)
        self.assertEqual(d["dso"]["qoq_days"],3)
        self.assertEqual(d["dio"]["yoy_days"],34)
        self.assertEqual(d["dio"]["qoq_days"],-3)
        self.assertIsNone(d["ccc"])
        self.assertIsNone(d["dpo"])
        self.assertLess(r["end_q2_accounts_receivable_yoy_pct"],r["sales_2026q2_revenue_yoy_pct"])
        self.assertGreater(r["end_q2_inventory_yoy_pct"],r["q2_cogs_yoy_pct"]+50)
        self.assertLess(r["cashflow_h1_k_normalized_unverified_original"],0)
        self.assertFalse(r["yoy_AR_grows_faster_than_quarter_revenue"])
        self.assertFalse(r["issuer_original_annual_report_PIT_verified"])

    def test_both_sources_honest_pit_and_13_gates(self):
        r=evaluate(*inputs())
        self.assertFalse(r["primary_official_reports_full_original_sha_archived"])
        self.assertTrue(r["no_definitive_impairment_or_misconduct_claim"])
        self.assertEqual(r["formal_Aplus_count_changed"],0)
        self.assertIsNone(r["actual_one_year_total_return_vs_0050"])
        self.assertEqual(r["orders_placed"],0)

    def test_vendor_dso_cannot_substitute_company_metric_without_method(self):
        p,m=inputs()
        p["issuers"]["4771"]["sources"][0]["dso_2026q2"]=76.69
        with self.assertRaisesRegex(ValueError,"EXPECTED_DIFFERENT_METHODS_NOT_PRESERVED"):
            evaluate(p,m)

    def test_4771_dso_yoy_cannot_fake_improvement(self):
        p,m=inputs()
        p["issuers"]["4771"]["sources"][1]["dso_2025q2"]=80
        p["issuers"]["4771"]["sources"][1]["ccc_2025q2"]=96.33
        with self.assertRaisesRegex(ValueError,"CROSS_METHOD_COLLECTION_CYCLE_DIRECTION_INCONSISTENT"):
            evaluate(p,m)

    def test_6206_dio_plus34_must_not_be_silently_erased(self):
        p,m=inputs()
        p["issuers"]["6206"]["sources"][0]["dio_2026q2"]=88
        with self.assertRaisesRegex(ValueError,"FLYTECH_COLLECTION_OR_INVENTORY_TREND_INCONSISTENT"):
            evaluate(p,m)

    def test_6206_2026q2_bare_receivable_wrong_source(self):
        p,m=inputs()
        p["issuers"]["6206"]["ar_2026q2_m"]*=2
        with self.assertRaisesRegex(ValueError,"A_R_IS_NOT_PRIOR_ARCHIVED_DATA"):
            evaluate(p,m)

    def test_company_financial_statement_margin_reconciles(self):
        p,m=inputs()
        p["issuers"]["4771"]["cogs_2026q2_k"]=750000
        with self.assertRaisesRegex(ValueError,"GROSS_MARGIN_MISMATCH_WITH_ORIGINAL_FINANCIAL_SOURCE"):
            evaluate(p,m)

    def test_vendor_CCC_requires_source_consistency(self):
        p,m=inputs()
        p["issuers"]["4771"]["sources"][1]["ccc_2026q2"]=120
        with self.assertRaisesRegex(ValueError,"REPORTED_CCC_ARITHMETIC"):
            evaluate(p,m)

    def test_reported_OCF_sign_cannot_be_flipped(self):
        p,m=inputs()
        p["issuers"]["6206"]["normalized_2026h1_ocf_k"]=97618
        with self.assertRaisesRegex(ValueError,"OCF_NOT_MATCHING_PRIOR_NORMALIZED_SOURCE"):
            evaluate(p,m)

    def test_source_pdf_hash_must_remain_unverified(self):
        p,m=inputs()
        p["issuers"]["4771"]["sources"][0]["issuer_original_document_sha256"]="a"*64
        with self.assertRaisesRegex(ValueError,"FALSE_ORIGINAL_PDF_ARCHIVE_OR_BAD_RATIO_SOURCE"):
            evaluate(p,m)

    def test_input_not_modified_by_evaluation(self):
        p,m=inputs()
        original=copy.deepcopy(p)
        evaluate(p,m)
        self.assertEqual(p,original)

    def test_wrong_source_period_cannot_pass(self):
        p,m=inputs()
        p["observation_end"]="2026-09-30"
        with self.assertRaisesRegex(ValueError,"WRONG_SOURCE_VINTAGE_OR_UNIVERSE"):
            evaluate(p,m)


if __name__=="__main__":
    unittest.main()
