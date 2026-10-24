"""Regression tests for primary TWSE P/B regime and historical-only reversion."""
import json
import unittest

from scripts.v8108_footwear_pb_regime_study import (
    build,group_spells,fixed_crossing_reversions,rolling_low_10pct_events,
    percentile,summarize_events
)


def fake_pbs(values):
    return [{"date":f"2020-{i//28+1:02}-{i%28+1:02}","pb":float(v)} for i,v in enumerate(values)]


class FootwearPBRegimeTests(unittest.TestCase):
    def test_source_9050_and_missing_preIPO_no_trade_win_rate(self):
        report=build()
        self.assertEqual(report["total_official_daily_observations"],9050)
        self.assertEqual(report["formal_Aplus_2027"],0)
        self.assertFalse(report["2027_performance_vs_0050_known"])
        self.assertTrue(report["never_claim_PB_rise_as_stock_total_return"])
        for code,expected in (("9904",2438),("6768",1340),
                              ("6965",396),("9802",2438),("9910",2438)):
            stock=report["issuers"][code]
            self.assertEqual(stock["observations"],expected)
            self.assertFalse(stock["historical_PB_to_stock_total_return_conversion_done"])
            self.assertIsNone(stock["expected_2027_total_stock_return_pct"])

    def test_threshold_duration_and_book_discount(self):
        report=build()
        for code in ("9904","6768","6965","9802","9910"):
            stock=report["issuers"][code]
            under=stock["absolute_PB_thresholds_and_historic_spells"]["1"]
            self.assertLessEqual(under["time_below_threshold_sessions"],stock["observations"])
            self.assertGreaterEqual(under["share_of_observed_days_below_threshold_pct"],0)
            self.assertLessEqual(under["share_of_observed_days_below_threshold_pct"],100)
        self.assertEqual(report["issuers"]["9802"]["current_PB"],.92)
        self.assertEqual(report["issuers"]["9904"]["current_PB"],.42)
        self.assertEqual(report["issuers"]["9910"]["current_PB"],2.83)
        self.assertEqual(report["issuers"]["9910"]["absolute_PB_thresholds_and_historic_spells"]["1"]["time_below_threshold_sessions"],0)
        self.assertLess(report["issuers"]["9802"]["current_PB"],report["issuers"]["9802"]["full_period_median_PB"])

    def test_yearly_2026_vs_old_regime_is_explicit(self):
        report=build()
        for c in report["issuers"].values():
            self.assertIn("2026",c["calendar_year_risk_regimes"])
            self.assertLessEqual(c["rolling_PB_stats"]["252"]["minimum_PB"],c["current_PB"])
            self.assertGreaterEqual(c["rolling_PB_stats"]["252"]["maximum_PB"],c["current_PB"])
        self.assertIsNone(report["issuers"]["6965"]["rolling_PB_stats"]["756"])
        self.assertIsNotNone(report["issuers"]["6768"]["rolling_PB_stats"]["756"])

    def test_cross_from_above_1_requires_prior_trading_day(self):
        rows=[{"date":f"2024-01-{i+1:02}","pb":v} for i,v in enumerate([.8,.9,1.1,.85,1.2,.95])]
        matured,pending=fixed_crossing_reversions(rows,1,lag=2)
        self.assertEqual(len(matured),1)
        self.assertEqual(len(pending),1)
        self.assertEqual(matured[0]["PB_start"],.85)
        self.assertEqual(matured[0]["PB_end"],.95)

    def test_unmatured_signal_not_in_win_rate(self):
        rows=[{"date":f"2024-01-{i+1:02}","pb":v} for i,v in enumerate([1.1,.9,.8])]
        events,pending=fixed_crossing_reversions(rows,1,lag=2)
        self.assertEqual(len(events),0)
        self.assertEqual(len(pending),1)
        summary=summarize_events(events,pending)
        self.assertIsNone(summary["PB_multiples_rise_frequency_not_stock_win_rate_pct"])
        self.assertIsNone(summary["realized_total_stock_returns_including_dividends"])

    def test_spells_not_duplicated_and_left_censored(self):
        rows=[{"date":f"2026-03-{i+1:02}","pb":v} for i,v in enumerate([.6,.8,1.2,.9,.8,1.1,.7])]
        s=group_spells(rows,lambda x:x["pb"]<1)
        self.assertEqual([e["trading_days"] for e in s],[2,2,1])
        self.assertTrue(s[0]["left_censored"])
        self.assertEqual(s[-1]["last"],"2026-03-07")

    def test_rolling_events_require_prior_history_not_full_sample_future(self):
        rows=[{"date":f"2026-{i//28+1:02}-{i%28+1:02}","pb":1.2 if i<260 else .8}
              for i in range(515)]
        event,pending=rolling_low_10pct_events(rows,history=252,lag=252)
        self.assertEqual(len(event),1)
        self.assertEqual(event[0]["signal_date"],rows[260]["date"])
        self.assertTrue(event[0]["signal_window_excludes_current_and_future"])
        self.assertEqual(len(pending),1)

    def test_invalid_history_horizon_rejected(self):
        rows=[{"date":"2026-01-01","pb":1.1}]
        with self.assertRaisesRegex(ValueError,"HISTORY_WINDOW_TOO_SHORT"):
            rolling_low_10pct_events(rows,history=100,lag=252)
        with self.assertRaisesRegex(ValueError,"UNSAFE_HORIZON"):
            fixed_crossing_reversions(rows,1,lag=0)

    def test_percentile_is_linear_not_lookahead(self):
        self.assertAlmostEqual(percentile([1,2,3,4,5],.1),1.4)
        self.assertAlmostEqual(percentile([1,2,3,4,5],.25),2)
        self.assertAlmostEqual(percentile([5,4,3,2,1],.5),3)


if __name__=="__main__":
    unittest.main()
