"""Synthetic contract tests, not historical performance or MOPS certification."""
import datetime as dt
import unittest
from unittest.mock import patch

from tw_model_v880.footwear_insider_holdout import evaluate_signal, evaluate_outcomes, wilson_interval

SHA = "a" * 64
DECISION = "2026-10-23T17:00:00+08:00"


def original(published="2026-10-15T10:00:00+08:00", captured="2026-10-15T11:00:00+08:00"):
    return dict(original_sha256=SHA, published_at=published, first_captured_at=captured)


def snapshot():
    days = []
    day = dt.date(2026, 10, 22)
    while len(days) < 252:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= dt.timedelta(days=1)
    days.sort()
    closes = [dict(date=x, close=100 + (i % 20) * 5) for i, x in enumerate(days)]
    closes[-1]["close"] = 100
    q1 = dict(period="2026Q1", revenue=100, gross_profit=10, single_quarter=True,
              **original("2026-05-15T10:00:00+08:00", "2026-05-15T11:00:00+08:00"))
    q2 = dict(period="2026Q2", revenue=100, gross_profit=12, single_quarter=True,
              **original("2026-08-15T10:00:00+08:00", "2026-08-15T11:00:00+08:00"))
    price = dict(closes=closes, calendar_sessions_verified=True,
                 **original("2026-10-22T14:00:00+08:00", "2026-10-22T18:00:00+08:00"))
    return dict(insider_months=[], issued_shares=200_000_000,
                shares_asof="2026-10-14T10:00:00+08:00", shares_original_sha256=SHA,
                contemporaneous_footwear_universe_verified=True,
                trailing_price_evidence=price, gross_margin_quarters=[q1, q2])


def event(i, stock=.2, bench=.1):
    return dict(code=str(1000 + i),
                signal_at="2026-10-24T10:00:00+08:00",
                entry_at="2026-10-26T09:00:00+08:00",
                exit_at="2027-10-27T13:30:00+08:00",
                originals_independently_audited=True, first_eligible_open_verified=True,
                issuer_and_0050_action_registers_complete=True,
                matched_execution_dates_verified=True,
                pre_registered_rule_asof_signal=True,
                issuer_execution_receipt_sha256=SHA,
                benchmark_execution_receipt_sha256=SHA,
                corporate_action_receipt_sha256=SHA,
                outcome_first_captured_at="2027-10-28T09:00:00+08:00",
                stock_net_total_return=stock, etf_0050_net_total_return=bench)


class FootwearHoldoutTests(unittest.TestCase):
    def setUp(self):
        self.mock = patch("tw_model_v880.insider_accumulation.evaluate_insider_accumulation",
                          return_value=dict(status="RESEARCH_WATCH_REQUIRES_INDEPENDENT_AUDIT",
                                            three_month_net_lots=411))
        self.mock.start()

    def tearDown(self):
        self.mock.stop()

    def test_watch_is_research_only(self):
        r = evaluate_signal(snapshot(), decision_at=DECISION)
        self.assertTrue(r["eligible_research_signal"])
        self.assertEqual(r["status"], "RESEARCH_SIGNAL_REQUIRES_INDEPENDENT_ORIGINAL_AUDIT")
        self.assertFalse(r["formal_aplus_or_exit_changed"])

    def test_insider_gate_pending(self):
        with patch("tw_model_v880.insider_accumulation.evaluate_insider_accumulation",
                   return_value={"status": "PENDING_OFFICIAL_MARKET_TRADE_ORIGINAL"}):
            self.assertEqual(evaluate_signal(snapshot(), decision_at=DECISION)["status"],
                             "INSIDER_PENDING_OFFICIAL_MARKET_TRADE_ORIGINAL")

    def test_future_financial_release_never_used(self):
        s = snapshot()
        s["gross_margin_quarters"][1]["published_at"] = "2026-10-24T10:00:00+08:00"
        s["gross_margin_quarters"][1]["first_captured_at"] = "2026-10-24T11:00:00+08:00"
        self.assertEqual(evaluate_signal(s, decision_at=DECISION)["status"],
                         "PENDING_ORIGINAL_QUARTER_PIT")

    def test_high_price_fails(self):
        s = snapshot()
        s["trailing_price_evidence"]["closes"][-1]["close"] = 180
        self.assertEqual(evaluate_signal(s, decision_at=DECISION)["status"],
                         "PRICE_NOT_IN_BOTTOM_20_PERCENT")

    def test_no_margin_recovery_fails(self):
        s = snapshot()
        s["gross_margin_quarters"][1]["gross_profit"] = 10
        self.assertEqual(evaluate_signal(s, decision_at=DECISION)["status"],
                         "GROSS_MARGIN_NOT_RECOVERING_BY_1PP")

    def test_missing_trading_calendar_fails(self):
        s = snapshot()
        s["trailing_price_evidence"]["calendar_sessions_verified"] = False
        self.assertEqual(evaluate_signal(s, decision_at=DECISION)["status"],
                         "PENDING_TRADING_CALENDAR_PRICE_PIT_ORIGINAL")

    def test_incomplete_price_window_fails(self):
        s = snapshot()
        s["trailing_price_evidence"]["closes"].pop()
        self.assertEqual(evaluate_signal(s, decision_at=DECISION)["status"],
                         "PENDING_COMPLETE_252_SESSION_PRICE_WINDOW")

    def test_no_matured_outcomes_is_null(self):
        r = evaluate_outcomes([], evaluated_at="2028-01-02T09:00:00+08:00")
        self.assertIsNone(r["win_rate"])

    def test_unmatured_outcome_is_blocked(self):
        r = evaluate_outcomes([event(1)], evaluated_at="2027-03-01T09:00:00+08:00")
        self.assertEqual(r["status"], "UNMATURED_OR_NONEXECUTABLE_12M_HORIZON")

    def test_pre_registration_not_forward_oos(self):
        e = event(1)
        e["signal_at"] = "2025-10-24T10:00:00+08:00"
        e["entry_at"] = "2025-10-25T09:00:00+08:00"
        e["exit_at"] = "2026-10-27T13:30:00+08:00"
        r = evaluate_outcomes([e], evaluated_at="2028-01-02T09:00:00+08:00")
        self.assertEqual(r["status"], "UNMATURED_OR_NONEXECUTABLE_12M_HORIZON")

    def test_one_sample_does_not_publish_win_rate(self):
        r = evaluate_outcomes([event(1)], evaluated_at="2028-01-02T09:00:00+08:00")
        self.assertEqual(r["status"], "INSUFFICIENT_INDEPENDENT_MATURED_EVENTS")
        self.assertIsNone(r["win_rate"])

    def test_missing_benchmark_corporate_actions_is_blocked(self):
        e = event(1)
        e["issuer_and_0050_action_registers_complete"] = False
        self.assertEqual(evaluate_outcomes([e], evaluated_at="2028-01-02T09:00:00+08:00")["status"],
                         "PENDING_INDEPENDENT_MATCHED_EXECUTION_AUDIT")

    def test_30_synthetic_examples_are_descriptive_only(self):
        xs = [event(i, stock=.2 if i <= 20 else .05, bench=.1) for i in range(1, 31)]
        r = evaluate_outcomes(xs, evaluated_at="2028-01-02T09:00:00+08:00")
        self.assertEqual(r["status"], "DESCRIPTIVE_AUDITED_OUTCOMES_NOT_CAUSAL_PROOF")
        self.assertEqual((r["n"], r["wins"]), (30, 20))
        self.assertFalse(r["formal_aplus_or_exit_changed"])
        self.assertFalse(r["sixty_pct_win_rate_supported_at_95pct"])

    def test_overlapping_same_issuer_not_counted_twice(self):
        self.assertEqual(evaluate_outcomes([event(1), event(1)],
                        evaluated_at="2028-01-02T09:00:00+08:00")["status"],
                        "OVERLAPPING_ISSUER_HOLDING_WINDOWS")

    def test_wilson_confidence_interval_not_point_estimate(self):
        low, high = wilson_interval(18, 30)
        self.assertLess(low, 0.6)
        self.assertGreater(high, 0.6)


if __name__ == "__main__":
    unittest.main()
