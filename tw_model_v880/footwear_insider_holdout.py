"""Predeclared footwear insider/price/margin research and one-year outcome audit.

Computational checks only: metadata and hash claims do not replace auditing
original MOPS disclosure files or independent corporate-action reconciliation.
Never update existing 13 quality gates, A+/A++, Base, or Exit.
"""
from __future__ import annotations

from datetime import date, datetime
import math
import re

SHA = re.compile(r"[0-9a-f]{64}\Z")
POLICY = {
    "signal": "3_positive_insider_months_AND_bottom20pct_of_252_closes_AND_QOQ_GM_plus1pp",
    "low_price_window_sessions": 252,
    "max_trailing_range_position": 0.20,
    "min_gm_delta_percentage_points": 1.0,
    "benchmark": "0050_DIVIDEND_ADJUSTED_NET_TOTAL_RETURN_MATCHED_DATES",
    "holding_calendar_days": 365,
    "minimum_independent_matured_events": 30,
    "one_signal_per_issuer_per_365_days": True,
    "test_target_outperformance_probability": 0.60,
    "signal_registration_date": "2026-10-23",
    "lookback_retroactive_outcomes_usable_as_forward_validation": False,
}


def aware(value):
    try:
        d = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_OFFSET_AWARE_TIMESTAMP") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("INVALID_OFFSET_AWARE_TIMESTAMP")
    return d


def digest_ok(value):
    return isinstance(value, str) and bool(SHA.fullmatch(value))


def blocked(reason, **kwargs):
    return {"status": reason, "eligible_research_signal": False,
            "formal_aplus_or_exit_changed": False,
            "forward_returns_certified": False, **kwargs}


def source_asof(evidence, signal_at):
    if not digest_ok(evidence.get("original_sha256")):
        return False
    try:
        published, captured = aware(evidence["published_at"]), aware(evidence["first_captured_at"])
    except (KeyError, ValueError):
        return False
    return published <= captured <= signal_at


def _quarter_index(period):
    if not isinstance(period, str) or not re.fullmatch(r"20\d\dQ[1-4]", period):
        raise ValueError("INVALID_FINANCIAL_PERIOD")
    return int(period[:4]) * 4 + int(period[-1])


def evaluate_signal(snapshot, *, decision_at, require_margin=True):
    """A shadow screen, not a substitute for original evidence inspection."""
    from tw_model_v880.insider_accumulation import evaluate_insider_accumulation

    signal_at = aware(decision_at)
    i = evaluate_insider_accumulation(snapshot.get("insider_months", []),
                                     decision_at=decision_at,
                                     issued_shares=snapshot.get("issued_shares"),
                                     issued_shares_asof=snapshot.get("shares_asof"),
                                     issued_shares_original_sha256=snapshot.get("shares_original_sha256"))
    if i["status"] != "RESEARCH_WATCH_REQUIRES_INDEPENDENT_AUDIT":
        return blocked("INSIDER_" + i["status"], insider_status=i["status"])
    if snapshot.get("contemporaneous_footwear_universe_verified") is not True:
        return blocked("PENDING_CONTEMPORANEOUS_INDUSTRY_UNIVERSE")
    price = snapshot.get("trailing_price_evidence") or {}
    if not (source_asof(price, signal_at) and price.get("calendar_sessions_verified") is True):
        return blocked("PENDING_TRADING_CALENDAR_PRICE_PIT_ORIGINAL")
    closes = price.get("closes")
    if not isinstance(closes, list) or len(closes) != POLICY["low_price_window_sessions"]:
        return blocked("PENDING_COMPLETE_252_SESSION_PRICE_WINDOW")
    prev = None
    values = []
    for row in closes:
        try:
            when = date.fromisoformat(row["date"])
            v = row["close"]
        except (KeyError, TypeError, ValueError):
            return blocked("INVALID_PRICE_SESSION")
        if not (type(v) in (int, float) and math.isfinite(v) and v > 0):
            return blocked("INVALID_PRICE_SESSION")
        if (prev is not None and when <= prev) or when >= signal_at.date():
            return blocked("FUTURE_DUPLICATE_OR_SAME_DAY_CLOSE")
        prev = when
        values.append(v)
    if max(values) == min(values):
        return blocked("PRICE_RANGE_UNDEFINED")
    position = (values[-1] - min(values)) / (max(values) - min(values))
    if position > POLICY["max_trailing_range_position"]:
        return blocked("PRICE_NOT_IN_BOTTOM_20_PERCENT", trailing_price_position=round(position, 6))
    if require_margin is False:
        # Strategy A: enter on market-buying persistence + low price alone.
        # Do not access future financial quarters or require a GM rebound.
        return {"status": "EARLY_RESEARCH_SIGNAL_REQUIRES_INDEPENDENT_ORIGINAL_AUDIT",
                "eligible_research_signal": True, "signal_variant": "A_EARLY",
                "gross_margin_gate": "NOT_REQUIRED",
                "trailing_price_position": round(position, 6),
                "three_month_insider_net_lots": i["three_month_net_lots"],
                "formal_aplus_or_exit_changed": False,
                "forward_returns_certified": False,
                "earliest_fill": "NEXT_VERIFIED_TRADE_AFTER_SIGNAL_NOT_SAME_CLOSE"}
    if require_margin is not True:
        raise ValueError("REQUIRE_MARGIN_MUST_BE_BOOLEAN")
    quarters = snapshot.get("gross_margin_quarters")
    if not isinstance(quarters, list) or len(quarters) != 2:
        return blocked("PENDING_TWO_PUBLISHED_QUARTER_MARGINS")
    if not all(source_asof(r, signal_at) and r.get("single_quarter") is True for r in quarters):
        return blocked("PENDING_ORIGINAL_QUARTER_PIT")
    before, after = quarters
    if _quarter_index(after.get("period")) != _quarter_index(before.get("period")) + 1:
        return blocked("NONCONSECUTIVE_QUARTERS")
    if any(type(r.get(k)) not in (int, float) or not math.isfinite(r[k]) for r in quarters for k in ("revenue", "gross_profit")):
        return blocked("INVALID_MARGIN_INPUT")
    if any(r["revenue"] <= 0 for r in quarters):
        return blocked("INVALID_MARGIN_REVENUE")
    gm_delta_pp = 100 * (after["gross_profit"] / after["revenue"] - before["gross_profit"] / before["revenue"])
    if gm_delta_pp < POLICY["min_gm_delta_percentage_points"]:
        return blocked("GROSS_MARGIN_NOT_RECOVERING_BY_1PP", gm_delta_pp=round(gm_delta_pp, 5))
    return {"status": "RESEARCH_SIGNAL_REQUIRES_INDEPENDENT_ORIGINAL_AUDIT",
            "signal_variant": "B_GM_CONFIRMED",
            "eligible_research_signal": True, "formal_aplus_or_exit_changed": False,
            "forward_returns_certified": False,
            "trailing_price_position": round(position, 6), "gm_delta_pp": round(gm_delta_pp, 5),
            "three_month_insider_net_lots": i["three_month_net_lots"],
            "earliest_fill": "NEXT_VERIFIED_TRADE_AFTER_SIGNAL_NOT_SAME_CLOSE"}


def wilson_interval(wins, n, z=1.95996398454):
    if type(wins) is not int or type(n) is not int or n < 1 or not 0 <= wins <= n:
        raise ValueError("INVALID_BINOMIAL_COUNTS")
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1-p) / n + z*z / (4*n*n)) / d
    return round(c-m, 6), round(c+m, 6)


def evaluate_outcomes(events, *, evaluated_at):
    """Fail-closed one-year comparison; no invented returns for missing events.

    Inputs must come from separately audited matched executions; this function
    never certifies caller-supplied boolean attestations as external evidence.
    """
    now = aware(evaluated_at)
    if not isinstance(events, list):
        raise ValueError("INVALID_EVENTS")
    if not events:
        return {"status": "NO_VERIFIED_MATURED_EVENTS", "n": 0,
                "win_rate": None, "excess_return_pp_mean": None,
                "wilson_95pct": None, "reject_target_60pct": None,
                "formal_aplus_or_exit_changed": False}
    last_exits = {}
    observed = []
    for event in sorted(events, key=lambda r: (r.get("signal_at", ""), r.get("code", ""))):
        try:
            signal, entry, exit_time = (aware(event[k]) for k in ("signal_at", "entry_at", "exit_at"))
            code = event["code"]
        except (ValueError, TypeError, KeyError):
            return blocked("PENDING_OUTCOME_DATES_ISSUER", win_rate=None, n=None)
        if not (isinstance(code, str) and re.fullmatch(r"\d{4}", code)):
            return blocked("PENDING_ISSUER_ID", win_rate=None, n=None)
        if (signal.date() < date.fromisoformat(POLICY["signal_registration_date"]) or
                entry <= signal or exit_time <= entry or
                (exit_time.date() - entry.date()).days < POLICY["holding_calendar_days"] or
                exit_time > now):
            return blocked("UNMATURED_OR_NONEXECUTABLE_12M_HORIZON", win_rate=None, n=None)
        if code in last_exits and signal <= last_exits[code]:
            return blocked("OVERLAPPING_ISSUER_HOLDING_WINDOWS", win_rate=None, n=None)
        last_exits[code] = exit_time
        if (event.get("originals_independently_audited") is not True or
                event.get("first_eligible_open_verified") is not True or
                event.get("issuer_and_0050_action_registers_complete") is not True or
                event.get("matched_execution_dates_verified") is not True or
                event.get("pre_registered_rule_asof_signal") is not True or
                not all(digest_ok(event.get(k)) for k in
                        ("issuer_execution_receipt_sha256", "benchmark_execution_receipt_sha256",
                         "corporate_action_receipt_sha256"))):
            return blocked("PENDING_INDEPENDENT_MATCHED_EXECUTION_AUDIT", win_rate=None, n=None)
        try:
            if aware(event["outcome_first_captured_at"]) > now:
                return blocked("FUTURE_OUTCOME_ARCHIVE", win_rate=None, n=None)
        except (KeyError, ValueError):
            return blocked("PENDING_OUTCOME_ARCHIVE_RECEIPT", win_rate=None, n=None)
        model = event.get("stock_net_total_return")
        benchmark = event.get("etf_0050_net_total_return")
        if any(type(x) not in (int, float) or not math.isfinite(x) or x < -1 for x in (model, benchmark)):
            return blocked("PENDING_ADJUSTED_NET_RETURN", win_rate=None, n=None)
        observed.append((model, benchmark))
    n = len(observed)
    wins = sum(stock > benchmark for stock, benchmark in observed)
    if n < POLICY["minimum_independent_matured_events"]:
        return {"status": "INSUFFICIENT_INDEPENDENT_MATURED_EVENTS", "n": n,
                "minimum_events": POLICY["minimum_independent_matured_events"],
                "win_rate": None, "excess_return_pp_mean": None,
                "wilson_95pct": None, "reject_target_60pct": None,
                "formal_aplus_or_exit_changed": False}
    low, high = wilson_interval(wins, n)
    return {"status": "DESCRIPTIVE_AUDITED_OUTCOMES_NOT_CAUSAL_PROOF",
            "n": n, "wins": wins, "win_rate": round(wins/n, 6),
            "excess_return_pp_mean": round(100*sum(a-b for a,b in observed)/n, 6),
            "wilson_95pct": [low, high],
            "sixty_pct_win_rate_supported_at_95pct": low > POLICY["test_target_outperformance_probability"],
            "formal_aplus_or_exit_changed": False,
            "return_input_attestations_not_independently_checked_by_this_function": True}
