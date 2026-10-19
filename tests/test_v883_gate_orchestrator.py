import unittest
from scripts.v883_gate_orchestrator import ROUTES, build, render_md
from tw_model_v880.evidence import GATES

class EvidenceDispatchTests(unittest.TestCase):
    def fixture(self):
        rows=[
          dict(code="9802",name="鈺齊",market="TWSE",rankable=True,scenario_upside_pct=35,status="CERTIFICATION_PENDING",source_tier="ORIGINAL_CURRENT_ISSUER_NUMERICS"),
          dict(code="9904",name="寶成",market="TWSE",rankable=True,scenario_upside_pct=12,status="CERTIFICATION_PENDING"),
          dict(code="1111",name="未估值",market="TPEX",rankable=False,scenario_upside_pct=None,status="TURNOVER_FILTER_BELOW_1M_TWD")
        ]
        research=dict(model="V8.8.2",estimate_vintage="2026-10-19T17:00:00+08:00",asof_price_date="2026-10-16",
                      data_scope=dict(model_rows=3),all_model_row_summary=rows,formal_Aplus_count=0)
        pending=dict(model="V8.8.2",asof=research["estimate_vintage"],
                     rows=[dict(code="9802",status="CERTIFICATION_PENDING",pending_gates=list(GATES)),
                           dict(code="9904",status="CERTIFICATION_PENDING",pending_gates=["cash_and_working_capital","tradability"]),
                           dict(code="1111",status="TURNOVER_FILTER_BELOW_1M_TWD",pending_gates=[])])
        return research,pending

    def test_prioritized_dated_queue_never_mints_pass(self):
        a,b=self.fixture()
        r=build(a,b,top=1)
        self.assertEqual(r["tracked_issuer_count"],3)
        self.assertEqual(r["eligible_research_count"],2)
        self.assertEqual(r["active_priority"][0]["code"],"9802")
        self.assertEqual(r["active_priority"][0]["next_route"],"FINANCIAL_ORIGINALS")
        self.assertEqual(r["gate_pending_counts"]["tradability"],2)
        self.assertEqual(r["lane_counts"]["INPUT_REPAIR"],1)
        self.assertTrue(all(not x["formal_Aplus"] for x in r["all_issuer_jobs"]))
        self.assertEqual(r["certification_from_dispatch"],0)
        self.assertIn("9802",render_md(r))

    def test_duplicate_code_and_missing_gate_rejected(self):
        a,b=self.fixture()
        a["all_model_row_summary"][1]["code"]="9802"
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):build(a,b)
        a,b=self.fixture()
        b["rows"][0]["pending_gates"]=[]
        with self.assertRaisesRegex(ValueError,"MISSING_CERTIFICATION"):build(a,b)
        a,b=self.fixture()
        b["rows"][0]["pending_gates"]=["invented_gate"]
        with self.assertRaisesRegex(ValueError,"INVALID_PENDING_GATES"):build(a,b)

    def test_stale_vintage_missing_issuer_and_nonfinite_rejected(self):
        a,b=self.fixture()
        b["asof"]="2026-10-18T17:00:00+08:00"
        with self.assertRaisesRegex(ValueError,"STALE"):build(a,b)
        a,b=self.fixture()
        b["rows"].pop()
        with self.assertRaisesRegex(ValueError,"UNIVERSE_NOT_IDENTICAL"):build(a,b)
        a,b=self.fixture()
        a["all_model_row_summary"][0]["scenario_upside_pct"]=float("inf")
        with self.assertRaisesRegex(ValueError,"INVALID_RESEARCH_UPSIDE"):build(a,b)
        self.assertEqual(len(ROUTES),13)

if __name__=="__main__":
    unittest.main()
