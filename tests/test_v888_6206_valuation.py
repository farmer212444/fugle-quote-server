import unittest
from scripts.v888_6206_valuation import calculate,SCENARIOS,positive,require

def fixture():
    baseline=dict(price_date="2026-10-16",model_vintage="2026-10-20T03:25:30+08:00",
                  current_financial_period="2026-Q2",model_version="V8.8.2",
                  existing_base_2027=dict(eps=9.5,target_price=148.0))
    src=dict(IR_h1=dict(first_captured_utc="2026-10-19T13:36:13+00:00",
             event_date="2026-08-12",source_url="https://www.flytech.com.tw/data/investor_law/attached/a.pdf",
             pdf_sha256="f"*64,extracted_text_sha256="e"*64),
             IR_fy=dict(first_captured_utc="2026-10-19T13:36:13+00:00",event_date="2026-03-20",source_url="https://www.flytech.com.tw/data/investor_law/attached/b.pdf",
             pdf_sha256="a"*64,extracted_text_sha256="b"*64),
             observations=dict(H1_2026_eps=5.93,H1_2026_inventory_m=1510,
                               H1_2026_receivables_m=1617))
    revenue=dict(revenue_9m_ntd_m=5135.677,ytd_yoy_pct=30.07,
        provenance=dict(capture_utc="2026-10-19T16:59:14+00:00"))
    price=dict(close=134.5,date="2026-10-16",source="official")
    return baseline,src,revenue,price

class FlytechValuationTests(unittest.TestCase):
    def test_base_earnings_bridge_and_all_scenarios(self):
        r=calculate(*fixture())
        self.assertEqual(r["status"],"SOURCE_RECONCILED_RESEARCH_ONLY_UNCERTIFIED")
        self.assertAlmostEqual(r["scenarios"]["base"]["eps"],11.617,places=2)
        self.assertAlmostEqual(r["scenarios"]["base"]["target_price"],185.87,places=1)
        self.assertAlmostEqual(r["scenarios"]["bear"]["target_price"],101.7,places=0)
        self.assertAlmostEqual(r["scenarios"]["bull"]["target_price"],253.4,places=0)
        self.assertAlmostEqual(r["estimated_2026_Q4_revenue_m"],1464.323)
        self.assertEqual(r["formal_quality_gates_passed_by_this_report"],0)
        self.assertFalse(r["formal_Aplus"])
        self.assertTrue(r["common_market_rank_unchanged"])
        self.assertTrue(r["assumptions_status"]["common_shares_are_proxy_not_diluted_certified"])
    def test_period_gate_fail_closed(self):
        b,s,r,p=fixture()
        b["current_financial_period"]="2026-Q3"
        with self.assertRaisesRegex(ValueError,"Q3_FINANCIAL_MODEL_ROLLOVER"):
            calculate(b,s,r,p)
    def test_mismatched_reference_price_does_not_mix_vintages(self):
        b,s,r,p=fixture()
        p["date"]="2026-10-19"
        with self.assertRaisesRegex(ValueError,"PRICE_DATE_NOT_MATCHED"):
            calculate(b,s,r,p)
    def test_future_source_receipt_rejected(self):
        b,s,r,p=fixture()
        r["provenance"]["capture_utc"]="2026-10-21T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError,"FORWARD_VINTAGE"):
            calculate(b,s,r,p)
    def test_invalid_numbers_fail_closed(self):
        self.assertIsNone(positive(None))
        self.assertIsNone(positive(True))
        self.assertIsNone(positive("nan"))
        with self.assertRaises(ValueError):require(False,"NEGATIVE")
if __name__=="__main__":
    unittest.main()
