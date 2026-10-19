import unittest
from scripts.v881_history_diagnostic import observe,analyze,_standalone_gm

class HistoricalDiagnosticsTests(unittest.TestCase):
    def sample(self):
        return dict(code="9999",name="SYNTHETIC",market="TWSE",periods={
            "2024-Q4":dict(revenue_ytd_k=400,gross_profit_ytd_k=120),
            "2025-Q1":dict(revenue_ytd_k=100,gross_profit_ytd_k=20),
            "2025-Q2":dict(revenue_ytd_k=220,gross_profit_ytd_k=56),
            "2025-Q4":dict(revenue_ytd_k=500,gross_profit_ytd_k=125),
            "2026-Q1":dict(revenue_ytd_k=120,gross_profit_ytd_k=24),
            "2026-Q2":dict(revenue_ytd_k=240,gross_profit_ytd_k=51.6),
        })
    def test_cumulative_to_standalone_is_not_ytd_margin(self):
        x=self.sample()['periods']
        self.assertAlmostEqual(_standalone_gm(x["2025-Q1"],x["2025-Q2"]),.30)
    def test_2026_growth_and_seasonal_adjustment(self):
        x=observe(self.sample(),2026)
        self.assertTrue(x["low_gm"])
        self.assertAlmostEqual(x["q1_revenue_yoy_pct"],20)
        self.assertAlmostEqual(x["q2_change_pp"],3)
        self.assertAlmostEqual(x["seasonal_adjusted_q2_change_pp"],-7)
        self.assertFalse(x["issuer_PIT_verified"])
    def test_no_future_2026_inputs_needed_for_2025_observation(self):
        a=self.sample()
        result=observe(a,2025)
        for p in ["2026-Q1","2026-Q2"]:
            del a["periods"][p]
        self.assertEqual(result,observe(a,2025))
        self.assertTrue(result["low_gm"])
    def test_no_2024_H1_does_not_invent_2025_revenue_growth(self):
        self.assertIsNone(observe(self.sample(),2025)["q1_revenue_yoy_pct"])
        self.assertIsNone(observe(self.sample(),2025)["seasonal_adjusted_q2_change_pp"])
    def test_nonpositive_standalone_revenue_must_not_count(self):
        x=self.sample()
        x["periods"]["2026-Q2"]["revenue_ytd_k"]=50
        self.assertIsNone(observe(x,2026))
    def test_returns_metrics_are_explicitly_null(self):
        r=analyze([self.sample()])
        self.assertFalse(r["formal_stock_return_backtest_passed"])
        self.assertIsNone(r["model_2023_to_2025_stock_returns"])
        self.assertEqual(r["yearly"]["2026"]["low_gm"]["n"],1)
if __name__=="__main__":unittest.main()
