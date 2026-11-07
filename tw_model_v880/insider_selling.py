"""Fail-closed, research-only overlay for MOPS market selling observations.

The same MOPS query6_1 source already used for insider purchases includes
centralized-market sales. This module independently replays the archived raw
bytes rather than trusting a published aggregate. Historical PIT publication
times and legally distinct holder identity are not certified; the overlay can
only prioritize a human risk review. It cannot change EPS, PE, A+, ranking or
automated Exit.
"""
import datetime as dt
import gzip
import hashlib
import json
import math
import re
from pathlib import Path

from scripts.insider_marketwide import parse_detail


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("TIME_REQUIRED")
    instant = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return instant


def _matching(actual, expected, decimals):
    return (isinstance(actual, (int, float))
            and not isinstance(actual, bool) and math.isfinite(actual)
            and abs(actual - round(expected, decimals)) < 0.0000001)


def _verify_seller(entry, months, base, cutoff):
    """Recalculate every reported month, with source hash and holdings checks."""
    code = entry["code"]
    market = entry["market"]
    shares = entry["issued_shares"]
    observed = entry["observed_months"]
    missing = entry["missing_months"]
    if (not isinstance(code, str) or not re.fullmatch(r"\d{4}", code)
            or market not in ("TWSE", "TPEX")
            or isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0
            or not isinstance(observed, list) or not observed
            or not isinstance(missing, list)
            or observed != [month for month in months if month in observed]
            or missing != [month for month in months if month not in observed]
            or len(set(observed)) != len(observed)):
        raise ValueError("INVALID_ISSUER_SCOPE")
    buy = sell = 0
    sell_months = negative_net_months = 0
    latest_sell_month = None
    for month in observed:
        receipt_path = base / "detail" / month / (code + ".json")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (receipt.get("code") != code or receipt.get("month") != month
                or receipt.get("market") != market):
            raise ValueError("RECEIPT_ISSUER_MONTH_MISMATCH")
        if _timestamp(receipt["first_captured_at"]) > cutoff:
            raise ValueError("SOURCE_CAPTURE_POSTDATES_ESTIMATE")
        archive_name = receipt["raw_archive"]
        digest = receipt["sha256"]
        if (not isinstance(archive_name, str)
                or not re.fullmatch(r"[a-zA-Z0-9_.-]+\.gz", archive_name)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("UNSAFE_OR_MISSING_ARCHIVE_HASH")
        raw = gzip.decompress((receipt_path.parent / archive_name).read_bytes())
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("ORIGINAL_HASH_MISMATCH")
        parsed = parse_detail(raw)
        if (parsed["buy_shares"] != receipt.get("buy_shares")
                or parsed["sell_shares"] != receipt.get("sell_shares")):
            raise ValueError("RECEIPT_NUMERIC_MISMATCH")
        b, s = parsed["buy_shares"], parsed["sell_shares"]
        buy += b
        sell += s
        if s > 0:
            sell_months += 1
            latest_sell_month = month
        if s > b:
            negative_net_months += 1
    if sell <= 0:
        raise ValueError("NOT_ACTUAL_MARKET_SELLER")
    expected = {
        "buy_lots": (buy / 1000, 3),
        "sell_lots": (sell / 1000, 3),
        "net_lots": ((buy - sell) / 1000, 3),
        "buy_pct_of_issued": (buy / shares * 100, 5),
        "sell_pct_of_issued": (sell / shares * 100, 5),
        "net_pct_of_issued": ((buy - sell) / shares * 100, 5),
        "net_sell_pct_of_issued": (max(sell - buy, 0) / shares * 100, 5),
    }
    if any(not _matching(entry.get(k), v, digits) for k, (v, digits) in expected.items()):
        raise ValueError("PUBLISHED_SELLER_AGGREGATE_MISMATCH")
    if (entry.get("sell_months") != sell_months
            or entry.get("negative_net_months") != negative_net_months
            or entry.get("observed_month_count") != len(observed)
            or entry.get("expected_ytd_month_count") != len(months)
            or entry.get("year_to_date_complete") is not (len(observed) == len(months))):
        raise ValueError("PUBLISHED_SELLER_COVERAGE_MISMATCH")
    net_sell_pct = expected["net_sell_pct_of_issued"][0]
    # These are triage bands only. No calibrated trading threshold or score.
    if sell > buy and net_sell_pct >= 1.0 and negative_net_months >= 2:
        triage = "HIGH_REVIEW"
    elif sell > buy:
        triage = "REVIEW"
    else:
        triage = "CONTEXT_ONLY"
    return {
        "status": "SOURCE_HASH_REPLAYED_RESEARCH_ONLY",
        "code": code, "market": market,
        "sell_lots": round(sell / 1000, 3),
        "buy_lots": round(buy / 1000, 3),
        "net_sell_lots": round(max(sell - buy, 0) / 1000, 3),
        "sell_pct_of_issued": round(sell / shares * 100, 5),
        "net_sell_pct_of_issued": round(net_sell_pct, 5),
        "sell_months": sell_months,
        "negative_net_months": negative_net_months,
        "latest_sell_month": latest_sell_month,
        "observed_month_count": len(observed),
        "expected_month_count": len(months),
        "missing_months": missing,
        "year_to_date_complete": len(observed) == len(months),
        "risk_review_priority": triage,
        "formal_holder_identity_certified": False,
        "historical_publication_PIT_certified": False,
        "can_change_EPS_PE_Aplus_or_Exit": False,
        "can_automatically_sell": False,
    }


def load_selling_observations(data_dir, asof):
    """Return source-replayed observations keyed by (market, stock code)."""
    result = {"status": "UNAVAILABLE_NOT_ZERO", "by_code": {},
              "verified_seller_count": 0, "invalid_seller_count": 0,
              "formal_signal_count": 0,
              "can_change_EPS_PE_Aplus_or_Exit": False}
    root = Path(data_dir)
    source = root / "rankings" / "insider_marketwide_latest.json"
    try:
        cutoff = _timestamp(asof)
        report = json.loads(source.read_text(encoding="utf-8"))
        if (report.get("schema") != "INSIDER_MARKETWIDE_YTD_V2"
                or not isinstance(report.get("all_observed_sellers"), list)
                or not isinstance(report.get("months"), list)
                or not report["months"]):
            return result
        if _timestamp(report["attempted_at_utc"]) > cutoff:
            return dict(result, status="SNAPSHOT_POSTDATES_ESTIMATE_NOT_USED")
        months = report["months"]
        if (any(not isinstance(m, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m)
                for m in months) or months != sorted(set(months))):
            return dict(result, status="INVALID_MONTH_SCOPE")
        invalid = 0
        verified = {}
        base = root / "insider"
        for entry in report["all_observed_sellers"]:
            try:
                record = _verify_seller(entry, months, base, cutoff)
                key = (record["market"], record["code"])
                if key in verified:
                    verified.pop(key)
                    invalid += 1
                else:
                    verified[key] = record
            except (OSError, KeyError, ValueError, TypeError, EOFError,
                    json.JSONDecodeError, OverflowError):
                invalid += 1
        return {**result, "status": "RESEARCH_OBSERVATIONS_NOT_FORMALLY_PIT_CERTIFIED",
                "by_code": verified, "verified_seller_count": len(verified),
                "invalid_seller_count": invalid,
                "source_status": report.get("status"),
                "holder_identity_formal_certification": False,
                "marketwide_rank_claim_permitted": False}
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return result


def attach_selling_risk(row, observations):
    """Append a shadow warning to a model row without modifying economics/grades."""
    record = observations["by_code"].get((row.get("market"), row.get("code")))
    if record is None:
        row["insider_selling_risk"] = {
            "status": "NOT_VERIFIED_OR_NOT_OBSERVED_NOT_ZERO",
            "risk_review_priority": "UNKNOWN",
            "can_change_EPS_PE_Aplus_or_Exit": False}
        return row
    risk = dict(record)
    # Operating corroboration is descriptive, not proof of insider motives.
    # These inputs are the model's existing observed financial/revenue context;
    # never change its estimated financials, ranked order, or formal gates.
    context = []
    trend = (row.get("revenue_bridge") or {}).get("trend_inputs") or {}
    latest_revenue_yoy = trend.get("latest_month_yoy")
    if (isinstance(latest_revenue_yoy, (int, float))
            and not isinstance(latest_revenue_yoy, bool)
            and math.isfinite(latest_revenue_yoy)
            and latest_revenue_yoy < 0):
        context.append("LATEST_MONTH_REVENUE_YOY_NEGATIVE")
    margin = row.get("margin_bridge") or {}
    current_margin = margin.get("current_ytd_gm")
    previous_margin = margin.get("prior_ytd_gm")
    if (isinstance(current_margin, (int, float))
            and isinstance(previous_margin, (int, float))
            and not isinstance(current_margin, bool)
            and not isinstance(previous_margin, bool)
            and math.isfinite(current_margin) and math.isfinite(previous_margin)
            and current_margin < previous_margin):
        context.append("YTD_GROSS_MARGIN_BELOW_PRIOR_YEAR")
    risk["operating_context_flags"] = context
    risk["operating_crosscheck_research_only"] = True
    row["insider_selling_risk"] = risk
    if record["risk_review_priority"] in ("HIGH_REVIEW", "REVIEW"):
        row.setdefault("warning_flags", []).append(
            "INSIDER_NET_SELLING_RESEARCH_WATCH_ONLY")
        if context:
            row["warning_flags"].append("INSIDER_SELLING_WITH_OPERATING_WEAKNESS_RESEARCH_ONLY")
    return row
