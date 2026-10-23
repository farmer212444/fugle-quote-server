#!/usr/bin/env python3
"""PIT-gated TW buyback event study. Research only; never changes A+ or orders.

This executable deliberately REQUIRES independently supplied historical event,
issuer total-return, and 0050 total-return CSV evidence. It never substitutes
unadjusted closes, today's survivors, or future execution rates.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

HORIZONS = (3, 6, 12)
START, END = date(2020, 1, 1), date(2025, 12, 31)
COSTS = dict(buy_fee=0.000285, sell_fee=0.000285, sell_tax=0.003,
             buy_slippage=0.001, sell_slippage=0.001)
REQUIRED = {
    "events": ("event_id", "stock_id", "event_type", "disclosed_at",
               "source_url", "source_sha256", "execution_rate"),
    "prices": ("date", "stock_id", "total_return_close", "corporate_actions_verified",
               "source_id"),
    "benchmark": ("date", "total_return_index", "total_return_verified", "source_id"),
}


def stamp(text):
    value = datetime.fromisoformat(text)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("DISCLOSURE_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value


def plus_months(day, months):
    total = day.year * 12 + day.month - 1 + months
    year, m = divmod(total, 12)
    m += 1
    return date(year, m, min(day.day, calendar.monthrange(year, m)[1]))


def csv_rows(path, kind):
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not set(REQUIRED[kind]).issubset(set(reader.fieldnames or [])):
            raise ValueError("REQUIRED_COLUMNS_MISSING_" + kind)
        return list(reader)


def parse_positive(v):
    x = float(v)
    if not math.isfinite(x) or x <= 0:
        raise ValueError("INVALID_TOTAL_RETURN_LEVEL")
    return x


def verified(v):
    return str(v).strip().lower() in ("1", "true", "yes")


def load_prices(records):
    by_issuer = defaultdict(dict)
    for r in records:
        key = r["stock_id"].strip()
        d = date.fromisoformat(r["date"])
        if not key or not r["source_id"].strip():
            raise ValueError("MISSING_PRICE_SOURCE")
        if d in by_issuer[key]:
            raise ValueError("DUPLICATED_ISSUER_DATE")
        by_issuer[key][d] = (parse_positive(r["total_return_close"]),
                             verified(r["corporate_actions_verified"]))
    return by_issuer


def load_benchmark(records):
    rows = {}
    for r in records:
        d = date.fromisoformat(r["date"])
        if not r["source_id"].strip():
            raise ValueError("MISSING_BENCHMARK_SOURCE")
        if d in rows:
            raise ValueError("DUPLICATED_BENCHMARK_DATE")
        rows[d] = (parse_positive(r["total_return_index"]),
                   verified(r["total_return_verified"]))
    return rows


def load_events(records):
    seen, out = set(), []
    for r in records:
        eid, issuer = r["event_id"].strip(), r["stock_id"].strip()
        typ = r["event_type"].strip().lower()
        if not eid or not issuer or eid in seen:
            raise ValueError("BAD_OR_DUPLICATE_EVENT_ID")
        seen.add(eid)
        if typ not in ("announce", "completion"):
            raise ValueError("EVENT_TYPE_MUST_BE_ANNOUNCE_OR_COMPLETION")
        disclosed = stamp(r["disclosed_at"])
        if not r["source_url"].startswith("https://"):
            raise ValueError("EVENT_SOURCE_URL_REQUIRED")
        sha = r["source_sha256"].strip().lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("EVENT_ORIGINAL_SHA256_REQUIRED")
        rate = r["execution_rate"].strip()
        if typ == "announce" and rate:
            raise ValueError("FUTURE_EXECUTION_RATE_IN_ANNOUNCEMENT")
        if typ == "completion" and (not rate or not 0 <= float(rate) <= 1):
            raise ValueError("COMPLETION_EXECUTION_RATE_REQUIRED_0_TO_1")
        if START <= disclosed.date() <= END:
            out.append(dict(event_id=eid, stock_id=issuer, event_type=typ,
                            disclosed_at=disclosed))
    return out


def next_after(dates, day):
    return next((d for d in dates if d > day), None)


def first_on_or_after(dates, day):
    return next((d for d in dates if d >= day), None)


def net_return(start, end):
    entry = start * (1 + COSTS["buy_fee"] + COSTS["buy_slippage"])
    exit_value = end * (1 - COSTS["sell_fee"] - COSTS["sell_tax"]
                        - COSTS["sell_slippage"])
    return exit_value / entry - 1


def stats(items):
    if not items:
        return dict(n=0, win_rate_pct=None, beat_0050_pct=None,
                    mean_net_pct=None, median_net_pct=None,
                    mean_excess_pct=None, median_excess_pct=None)
    rs = [x["net_return"] for x in items]
    alphas = [x["alpha_0050"] for x in items]
    return dict(
        n=len(items),
        win_rate_pct=100 * sum(x > 0 for x in rs) / len(rs),
        beat_0050_pct=100 * sum(x > 0 for x in alphas) / len(alphas),
        mean_net_pct=100 * statistics.mean(rs),
        median_net_pct=100 * statistics.median(rs),
        mean_excess_pct=100 * statistics.mean(alphas),
        median_excess_pct=100 * statistics.median(alphas),
    )


def study(events, prices, benchmark, as_of):
    # Reconstructed event study, not a forward-registered model prediction.
    # Events after as_of cannot enter the study even if source file contains them.
    valid_events = [e for e in events if e["disclosed_at"].date() <= as_of]
    observed, blocked, immature = [], [], []
    benchmark_dates = sorted(d for d in benchmark if d <= as_of)
    last_date = max(benchmark_dates, default=None)
    for event in valid_events:
        sid = event["stock_id"]
        issuer = prices.get(sid, {})
        issuer_dates = sorted(d for d in issuer if d <= as_of)
        entry = next_after(issuer_dates, event["disclosed_at"].date())
        segment = ("DEV_2020_2023" if event["disclosed_at"].year <= 2023
                   else "OOS_2024_2025")
        for months in HORIZONS:
            label = dict(event_id=event["event_id"], stock_id=sid,
                         event_type=event["event_type"],
                         segment=segment, horizon_months=months)
            if entry is None or entry not in benchmark:
                blocked.append(dict(**label, reason="MISSING_NEXT_SESSION_MATCHED_ENTRY"))
                continue
            mature_date = plus_months(entry, months)
            if last_date is None or mature_date > min(last_date, as_of):
                immature.append(dict(**label, maturity_date=str(mature_date)))
                continue
            exit_date = first_on_or_after(issuer_dates, mature_date)
            if exit_date is None or exit_date not in benchmark:
                blocked.append(dict(**label, reason="MISSING_MATCHED_EXIT_OR_DELISTING"))
                continue
            # A suspended/delisted issuer must not be notionally sold months later.
            if (exit_date - mature_date).days > 7:
                blocked.append(dict(**label, reason="STALE_EXIT_OR_SUSPENDED"))
                continue
            start, start_verified = issuer[entry]
            end, end_verified = issuer[exit_date]
            b0, b0_verified = benchmark[entry]
            b1, b1_verified = benchmark[exit_date]
            if not all((start_verified, end_verified, b0_verified, b1_verified)):
                blocked.append(dict(**label, reason="UNVERIFIED_TOTAL_RETURN_OR_ACTIONS"))
                continue
            ret = net_return(start, end)
            benchmark_ret = b1 / b0 - 1  # Gross 0050 TR: conservative comparator.
            observed.append(dict(**label, entry_date=str(entry),
                                 exit_date=str(exit_date),
                                 net_return=ret, return_0050=benchmark_ret,
                                 alpha_0050=ret - benchmark_ret))
    groups = {}
    for typ in ("announce", "completion"):
        for segment in ("DEV_2020_2023", "OOS_2024_2025"):
            for months in HORIZONS:
                cohort = [r for r in observed if (r["event_type"], r["segment"],
                                                  r["horizon_months"])
                          == (typ, segment, months)]
                key = typ + "_" + segment + "_" + str(months) + "m"
                groups[key] = stats(cohort)
    # Never call an isolated backtest a certified A+, tradable alpha, or complete
    # universe coverage; provenance/eligible universe require an external audit.
    return dict(
        schema="BUYBACK_EVENT_OOS_V1",
        status=("RESEARCH_PARTIAL_OR_BLOCKED" if blocked or immature or not observed
                else "RESEARCH_OBSERVATIONS_UNCERTIFIED"),
        experiment_type="HISTORICAL_EVENT_STUDY_NOT_FORWARD_MODEL_BACKTEST",
        research_only=True, formal_a_plus_unchanged=True, orders_created=False,
        period="2020-01-01_to_2025-12-31",
        holding_months=list(HORIZONS),
        event_count=len(valid_events), observed_count=len(observed),
        blocked_count=len(blocked), immature_count=len(immature),
        grouping=groups, blocked=blocked, immature=immature,
        observations=observed,
        limitations=[
            "Input coverage and historical eligible universe NOT automatically certified",
            "Event public disclosure time must be independently checked",
            "Dividend/split/delisting total-return data require independent audit",
            "Share-adjusted prices are outcomes, never pre-event predictors",
            "0050 benchmark is GROSS total return; issuer returns include fixed costs",
            "Overlapping events are correlated; n is not independent issuer count",
            "No causal claim, and no A+ promotion based on this research alone",
        ],
    )


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--events", default="tw-market-data/buybacks/events_2020_2025.csv")
    p.add_argument("--prices", default="tw-market-data/buybacks/issuer_tr_daily.csv")
    p.add_argument("--benchmark", default="tw-market-data/buybacks/0050_tr_daily.csv")
    p.add_argument("--out", default="tw-market-data/experiments/buyback_event_oos_v1/latest.json")
    p.add_argument("--as-of", default="2026-10-24")
    args = p.parse_args(argv)
    inputs = {"events": Path(args.events), "prices": Path(args.prices),
              "benchmark": Path(args.benchmark)}
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        result = dict(schema="BUYBACK_EVENT_OOS_V1",
                      status="BLOCKED_MISSING_SOURCE_FILES",
                      research_only=True, orders_created=False,
                      formal_a_plus_unchanged=True, missing_inputs=missing,
                      observed_count=0, win_rate_pct=None, beat_0050_pct=None)
    else:
        result = study(load_events(csv_rows(inputs["events"], "events")),
                       load_prices(csv_rows(inputs["prices"], "prices")),
                       load_benchmark(csv_rows(inputs["benchmark"], "benchmark")),
                       date.fromisoformat(args.as_of))
        result["input_sha256"] = {
            key: hashlib.sha256(path.read_bytes()).hexdigest()
            for key, path in inputs.items()}
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                 allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result.get(key) for key in
                      ("schema", "status", "event_count", "observed_count",
                       "blocked_count", "immature_count", "missing_inputs")},
                     ensure_ascii=False))
    return 0 if result["status"] == "RESEARCH_OBSERVATIONS_UNCERTIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
