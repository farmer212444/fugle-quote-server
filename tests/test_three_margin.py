"""Synthetic PIT tests; passing these does not validate historical returns."""
import unittest
from tw_model_v880.three_margin import classify


def sample():
    return dict(issuer="9802", quarter="2026Q2",
                published_at="2026-08-14T16:00:00+08:00",
                captured_at="2026-08-14T17:00:00+08:00",
                signal_at="2026-08-15T09:00:00+08:00",
                gross_margin=18, operating_margin=8, net_margin=6,
                gross_margin_yoy_prev=-1, operating_margin_yoy_prev=-2,
                gross_margin_yoy=1, operating_margin_yoy=0.5,
                net_margin_yoy=-0.2, revenue_yoy_3m=12,
                revenue_yoy_prior_3m=5, operating_profit=100)


class ThreeMarginPIT(unittest.TestCase):
    def test_early_turn_without_three_rising(self):
        result=classify(sample())
        self.assertTrue(result["B"])
        self.assertFalse(result["A"])

    def test_all_three_rising(self):
        row=sample();row["net_margin_yoy"]=0.2
        self.assertTrue(classify(row)["A"])

    def test_no_lookahead(self):
        row=sample();row["captured_at"]="2026-08-16T09:00:00+08:00"
        self.assertEqual(classify(row)["status"],"NOT_VALIDATED")

    def test_revision_after_signal(self):
        row=sample();row["revision_at"]="2026-09-01T12:00:00+08:00"
        self.assertEqual(classify(row)["status"],"NOT_VALIDATED")

    def test_missing_is_not_zero(self):
        row=sample();del row["gross_margin_yoy"]
        self.assertEqual(classify(row)["status"],"NOT_VALIDATED")

    def test_equal_does_not_count_as_rise(self):
        row=sample();row["gross_margin_yoy"]=0
        self.assertFalse(classify(row)["B"])

    def test_financial_excluded(self):
        row=sample();row["is_financial"]=True
        self.assertEqual(classify(row)["status"],"EXCLUDED")

    def test_timezone_required(self):
        row=sample();row["published_at"]="2026-08-14T16:00:00"
        self.assertEqual(classify(row)["status"],"NOT_VALIDATED")


if __name__ == "__main__":
    unittest.main()
