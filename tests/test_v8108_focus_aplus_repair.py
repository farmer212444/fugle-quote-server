"""No fictitious A+ PASS from 6206 PDF bytes or hypothetical 9802 margins."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v8108_focus_aplus_repair import (
    build,cost_bridge,full_6206_starter,gm_hurdle,markdown,publish)
from tw_model_v880.evidence import GATES

STAMP="2026-11-10T09:16:28.134918+08:00"
DATE="2026-11-09"

def put(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")

def fixture(root):
    payload=b"%PDF-1.4 pretend test bytes only"
    rel="evidence/v880/originals/6206/presentation.pdf"
    path=root/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
    doc=dict(issuer="6206",schema="V896_DURABLE_ORIGINAL_PDF_NOT_CERTIFIED",
             documents=[dict(issuer="6206",document_kind="presentation",
                archive_path=rel,document_date="2026-08-12",
                source_url="https://www.flytech.com.tw/presentation.pdf",
                sha256=hashlib.sha256(payload).hexdigest(),captured_at_utc="2026-10-01T00:00:00Z")])
    put(root/"evidence/v880/originals/6206/manifest.json",doc)
    triage=dict(issuer="6206",price_date=DATE,estimate_vintage=STAMP,
                gates=[dict(gate=g,formal_status="PENDING",
                            automatically_certified=False,
                            next_action="需要逐季核對",source_coverage="OBSERVED_PARTIAL")
                       for g in GATES])
    put(root/"rankings/v891_6206_gate_triage.json",triage)
    focus=[]
    for code in ("6206","9802"):
        focus.append(dict(code=code,company_gates_pending=12,
                          company_gates_passed=0,
                          formal_Aplus=False,
                          valuation_period="2026-Q2" if code=="6206" else "2026-Q3",
                          reviewed_period="2026-Q2",
                          strategy_validation_lane="STRATEGY_PIT_OOS_PENDING",
                          price_lane="A_PLUS_PRICE_CANDIDATE_UNVERIFIED" if code=="6206"
                                else "PRICE_HURDLE_NOT_MET",
                          research_upside_pct=53.58 if code=="6206" else -16.37))
    put(root/"rankings/latest_aplus_decision_lanes.json",
        dict(model="V8.10.8",asof_price_date=DATE,estimate_vintage=STAMP,issuers=focus))
    # The core forecast is mathematically internally consistent.
    gross=10000000*0.15
    costs=10000000*0.09
    nonop=0
    pretax=gross-costs+nonop
    net=pretax*.75
    shares=100_000_000
    eps=net*1000/shares
    main=dict(revenue_k=10000000,gross_margin=.15,
              gross_profit_k=gross,opex_ratio=.09,opex_k=costs,
              operating_profit_k=pretax,nonoperating_k=nonop,
              pretax_k=pretax,tax_rate=.25,parent_fraction=1,
              parent_profit_k=net,shares=shares,eps=eps,pe=12,
              target_price=eps*12)
    put(root/"rankings/v886_9802_early_q3.json",
        dict(code="9802",quarter="2026-Q3",
             estimate_vintage=STAMP,
             status="MAIN_RESEARCH_REBASED_ON_ISSUER_SELF_REPORT",
             new=main))
    put(root/"rankings/latest_footwear_review.json",
        dict(estimate_vintage=STAMP,asof_price_date=DATE,
             companies=[dict(code="9802",reference_close=63.0,
                 production_base_eps=eps,production_base_price=eps*12)]))
    cogs=dict(issuer="9802",kind="PUBLISHED_GROUP_COST_OF_SALES_COMPOSITION",
        source=dict(in_repository_original_pdf_archived=False,
            issuer_publication_url="https://example.org/company.pdf"),
        figures={"2025-Q2":dict(revenue_million=5232,gross_profit_million=968,
                    direct_materials_million=2382,direct_labor_million=990,
                    manufacturing_overhead_million=892),
                 "2026-Q2":dict(revenue_million=5258,gross_profit_million=732,
                    direct_materials_million=2515,direct_labor_million=1150,
                    manufacturing_overhead_million=861)})
    put(root/"evidence/v880/factory_ramp/9802_disclosed_cogs.json",cogs)
    return rel,main

class CertificationFocusTests(unittest.TestCase):
    def test_6206_receipts_rehashed_without_signoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rel,main=fixture(root)
            a=build(root)
            starter=a["review_starter"]
            self.assertEqual(starter["originals_sha256_checked"],1)
            self.assertEqual(len(starter["gate_review_starter"]),13)
            self.assertEqual(set(starter["gate_review_starter"]),set(GATES))
            self.assertFalse(starter["review_packs_written"])
            self.assertFalse(starter["formal_Aplus"])
            self.assertTrue(all(g["status"]=="PENDING" and g["reviewer_id"] is None
                                and g["review_completed"] is False
                                for g in starter["gate_review_starter"].values()))
            self.assertEqual(starter["gate_review_starter"]["original_eight_quarter_statements"]["sources"],[])
            self.assertEqual(len(starter["gate_review_starter"]["management_promises"]["sources"]),1)
            pub=publish(root)
            self.assertEqual(pub["formal_pass_added"],0)
            self.assertTrue((root/"rankings/latest_focus_aplus_repair.md").exists())
            self.assertFalse((root/"evidence/v880/review_packs/6206.json").exists())
            self.assertIn("18.37",markdown(pub) if pub["second_focus"]["operating_hurdle"]["required_2027_gm_pct_for_30pct"]==18.37 else markdown(pub))

    def test_tampering_original_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rel,_=fixture(root)
            (root/rel).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError,"ORIGINAL_PDF_HASH_MISMATCH"):
                build(root)

    def test_mismatched_vintage_never_combined(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            p=root/"rankings/latest_footwear_review.json"
            d=json.loads(p.read_text());d["estimate_vintage"]="2026-11-09T09:00:00+08:00";put(p,d)
            with self.assertRaisesRegex(ValueError,"INPUT_ESTIMATE_VINTAGE_MISMATCH"):
                build(root)

    def test_cost_bridge_does_not_assume_new_factory_explains_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            c=json.loads((root/"evidence/v880/factory_ramp/9802_disclosed_cogs.json").read_text())
            o=cost_bridge(c)
            self.assertLess(o["contributors"]["direct_materials_million"]["gross_margin_contribution_pp"],0)
            self.assertLess(o["contributors"]["direct_labor_million"]["gross_margin_contribution_pp"],0)
            self.assertGreater(o["contributors"]["manufacturing_overhead_million"]["gross_margin_contribution_pp"],0)
            self.assertFalse(o["plant_level_utilization_verified"])
            self.assertFalse(o["cost_normalization_to_2027_verified"])

    def test_9802_main_model_gm_sensitivity_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,base=fixture(root)
            expected=gm_hurdle(base,63)
            self.assertGreater(expected["required_2027_gm_pct_for_30pct"],expected["base_gross_margin_pct"])
            self.assertEqual(expected["required_2027_eps_for_30pct"],6.825)
            self.assertFalse(expected["required_margin_is_not_forecast_or_quality_PASS"] is False)
            mutated=copy.deepcopy(base);mutated["target_price"]+=20
            with self.assertRaisesRegex(ValueError,"MARGIN_PRICE_NOT_RECONCILED"):
                gm_hurdle(mutated,63)

    def test_9802_pdf_is_not_false_original_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            p=root/"evidence/v880/factory_ramp/9802_disclosed_cogs.json"
            d=json.loads(p.read_text());d["source"]["in_repository_original_pdf_archived"]=True;put(p,d)
            with self.assertRaisesRegex(ValueError,"COST_PDF_PROVENANCE_FLAGS_MISMATCH"):
                build(root)

if __name__=="__main__":
    unittest.main()
