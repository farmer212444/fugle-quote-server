"""Synthetic-only paired cohort validation, not realized investment alpha."""
import unittest

from tests.test_footwear_insider_holdout import event
from tw_model_v880.footwear_strategy_pair import compare_research_episodes

NOW = "2028-01-02T09:00:00+08:00"


def episode(i, *, confirmed=True, a_return=0.1, b_return=0.2):
    a = event(i, stock=a_return, bench=.15)
    e = {"code": a["code"], "a_signal_at": a["signal_at"], "a_outcome": a}
    if confirmed:
        b = event(i, stock=b_return, bench=.15)
        b["signal_at"] = "2026-11-30T16:00:00+08:00"
        b["entry_at"] = "2026-12-01T09:00:00+08:00"
        b["exit_at"] = "2027-12-02T13:30:00+08:00"
        b["outcome_first_captured_at"] = "2027-12-03T09:00:00+08:00"
        e.update(b_signal_at=b["signal_at"], b_outcome=b)
    return e


class PairedCohortTests(unittest.TestCase):
    def test_no_episodes_reports_no_win_rate(self):
        r = compare_research_episodes([], evaluated_at=NOW)
        self.assertIsNone(r["a_win_rate"])
        self.assertIsNone(r["full_population_A_vs_B_winner"] if "full_population_A_vs_B_winner" in r else None)

    def test_six_or_fewer_events_never_publish_real_win(self):
        xs = [episode(i) for i in range(1, 7)]
        r = compare_research_episodes(xs, evaluated_at=NOW)
        self.assertEqual(r["status"], "AWAITING_MATURED_12M_MATCHED_SAMPLES")
        self.assertIsNone(r["b_conditional_win_rate"])

    def test_b_must_not_be_backdated_before_a(self):
        x = episode(1)
        x["b_signal_at"] = "2026-10-01T12:00:00+08:00"
        x["b_outcome"]["signal_at"] = x["b_signal_at"]
        with self.assertRaisesRegex(ValueError, "B_CANNOT_SIGNAL_BEFORE_A"):
            compare_research_episodes([x], evaluated_at=NOW)

    def test_b_no_signal_not_silently_dropped_from_a(self):
        xs = [episode(i, confirmed=(i <= 30)) for i in range(1, 33)]
        r = compare_research_episodes(xs, evaluated_at=NOW)
        self.assertEqual(r["total_A_triggered_episodes"], 32)
        self.assertEqual(r["unconfirmed_B_episode_count"], 2)
        self.assertEqual(r["confirmed_B_episode_count"], 30)

    def test_selected_subset_rate_is_not_full_population_winner(self):
        xs = [episode(i, a_return=.10 if i <= 15 else .20,
                         b_return=.20 if i <= 22 else .10) for i in range(1, 31)]
        r = compare_research_episodes(xs, evaluated_at=NOW)
        self.assertEqual(r["status"], "THREE_ARM_DESCRIPTIVE_SCORES_NOT_STRATEGY_CAUSALITY")
        self.assertEqual(r["total_A_triggered_episodes"], 30)
        self.assertEqual(r["a_win_rate"], .5)
        self.assertEqual(r["b_conditional_win_rate"], round(22/30, 6))
        self.assertIsNone(r["full_population_A_vs_B_winner"])
        self.assertFalse(r["production_gate_changed"])

    def test_missing_b_outcome_never_treated_as_no_signal(self):
        x = episode(1)
        x["b_outcome"] = None
        r = compare_research_episodes([x], evaluated_at=NOW)
        self.assertEqual(r["status"], "PENDING_B_CONFIRMATION_OR_OUTCOME")
        self.assertIsNone(r["b_conditional_win_rate"])

    def test_incomplete_corporate_actions_blocks_results(self):
        xs = [episode(i) for i in range(1, 31)]
        xs[0]["b_outcome"]["issuer_and_0050_action_registers_complete"] = False
        r = compare_research_episodes(xs, evaluated_at=NOW)
        self.assertEqual(r["status"], "AWAITING_MATURED_12M_MATCHED_SAMPLES")
        self.assertIsNone(r["b_conditional_win_rate"])

    def test_duplicate_frozen_episode_is_rejected(self):
        x = episode(1)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_FROZEN_EPISODE"):
            compare_research_episodes([x, x], evaluated_at=NOW)


if __name__ == "__main__":
    unittest.main()
