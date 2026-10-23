"""Paired 12-month *research* scorecard for two preregistered footwear paths.

A: insider persistence + low close; B: A plus public GM recovery.
B-only conditional outcomes must NEVER be compared to the full A sample as
proof that waiting is superior; reports include A on the SAME B-confirmed
subset, B confirmation coverage, and censoring. The return validator remains
fail-closed and requires >=30 matured events in each reported arm.
"""
from __future__ import annotations

from tw_model_v880.footwear_insider_holdout import aware, evaluate_outcomes


def compare_research_episodes(episodes, *, evaluated_at):
    """Compare frozen A entry episodes with B confirmations; no retroactive entry.

    Each episode has code, a_signal_at, a_outcome (validated event dict);
    optional b_signal_at/b_outcome must both be provided only if B truly fired
    after the A signal. Missing B is kept in the cohort as 'no confirmation'.
    An immature/missing outcome blocks publication rather than being dropped.
    """
    aware(evaluated_at)
    if not isinstance(episodes, list):
        raise ValueError("EPISODES_MUST_BE_LIST")
    if not episodes:
        return {"status": "NO_MATURED_PAIRED_EPISODES",
                "a_win_rate": None, "b_conditional_win_rate": None,
                "a_same_subset_win_rate": None, "confirmed_episode_count": 0,
                "unconfirmed_episode_count": 0,
                "production_gate_changed": False}

    all_a, subset_a, subset_b = [], [], []
    seen = set()
    for episode in episodes:
        if not isinstance(episode, dict):
            raise ValueError("INVALID_EPISODE")
        code = episode.get("code")
        signal_a = episode.get("a_signal_at")
        if not isinstance(code, str) or not isinstance(signal_a, str):
            raise ValueError("INVALID_EPISODE_KEY")
        frozen_id = (code, signal_a)
        if frozen_id in seen:
            raise ValueError("DUPLICATE_FROZEN_EPISODE")
        seen.add(frozen_id)
        a_at = aware(signal_a)
        a = episode.get("a_outcome")
        if not isinstance(a, dict) or a.get("code") != code or a.get("signal_at") != signal_a:
            return {"status": "PENDING_COMPLETE_A_OUTCOMES",
                    "a_win_rate": None, "b_conditional_win_rate": None,
                    "a_same_subset_win_rate": None,
                    "production_gate_changed": False}
        all_a.append(a)
        signal_b = episode.get("b_signal_at")
        b = episode.get("b_outcome")
        if signal_b is None and b is None:
            continue
        if not isinstance(signal_b, str) or not isinstance(b, dict):
            return {"status": "PENDING_B_CONFIRMATION_OR_OUTCOME",
                    "a_win_rate": None, "b_conditional_win_rate": None,
                    "a_same_subset_win_rate": None,
                    "production_gate_changed": False}
        b_at = aware(signal_b)
        if b_at < a_at:
            raise ValueError("B_CANNOT_SIGNAL_BEFORE_A")
        if b.get("code") != code or b.get("signal_at") != signal_b:
            raise ValueError("B_OUTCOME_DIFFERENT_FROM_FROZEN_SIGNAL")
        subset_a.append(a)
        subset_b.append(b)

    count_b = len(subset_b)
    result = {"status": "AWAITING_MATURED_12M_MATCHED_SAMPLES",
              "total_A_triggered_episodes": len(all_a),
              "confirmed_B_episode_count": count_b,
              "unconfirmed_B_episode_count": len(all_a) - count_b,
              "A_full_cohort": None,
              "A_on_B_confirmed_subset": None,
              "B_confirmed_subset": None,
              "a_win_rate": None, "b_conditional_win_rate": None,
              "a_same_subset_win_rate": None,
              "full_population_A_vs_B_winner": None,
              "production_gate_changed": False,
              "analysis_limit": "B is a delayed selected subset; no unconditional causal comparison or cash-drag portfolio return.",
              "independent_external_source_audit_not_performed_here": True}
    # Do not compute or expose even descriptive win rates if the source,
    # execution, or complete 12m outcome of any included episode is missing.
    full_a = evaluate_outcomes(all_a, evaluated_at=evaluated_at)
    b_subset = evaluate_outcomes(subset_b, evaluated_at=evaluated_at) if count_b else None
    a_subset = evaluate_outcomes(subset_a, evaluated_at=evaluated_at) if count_b else None
    result["A_full_cohort_status"] = full_a["status"]
    result["B_confirmed_subset_status"] = b_subset["status"] if b_subset else "NO_B_CONFIRMED"
    result["A_on_B_subset_status"] = a_subset["status"] if a_subset else "NO_B_CONFIRMED"
    admissible = "DESCRIPTIVE_AUDITED_OUTCOMES_NOT_CAUSAL_PROOF"
    if all(x is not None and x["status"] == admissible for x in (full_a, a_subset, b_subset)):
        result.update(
            status="THREE_ARM_DESCRIPTIVE_SCORES_NOT_STRATEGY_CAUSALITY",
            A_full_cohort=full_a, A_on_B_confirmed_subset=a_subset, B_confirmed_subset=b_subset,
            a_win_rate=full_a["win_rate"], b_conditional_win_rate=b_subset["win_rate"],
            a_same_subset_win_rate=a_subset["win_rate"],
            b_minus_a_same_subset_win_rate_pp=round(100*(b_subset["win_rate"]-a_subset["win_rate"]), 4))
    return result
