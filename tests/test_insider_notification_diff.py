import unittest
from scripts.insider_notification_diff import compare

def report(rows, done=10, expected=100):
    return {
        "status": "PARTIAL_YTD_BUYER_DISCOVERY_NOT_MARKETWIDE",
        "marketwide_rank_claim_permitted": False,
        "verified_detail_month_count": done,
        "expected_detail_month_count": expected,
        "positive_buy_observed_sample_top100": rows,
    }

def row(code, pct=1.0, lots=100):
    return {"code": code, "buy_pct_of_issued": pct, "buy_lots": lots,
            "observed_months": ["2026-09"], "missing_months": ["2026-01"],
            "expected_ytd_month_count": 9}

class NotificationDiffTests(unittest.TestCase):
    def test_duplicate_is_silent(self):
        r = report([row("9802")])
        self.assertFalse(compare(r, r, {"9802"})["notify"])

    def test_new_verified_buyer(self):
        result = compare(report([]), report([row("9802")]), {"9802"})
        self.assertTrue(result["notify"])
        self.assertEqual(result["changes"][0]["code"], "9802")

    def test_unverified_is_silent(self):
        self.assertFalse(compare(report([]), report([row("9802")]), set())["notify"])

    def test_zero_buy_is_silent(self):
        self.assertFalse(compare(report([]), report([row("9802", lots=0)]), {"9802"})["notify"])

    def test_significant_ratio_change(self):
        result = compare(report([row("9802", 1.0)]),
                         report([row("9802", 1.3)]), {"9802"})
        self.assertTrue(result["notify"])

    def test_coverage_gain(self):
        result = compare(report([], 10), report([], 12), set())
        self.assertTrue(result["coverage_improved"])

    def test_small_coverage_gain_is_silent(self):
        self.assertFalse(compare(report([], 10), report([], 10), set())["notify"])

    def test_invalid_coverage_fails_closed(self):
        with self.assertRaises(ValueError):
            compare(report([]), report([], 101), set())

if __name__ == "__main__":
    unittest.main()
