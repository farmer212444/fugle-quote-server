import datetime as dt
import unittest

from scripts.mops_history_window import desired_backfill_quarters


def valid():
    return dict(status="ALL_BATCHES_PRESENT_UNAUDITED",
                expected_market_quarter_statement_batches=32,
                verified_batches=32,
                last_eligible_quarter="2026-Q3")


class QuarterlyWindowTest(unittest.TestCase):
    def test_new_q3_is_first_and_q2_legacy_seed_is_not_falsely_recollected(self):
        expected=["2026Q3", "2026Q1", "2025Q4", "2025Q3",
                  "2025Q2", "2025Q1", "2024Q4"]
        self.assertEqual(desired_backfill_quarters(valid(), today=dt.date(2026, 11, 27)), expected)

    def test_future_quarter_rolls_without_hardcoded_q3(self):
        source=valid()
        source["last_eligible_quarter"]="2027-Q1"
        result=desired_backfill_quarters(source,today=dt.date(2027, 5, 31))
        self.assertEqual(result[0], "2027Q1")
        self.assertEqual(result[-1], "2025Q2")
        self.assertNotIn("2026Q2", result)

    def test_rejects_incomplete_or_future_scan(self):
        for field,value in (("status","PARTIAL"),("verified_batches",31),
                            ("last_eligible_quarter","2027-Q1"),
                            ("last_eligible_quarter","2026-Q5")):
            with self.subTest(field=field,value=value):
                source=valid()
                source[field]=value
                with self.assertRaises(ValueError):
                    desired_backfill_quarters(source,today=dt.date(2026, 11, 27))

    def test_seed_outside_active_window_is_not_suppressed(self):
        source=valid()
        source["last_eligible_quarter"]="2028-Q3"
        result=desired_backfill_quarters(source,today=dt.date(2028, 11, 25))
        self.assertEqual(len(result),8)
        self.assertEqual(result[0],"2028Q3")


if __name__ == "__main__":
    unittest.main()
