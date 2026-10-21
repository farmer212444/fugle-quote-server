"""V8.9.10 9802 issuer-slide material/labor/overhead reproducibility guards."""
import copy
import json
from pathlib import Path
import unittest

from tw_model_v880.disclosed_cogs import assess_disclosed_cogs, render_disclosed_cogs
from scripts.v899_factory_ramp_audit import standalone

ROOT=Path(__file__).resolve().parents[1]
RECEIPT=ROOT/"tw-market-data"/"evidence"/"v880"/"factory_ramp"/"9802_disclosed_cogs.json"
ASOF="2026-10-21T20:00:00+08:00"


def receipt():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def official_mirrors():
    # Company slide values rounded to NT$ millions, compared against TWSE
    # consolidated YTD quarter subtraction (Q2 minus Q1) to the nearest NT$2m.
    return {
        "2025-Q2":{"revenue_twd":5232374000,"gross_profit_twd":967677000},
        "2026-Q2":{"revenue_twd":5258501000,"gross_profit_twd":732887000},
    }


class IssuerDisclosedCogsTests(unittest.TestCase):
    def test_frozen_issuer_original_pdf_checksum_and_periods(self):
        e=receipt()
        self.assertEqual(e["source"]["original_pdf_sha256"],
            "44973cb7cbfabd9d601271647eecf5391f01d56ff1c62030870aebcdd9726a3b")
        self.assertEqual((e["source"]["source_page_pdf_one_indexed"],
                          e["source"]["source_page_printed"]),(20,23))
        self.assertFalse(e["source"]["in_repository_original_pdf_archived"])
        self.assertEqual(set(e["figures"]),{"2025-Q2","2026-Q2"})

    def test_issuer_factors_reconcile_to_financial_statement(self):
        d=assess_disclosed_cogs(receipt(),asof=ASOF,
                                standardized_accounting=official_mirrors())
        self.assertEqual(d["status"],"PUBLISHED_CONSOLIDATED_COGS_SPLIT_NOT_PLANT_CAUSALITY")
        self.assertTrue(d["reconciled_to_standardized_q2_accounting"])
        b=d["burdens"]
        self.assertAlmostEqual(b["direct_materials_million"]["burden_change_pp"],2.304,delta=.02)
        self.assertAlmostEqual(b["direct_labor_million"]["burden_change_pp"],2.949,delta=.02)
        self.assertAlmostEqual(b["manufacturing_overhead_million"]["burden_change_pp"],-.674,delta=.02)
        self.assertAlmostEqual(d["displayed_gross_margin_change_pp"],-4.58,delta=.05)
        self.assertAlmostEqual(d["materials_plus_labor_gm_effect_pp"],-5.25,delta=.05)
        self.assertAlmostEqual(d["manufacturing_overhead_gm_effect_pp"],+.67,delta=.05)
        self.assertFalse(d["base_gm_override_allowed"])
        self.assertFalse(d["formal_a_plus_changed"])
        self.assertFalse(d["model_eps_pe_target_changed"])

    def test_manufacturing_overhead_is_mixed_not_equivalent_to_depreciation(self):
        d=assess_disclosed_cogs(receipt(),asof=ASOF)
        self.assertTrue(d["overhead_contains_mixed_fixed_and_variable_costs"])
        self.assertTrue(d["direct_labor_contains_possible_new_factory_training"])
        for key in ("factory_yield_actual_verified","factory_utilization_actual_verified",
                    "segment_asp_and_product_mix_verified",
                    "wage_and_learning_driver_split_verified",
                    "plant_ramp_causally_proven","recovery_time_estimated"):
            self.assertFalse(d[key],key)

    def test_reject_future_date_to_stop_hindsight(self):
        with self.assertRaisesRegex(ValueError,"NOT_YET_PUBLIC"):
            assess_disclosed_cogs(receipt(),asof="2026-09-16T23:00:00+08:00")

    def test_reject_unzoned_research_timestamp(self):
        with self.assertRaisesRegex(ValueError,"TIMEZONE"):
            assess_disclosed_cogs(receipt(),asof="2026-10-21T20:00:00")

    def test_issuer_identity_required(self):
        e=receipt()
        e["issuer"]="2330"
        with self.assertRaisesRegex(ValueError,"ISSUER_ID"):
            assess_disclosed_cogs(e,asof=ASOF)

    def test_reject_noncompany_domain_and_invalid_hash(self):
        e=receipt()
        e["source"]["issuer_publication_url"]="https://attacker.invalid/9802.pdf"
        with self.assertRaisesRegex(ValueError,"SOURCE_NOT_ISSUER"):
            assess_disclosed_cogs(e,asof=ASOF)
        e=receipt();e["source"]["original_pdf_sha256"]="x"*64
        with self.assertRaisesRegex(ValueError,"PDF_HASH"):
            assess_disclosed_cogs(e,asof=ASOF)

    def test_cannot_claim_full_pdf_original_in_git_when_absent(self):
        e=receipt();e["source"]["in_repository_original_pdf_archived"]=True
        with self.assertRaisesRegex(ValueError,"REPOSITORY_STATUS"):
            assess_disclosed_cogs(e,asof=ASOF)

    def test_raw_pdf_not_available_means_no_full_ci_pdf_replay(self):
        d=assess_disclosed_cogs(receipt(),asof=ASOF)
        self.assertTrue(d["source_pdf_verified_in_analysis"])
        self.assertFalse(d["original_pdf_archived_in_repository"])

    def test_missing_or_tampered_material_labor_mfg_data_refused(self):
        e=receipt();e["figures"]["2026-Q2"]["direct_materials_million"]=2020
        with self.assertRaisesRegex(ValueError,"GROSS_RECONCILIATION"):
            assess_disclosed_cogs(e,asof=ASOF)

    def test_non_numeric_and_boolean_fields_refused(self):
        for bad in (None,"2515",True,float("nan"),-5):
            with self.subTest(bad=bad):
                e=receipt();e["figures"]["2026-Q2"]["direct_materials_million"]=bad
                with self.assertRaises(ValueError):
                    assess_disclosed_cogs(e,asof=ASOF)

    def test_rounded_reconciliation_with_tolerance_but_not_wrong_company(self):
        out=assess_disclosed_cogs(receipt(),asof=ASOF,standardized_accounting=official_mirrors())
        self.assertTrue(out["reconciled_to_standardized_q2_accounting"])
        m=official_mirrors();m["2026-Q2"]["gross_profit_twd"]=680000000
        with self.assertRaisesRegex(ValueError,"ACCOUNTING_MISMATCH"):
            assess_disclosed_cogs(receipt(),asof=ASOF,standardized_accounting=m)

    def test_wrong_quarter_rejected(self):
        e=receipt();e["figures"]["2025-Q1"]=e["figures"].pop("2025-Q2")
        with self.assertRaisesRegex(ValueError,"PERIODS_INCOMPLETE"):
            assess_disclosed_cogs(e,asof=ASOF)

    def test_printed_report_warns_against_misreading_production_output(self):
        report=render_disclosed_cogs(assess_disclosed_cogs(receipt(),asof=ASOF))
        self.assertIn("不是各廠可用產能",report)
        self.assertIn("製造費用",report)
        self.assertIn("人工",report)
        self.assertIn("SHA256",report)
        self.assertIn("不提高2027 Base",report)

    def test_standalone_quarter_matches_frozen_official_figures(self):
        d=ROOT/"tw-market-data"/"fundamentals"
        for y in (2025,2026):
            p1=json.loads((d/f"{y}-Q1"/"TWSE_income.json").read_text())
            p2=json.loads((d/f"{y}-Q2"/"TWSE_income.json").read_text())
            r1=next(r for r in p1["rows"] if r["code"]=="9802")
            r2=next(r for r in p2["rows"] if r["code"]=="9802")
            q2=standalone(r1,r2)
            expected=official_mirrors()[f"{y}-Q2"]
            self.assertEqual(q2["revenue_twd"],expected["revenue_twd"])
            self.assertEqual(q2["gross_profit_twd"],expected["gross_profit_twd"])


if __name__=="__main__":
    unittest.main()
