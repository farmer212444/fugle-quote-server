"""0050 2025-06-18 4:1 split accounting control — NOT a verified backtest.

TWSE public split notice: before split 2025-06-10 close 188.65;
2025-06-18 resumption reference 47.16; unit multiplier FOUR.
https://www.twse.com.tw/zh/ETFortune/announcement?company=A00005&date=20250617&fund=0050&seq=1&type=other

Bars below represent a minimal arithmetic TEST. They do not prove actual
fills, liquidity, total dividends, 12-month benchmark performance or PIT.
"""
import unittest

from tw_model_v880.execution import net_trade


def sample(split):
    return net_trade(
        bars=[
            dict(open_at="2025-06-10T09:00:00+08:00",
                 close_at="2025-06-10T13:30:00+08:00",
                 open=188.65, close=188.65, turnover_ntd=1e9,
                 fillability_verified=True),
            dict(open_at="2025-06-18T09:00:00+08:00",
                 close_at="2025-06-18T13:30:00+08:00",
                 open=47.16, close=47.16, turnover_ntd=1e9,
                 fillability_verified=True),
        ],
        actions=[dict(id="0050-2025-06-18-official-four-for-one",
                      type="split", ratio=4.0,
                      effective_at="2025-06-18T00:00:00+08:00")] if split else [],
        signal_at="2025-06-09T17:00:00+08:00",
        exit_at="2025-06-18T14:00:00+08:00",
        costs={
            "buy_fee_rate": 0.0, "sell_fee_rate": 0.0, "sell_tax_rate": 0.0,
            "buy_slippage_rate": 0.0, "sell_slippage_rate": 0.0,
            "half_spread_rate": 0.0, "minimum_fee_ntd": 0.0},
        corporate_actions_complete=True, requested_notional_ntd=10000.0,
        max_participation=0.05,
    )


class ETF0050SplitAccountingTests(unittest.TestCase):
    def test_split_cannot_be_fake_75pct_drawdown(self):
        adjusted = sample(True)
        omitted = sample(False)
        self.assertAlmostEqual(adjusted["ending_shares"], 4*10000/188.65)
        self.assertAlmostEqual(adjusted["net_total_return"],
                               4*47.16/188.65-1, places=12)
        self.assertLess(abs(adjusted["net_total_return"]), .001)
        self.assertLess(omitted["net_total_return"], -.70)

    def test_ex_dividend_cash_not_same_as_split(self):
        # A cash dividend increases cash received but not units.
        # A 4:1 split multiplies units but does not directly pay cash.
        r = sample(True)
        self.assertEqual(r["dividend_cash"], 0)
        self.assertGreater(r["ending_shares"], 200)

    def test_net_trade_needs_verified_complete_action_registry(self):
        with self.assertRaisesRegex(ValueError, "CORPORATE_ACTION_COVERAGE_UNKNOWN"):
            net_trade(bars=[], actions=[], signal_at="2025-06-10T00:00:00+08:00",
                      exit_at="2025-06-18T14:00:00+08:00",
                      costs={}, corporate_actions_complete=False,
                      requested_notional_ntd=10000., max_participation=.05)


if __name__ == "__main__":
    unittest.main()
