"""Synthetic, offline tests; these do not certify any real insider filing."""
import unittest

from tw_model_v880.insider_accumulation import evaluate_insider_accumulation

SHA = "a" * 64


def sample():
    rows = []
    for month, buys in [("2026-07", 60), ("2026-08", 120), ("2026-09", 231)]:
        rows.append(dict(month=month, source_kind="OFFICIAL_MOPS_POST_TRADE_ORIGINAL",
                         original_sha256=SHA, holder_identity_reconciled=True,
                         holdings_rollforward_reconciled=True,
                         market_vs_transfer_reconciled=True,
                         market_buy_lots=buys, market_sell_lots=0,
                         published_at="2026-10-15T10:00:00+08:00",
                         receipt_at="2026-10-15T11:00:00+08:00"))
    return rows


def inspect(rows, **overrides):
    kwargs=dict(decision_at="2026-10-23T17:00:00+08:00",
                issued_shares=200_000_000,
                issued_shares_asof="2026-10-14T10:00:00+08:00",
                issued_shares_original_sha256=SHA)
    kwargs.update(overrides)
    return evaluate_insider_accumulation(rows, **kwargs)


class InsiderAccumulationResearchTests(unittest.TestCase):
    def test_synthetic_three_months_only_research_watch(self):
        result = inspect(sample())
        self.assertEqual(result["status"], "RESEARCH_WATCH_REQUIRES_INDEPENDENT_AUDIT")
        self.assertEqual(result["three_month_net_lots"], 411)
        self.assertEqual(result["report_months_checked"], ["2026-07", "2026-08", "2026-09"])
        self.assertFalse(result["new_formal_Aplus"])
        self.assertFalse(result["eps_pe_override"])
        self.assertFalse(result["automatic_exit"])
        self.assertFalse(result["backtest_eligible"])
        self.assertFalse(result["independently_certified"])

    def test_secondary_summary_is_not_validated(self):
        rows = sample()
        rows[-1]["source_kind"] = "SECONDARY_MOPS_DERIVED_SUMMARY_ONLY"
        self.assertEqual(inspect(rows)["status"], "PENDING_OFFICIAL_MARKET_TRADE_ORIGINAL")

    def test_future_publication_causes_pit_block(self):
        rows = sample()
        rows[0]["published_at"] = "2026-10-24T10:00:00+08:00"
        rows[0]["receipt_at"] = "2026-10-24T11:00:00+08:00"
        self.assertEqual(inspect(rows)["status"], "PENDING_PIT_PUBLICATION_OR_RECEIPT")

    def test_early_decision_before_publication_blocks(self):
        self.assertEqual(inspect(sample(), decision_at="2026-10-14T09:00:00+08:00")["status"],
                         "PENDING_FUTURE_SHARES_SOURCE")

    def test_transfer_cannot_be_market_buying(self):
        rows = sample()
        rows[-1]["market_vs_transfer_reconciled"] = False
        self.assertEqual(inspect(rows)["status"], "PENDING_IDENTITY_TRANSFER_OR_ROLLFORWARD")

    def test_missing_month_is_pending(self):
        self.assertEqual(inspect(sample()[:-1])["status"],
                         "PENDING_THREE_CONSECUTIVE_MONTHS")

    def test_monthly_selling_breaks_persistence(self):
        rows = sample()
        rows[1]["market_sell_lots"] = 200
        self.assertEqual(inspect(rows)["status"], "NO_THREE_MONTH_PERSISTENCE")

    def test_small_buying_is_not_promoted(self):
        rows = sample()
        for row in rows:
            row["market_buy_lots"] = 1
        self.assertEqual(inspect(rows)["status"], "POSITIVE_BUT_LOW_MATERIALITY")

    def test_duplicate_month_is_not_silently_summed(self):
        self.assertEqual(inspect(sample() + [sample()[2]])["status"],
                         "PENDING_DUPLICATE_REPORTING_MONTH")

    def test_missing_denominator_is_pending(self):
        self.assertEqual(inspect(sample(), issued_shares=None)["status"],
                         "PENDING_OFFICIAL_SHARES_DENOMINATOR")

    def test_naive_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "TIMESTAMP_MUST_HAVE_OFFSET"):
            inspect(sample(), decision_at="2026-10-23T17:00:00")


if __name__ == "__main__":
    unittest.main()
