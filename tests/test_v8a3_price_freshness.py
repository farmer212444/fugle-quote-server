"""Reference quote vintage guard: warn on possible missing market sessions.

Weekdays are only a heuristic. No holiday/exchange status is inferred.
"""
import unittest
from tw_model_v880.freshness import (
    assess_price_freshness, possible_completed_weekday_sessions
)


class PriceFreshnessTests(unittest.TestCase):
    def test_live_oct21_morning_detects_oct20_potential_missing_session(self):
        r=assess_price_freshness("2026-10-21T10:30:00+08:00","2026-10-19")
        self.assertEqual(r["status"],"POSSIBLY_STALE_CONFIRM_EXCHANGE_SESSION")
        self.assertEqual(r["potentially_missing_weekdays"],["2026-10-20"])
        self.assertTrue(r["equity_source_may_be_stale"])
        self.assertFalse(r["market_holiday_calendar_certified"])
        self.assertFalse(r["quote_is_confirmed_latest_session"])
        self.assertFalse(r["quotes_imputed_or_backfilled"])
        self.assertTrue(r["research_model_2027_unchanged"])
        self.assertTrue(r["formal_Aplus_status_unchanged"])

    def test_prior_day_quote_is_not_stale_but_also_not_confirmed_current(self):
        r=assess_price_freshness("2026-10-21T10:30:00+08:00","2026-10-20")
        self.assertEqual(r["status"],"NO_POTENTIAL_WEEKDAY_PRICE_GAP")
        self.assertEqual(r["potentially_missing_weekdays"],[])
        self.assertFalse(r["quote_is_confirmed_latest_session"])

    def test_monday_before_close_respects_weekend(self):
        r=assess_price_freshness("2026-10-19T10:30:00+08:00","2026-10-16")
        self.assertEqual(r["potentially_missing_weekdays"],[])
        after=assess_price_freshness("2026-10-19T17:30:00+08:00","2026-10-16")
        self.assertEqual(after["potentially_missing_weekdays"],["2026-10-19"])

    def test_no_future_day_and_timezone_guard(self):
        with self.assertRaisesRegex(ValueError,"FUTURE_REFERENCE_PRICE"):
            assess_price_freshness("2026-10-21T10:30:00+08:00","2026-10-22")
        with self.assertRaisesRegex(ValueError,"FRESHNESS_ASOF_TIMEZONE_REQUIRED"):
            assess_price_freshness("2026-10-21T10:30:00","2026-10-20")

    def test_weekday_screen_does_not_assert_actual_trading_or_fill(self):
        # Weekday candidate alone cannot prove an exchange was open.
        monday=possible_completed_weekday_sessions("2026-10-12T18:00:00+08:00",
                                                    "2026-10-09")
        self.assertEqual(monday,["2026-10-12"])
        r=assess_price_freshness("2026-10-12T18:00:00+08:00","2026-10-09")
        self.assertFalse(r["market_holiday_calendar_certified"])
        self.assertFalse(r["quotes_imputed_or_backfilled"])


if __name__=="__main__":
    unittest.main()
