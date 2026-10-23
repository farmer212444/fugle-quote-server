"""Contracts for source-first cross-sector 2027 candidate triage, not a backtest."""
import copy
import json
import unittest
from pathlib import Path

from scripts.v8106_cross_sector_2027_shadow import build


def inputs():
    folder=Path("tw-market-data/rankings")
    return (
        json.loads((folder/"latest_evidence_priority.json").read_bytes()),
        json.loads((folder/"v891_gate_progress.json").read_bytes()),
        json.loads((folder/"v892_top20_quality_audit.json").read_bytes())
    )


class V8106CrossSectorTests(unittest.TestCase):
    def test_original_reconciled_top10_has_zero_formal_picks(self):
        res=build(*inputs())
        self.assertEqual(res["evaluated_issuers"],1347)
        self.assertEqual(res["unverified_remaining_issuers"],654)
        self.assertEqual(res["provisional_2027_upside_ge30_count_in_evaluated_pool"],127)
        self.assertEqual(res["formally_certified_Aplus_count"],0)
        self.assertEqual(res["base_upside_ge30_in_original_current_reconciled_top10_count"],10)
        self.assertEqual(res["stress_upside_ge30_in_original_current_reconciled_top10_count"],0)
        self.assertIsNone(res["observed_real_out_of_sample_win_rate_vs_0050"])
        self.assertEqual(res["orders_placed"],0)
        self.assertFalse(res["model_changed"])

    def test_risk_lanes_honest(self):
        res=build(*inputs())
        rows={x["research_code"]:x for x in res["research_candidates_source_order"]}
        self.assertEqual(rows["2027"]["research_quality_lane"],"SOURCE_RECONCILED_NEXT_EARNINGS_QUALITY_REVIEW")
        self.assertEqual(rows["3130"]["research_quality_lane"],"SOURCE_RECONCILED_NEXT_EARNINGS_QUALITY_REVIEW")
        self.assertEqual(rows["6206"]["research_quality_lane"],
                         "CHECK_FINANCIAL_AND_REVENUE_ORIGINALS_BEFORE_ANY_RISK_DECISION")
        self.assertIn("UNRESOLVED_NEGATIVE_OPERATING_CASHFLOW",rows["6206"]["high_risk_review_flags"])
        self.assertIn("LATEST_MONTH_SALES_REVERSAL",rows["6143"]["high_risk_review_flags"])
        self.assertIn("AUDITOR_SUBSIDIARY_SCOPE_REVIEW",rows["8383"]["high_risk_review_flags"])
        self.assertEqual(rows["2027"]["formal_pending_gates"],13)
        self.assertFalse(any(z["eligible_for_one_stock_10m_concentration"] for z in rows.values()))

    def test_3130_company_disclosed_cyber_incident_blocks_clean_risk_tier(self):
        result=build(*inputs())
        rows={x["research_code"]:x for x in result["research_candidates_source_order"]}
        item=rows["3130"]
        self.assertEqual(item["dated_public_material_event_id"],"3130_CYBER_RESUME_DISCLOSURE_20261006")
        self.assertEqual(item["dated_public_material_event_date"],"2026-10-06")
        self.assertIn("CYBERSECURITY_PERSONAL_DATA_INCIDENT_IMPACT_OPEN",item["high_risk_review_flags"])
        self.assertEqual(item["research_quality_lane"],
                         "CHECK_FINANCIAL_AND_REVENUE_ORIGINALS_BEFORE_ANY_RISK_DECISION")
        self.assertFalse(item["material_event_original_company_mops_attested"])
        self.assertEqual(result["known_public_material_events_included"],1)
        self.assertFalse(item["formal_Aplus"])

    def test_missing_3130_known_risk_cannot_silently_restore_clean_tier(self):
        p,g,b=inputs()
        path=Path("tw-market-data/evidence/v8106_cross_sector_public_events_20261024.json")
        events=json.loads(path.read_bytes())
        events["events"]=[]
        with self.assertRaisesRegex(ValueError,"MISSING_KNOWN_3130_CYBER_RISK_EVENT"):
            build(p,g,b,events)

    def test_event_source_cannot_be_mislabeled_official_original(self):
        p,g,b=inputs()
        events=json.loads(Path("tw-market-data/evidence/v8106_cross_sector_public_events_20261024.json").read_bytes())
        events["events"][0]["official_company_original_bytes_sha256"]="a"*64
        with self.assertRaisesRegex(ValueError,"MATERIAL_EVENT_SOURCE_OR_LEGAL_STATUS_MISREPRESENTED"):
            build(p,g,b,events)

    def test_downside_eps_pe_stress_is_not_base(self):
        res=build(*inputs())
        rows={x["research_code"]:x for x in res["research_candidates_source_order"]}
        self.assertAlmostEqual(rows["2027"]["model_base_upside_pct_unverified"],47.65,places=1)
        self.assertAlmostEqual(rows["2027"]["model_eps_and_pe_both_minus20_upside_pct"],-5.51,places=1)
        self.assertAlmostEqual(rows["6206"]["model_base_upside_pct_unverified"],40.93,places=1)
        self.assertAlmostEqual(rows["6206"]["model_eps_and_pe_both_minus20_upside_pct"],-9.80,places=1)

    def test_high_computed_returns_are_not_certified(self):
        res=build(*inputs())
        bulk={x["code"]:x for x in res["high_upside_but_originals_unverified_examples"]}
        self.assertIn("6494",bulk)
        self.assertIn("1785",bulk)
        self.assertEqual(bulk["6494"]["source_lane"],"HIGH_UPSIDE_BULK_SOURCE_UNVERIFIED_NOT_BUY")
        self.assertFalse(bulk["6494"]["formal_Aplus"])

    def test_frozen_source_reference_dates_failing_cannot_promote(self):
        p,g,b=inputs()
        g["asof_price_date"]="2026-10-23"
        with self.assertRaisesRegex(ValueError,"GATE_VINTAGE"):
            build(p,g,b)
        p,g,b=inputs()
        b["asof_price_date"]="2026-10-21"
        with self.assertRaisesRegex(ValueError,"BROAD_UNIVERSE"):
            build(p,g,b)

    def test_model_certification_must_be_zero(self):
        p,g,b=inputs()
        g["formally_certified_Aplus_in_report"]=1
        with self.assertRaisesRegex(ValueError,"GATE_VINTAGE_OR_FORMAL_GRADE"):
            build(p,g,b)

    def test_all_eight_originals_cannot_be_faked(self):
        p,g,b=inputs()
        p["top10_evidence_first"][0]["all_eight_quarters_and_notes_verified"]=True
        with self.assertRaisesRegex(ValueError,"MISLABELED_FULL_EIGHT"):
            build(p,g,b)

    def test_valuation_bridge_arithmetic_detects_deception(self):
        p,g,b=inputs()
        p["top10_evidence_first"][0]["base_target_price"]*=2
        with self.assertRaisesRegex(ValueError,"UPSIDE_EPS_PRICE_BRIDGE"):
            build(p,g,b)

    def test_unreviewed_offering_rejected(self):
        p,g,b=inputs()
        p["top10_evidence_first"][0]["pending_offering"]=True
        with self.assertRaisesRegex(ValueError,"EQUITY_OFFERING"):
            build(p,g,b)

    def test_no_stress_promotion_from_unverified_bulk_names(self):
        p,g,b=inputs()
        b["issuer_ranked"][0]["stress_double20_upside_pct"]=1000
        res=build(p,g,b)
        entry=next(x for x in res["high_upside_but_originals_unverified_examples"] if x["code"]=="6494")
        self.assertFalse(entry["formal_Aplus"])
        self.assertIsNone(res["observed_real_out_of_sample_win_rate_vs_0050"])


if __name__=="__main__":
    unittest.main()
