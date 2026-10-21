import unittest
from scripts.v8a5_quality_decision_lane import prepare,markdown

GATES=[
"original_eight_quarter_statements","cash_and_working_capital",
"nonoperating_components","fully_diluted_shares","matched_peers_and_cycle",
"management_promises","auditor_scope","tradability","forecast_bridge",
"insider_claims","dividend_window","point_in_time","out_of_sample_validation",
]
def fixtures():
    rows=[];diag=[]
    for i in range(10):
        code=str(2000+i)
        is_red=i==0
        source="ORIGINAL_CURRENT_ISSUER_NUMERICS" if i%2==0 else "OFFICIAL_CURRENT_BATCH_WITH_UNVERIFIED_HISTORICAL_DETAIL"
        rows.append(dict(code=code,rank=i+1,name="test"+code,market="TWSE",reference_close=100.,
            price_date="2026-10-20",source_tier=source,
            base_2027_eps=10.,base_2027_pe=20.,base_2027_target=200.,
            base_2027_upside_pct=100.-i,
            stress_double20_upside_pct=28.+i,
            q3_revenue_yoy_pct=35.,formal_Aplus=False,
            analysis=dict(flags=[] if not is_red else ["FORWARD_PE_AT_LEAST_20_REQUIRES_MATCHED_PEERS"]),
            critical_evidence_gaps=["Q3_REVENUE_GROWTH_DECELERATED_AT_LEAST_20PP"] if is_red else []))
        diag.append(dict(code=code,formally_passed_gates=[],formally_failed_gates=[],
            still_pending_gates=GATES,formal_Aplus=False))
    top=dict(asof_price_date="2026-10-20",issuer_ranked=rows,
             automatically_certified_Aplus=0,estimate_vintage="2026-10-21T12:00:00+08:00",
             financial_last_quarter="2026-Q2")
    gate=dict(asof_price_date="2026-10-20",issuer_diagnostics=diag)
    price=dict(date="2026-10-20")
    return top,gate,price

class QualityLaneTests(unittest.TestCase):
    def test_math_rank_unchanged_and_high_upside_red_not_verified(self):
        a,b,c=fixtures()
        out=prepare(a,b,c)
        self.assertEqual([i["code"] for i in out["base_upside_order"]],
                         [i["code"] for i in a["issuer_ranked"]])
        first=out["base_upside_order"][0]
        self.assertEqual(first["quality_review_status"],"OPERATING_PE_OR_DILUTION_RED_FLAGS_REVIEW")
        self.assertFalse(first["high_confidence_buy_or_Aplus_certified"])
        self.assertEqual(out["formal_Aplus_added"],0)
        self.assertEqual(out["issuer_count"],10)
        self.assertNotEqual(out["verification_order"][0]["code"],first["code"])
    def test_date_mismatch_rejected(self):
        a,b,c=fixtures();b["asof_price_date"]="2026-10-19"
        with self.assertRaisesRegex(ValueError,"VINTAGE_MISMATCH"):prepare(a,b,c)
    def test_missing_formal_gate_cannot_silently_pass(self):
        a,b,c=fixtures();b["issuer_diagnostics"][0]["still_pending_gates"]=[]
        with self.assertRaisesRegex(ValueError,"INCOMPLETE_THIRTEEN_GATE"):
            prepare(a,b,c)
    def test_q3_self_report_not_used_to_rewrite_base(self):
        a,b,c=fixtures()
        out=prepare(a,b,c,dict(period="2026-Q3",status="SELF_REPORTED_UNAUDITED",
            disclosed_at="2026-10-20",q3_2026=dict(eps=0.68,revenue=5435935,gross_profit=719347)))
        self.assertAlmostEqual(out["9802_Q3_self_report"]["gross_margin_pct"],13.23)
        self.assertIn("NOT_AUTOMATICALLY_RESTATED",str(out["9802_Q3_self_report"]))
        self.assertIn("2026Q3",markdown(out))
    def test_numeric_only_stress_no_probabilities(self):
        a,b,c=fixtures();out=prepare(a,b,c)
        self.assertTrue(out["verification_order"][0]["high_confidence_buy_or_Aplus_certified"] is False)
        self.assertFalse(out["has_statistical_outperformance_calibration"])

if __name__=="__main__": unittest.main()
