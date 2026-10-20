"""Revenue-first discovery is independent of valuation and certification."""
import unittest
from tw_model_v880.revenue_leading import revenue_leading_signal

class RevenueLeadingTests(unittest.TestCase):
    def test_early_signal_before_margin_confirmation(self):
        x=revenue_leading_signal(72,12.97,.4232)
        self.assertEqual(x["status"],"EARLY_REVENUE_ACCELERATION")
        self.assertEqual(x["priority"],"HIGH")
        self.assertFalse(x["formal_quality_pass"])
        self.assertTrue(x["base_valuation_unchanged"])

    def test_growing_sales_with_margin_pressure_is_not_confirmed_profit(self):
        x=revenue_leading_signal(72,12.97,.4232,.132,.176)
        self.assertEqual(x["status"],"REVENUE_ACCELERATION_WITH_MARGIN_CONVERSION_RISK")
        self.assertTrue(x["margin_conversion_risk"])
        self.assertFalse(x["formal_quality_pass"])

    def test_declining_sales_not_promoted(self):
        x=revenue_leading_signal(-8,-3,-.1)
        self.assertEqual(x["priority"],"NONE")

    def test_missing_data_does_not_become_zero(self):
        x=revenue_leading_signal(None,15,.2)
        self.assertEqual(x["status"],"INSUFFICIENT_DATED_REVENUE_DATA")

    def test_no_invented_acceleration_when_monthly_not_above_ytd(self):
        x=revenue_leading_signal(10,25,.2)
        self.assertEqual(x["priority"],"NORMAL")

if __name__=="__main__":
    unittest.main()
