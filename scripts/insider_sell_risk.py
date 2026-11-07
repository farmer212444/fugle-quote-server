"""Research-only MOPS insider-selling pressure overlay.

The marketwide collector has already checked original gzip bytes, SHA-256,
holdings rollforwards and market-trade columns. This module does NOT re-certify
holder identity, historical PIT, causal predictive power or trading signals.
"""
import datetime as dt
import json
import math
from pathlib import Path

TW = dt.timezone(dt.timedelta(hours=8))
MISSING = "SELL_SOURCE_UNAVAILABLE_OR_NOT_ASOF_SAFE"
EFFECT = "RESEARCH_REVIEW_ONLY_NO_EPS_PE_APLUS_EXIT_CHANGE"


def load_sell_feed(path, asof):
    """Do not use any ranking snapshot created after the model's as-of instant.

    A YYYY-MM-DD date without clock time means its *start*, not an invented
    end-of-day data availability. This is deliberately conservative.
    """
    empty = {"status": MISSING, "records": {}, "months": [],
             "holder_identity_formal_certification": False}
    path = Path(path)
    if not path.is_file():
        return empty
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        when = dt.datetime.fromisoformat(doc["attempted_at_utc"].replace("Z", "+00:00"))
        cutoff = dt.datetime.fromisoformat(asof)
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=TW)
        if when.tzinfo is None or when > cutoff:
            return dict(empty, status="INSIDER_SELL_SNAPSHOT_NOT_AVAILABLE_AT_ASOF")
        if doc.get("schema") != "INSIDER_MARKETWIDE_YTD_V2":
            return dict(empty, status="INSIDER_SELL_SOURCE_SCHEMA_MISMATCH")
        if (doc.get("holder_identity_formal_certification") is not False
                or doc.get("marketwide_rank_claim_permitted") is not False):
            return dict(empty, status="INSIDER_SELL_UNEXPECTED_SOURCE_CERTIFICATION")
        months = doc.get("months")
        sellers = doc.get("all_observed_selling")
        complete = doc.get("all_complete_sample")
        if not isinstance(months, list) or not isinstance(sellers, list) or not isinstance(complete, list):
            return dict(empty, status="INSIDER_SELL_FIELDS_NOT_AVAILABLE")
        records = {}
        for row in sellers:
            if isinstance(row, dict) and isinstance(row.get("code"), str):
                records[row["code"]] = row
        # Only an actual full-scope SHA-checked row can establish zero selling.
        for row in complete:
            if isinstance(row, dict) and isinstance(row.get("code"), str):
                records.setdefault(row["code"], row)
        return {"status": "ASOF_VALID_RESEARCH_ONLY_UNCERTIFIED_HOLDER_IDENTITY",
                "records": records, "months": months,
                "attempted_at_utc": doc["attempted_at_utc"],
                "holder_identity_formal_certification": False,
                "marketwide_rank_claim_permitted": False}
    except (OSError, ValueError, KeyError, TypeError):
        return dict(empty, status="INSIDER_SELL_INVALID_SOURCE")


def assess_sell_risk(record, source_status):
    """Exploratory thresholds, not fitted trading or return probabilities."""
    unknown = {"status": source_status, "tier": "UNKNOWN",
               "needs_manual_review": False, "effect": EFFECT,
               "historical_PIT_certified": False, "holder_identity_certified": False}
    if not isinstance(record, dict):
        return dict(unknown, reason="NO_VERIFIED_SELL_OBSERVATION_FOR_ISSUER")
    try:
        sell_pct = float(record["sell_pct_of_issued"])
        net_sell_pct = float(record["net_sell_pct_of_issued"])
        sell_months = int(record["negative_net_months"])
        streak = int(record["max_consecutive_net_sell_months"])
        observed = int(record["observed_month_count"])
        expected = int(record["expected_ytd_month_count"])
        complete = record["year_to_date_complete"] is True
        if not (0 <= sell_pct <= 100 and -100 <= net_sell_pct <= 100 and
                0 <= streak <= sell_months <= observed <= expected and expected > 0):
            raise ValueError("INVALID_SELL_AGGREGATE")
    except (ValueError, KeyError, TypeError):
        return dict(unknown, reason="INVALID_SELL_AGGREGATE")
    # Requiring net sales distinguishes true distribution from high-volume
    # but offsetting purchases. One large disposal gets reviewed separately.
    high = net_sell_pct >= 0.75 or (net_sell_pct >= 0.35 and sell_months >= 2)
    watch = net_sell_pct >= 0.20 or (sell_pct >= 1.00 and sell_months >= 1)
    tier = "HIGH_REVIEW" if high else "WATCH_REVIEW" if watch else "NO_MATERIAL_OBSERVED_SIGNAL"
    return {"status": "OBSERVED_MONTHS_VERIFIED_IDENTITY_AND_PIT_PENDING",
            "tier": tier, "needs_manual_review": high or watch,
            "sell_pct_of_issued": sell_pct,
            "net_sell_pct_of_issued": net_sell_pct,
            "net_sell_months": sell_months,
            "max_consecutive_net_sell_months": streak,
            "observed_month_count": observed,
            "expected_ytd_month_count": expected,
            "year_to_date_complete": complete,
            "missing_months": record.get("missing_months", []),
            "sell_amount_is_observed_months_only": not complete,
            "holder_identity_certified": False,
            "historical_PIT_certified": False,
            "role_concentration_verified": False,
            "effect": EFFECT,
            "rule_status": "EXPLORATORY_THRESHOLDS_NOT_WALK_FORWARD_VALIDATED"}


def operating_weakness_context(row):
    """Read only already-computed financial facts; never forecast or score.

    Absence of comparable periods is unknown, not evidence of strength.
    Revenue is a signed year-on-year fraction, while YTD gross margin uses
    the model's same-period comparison. No dated price-momentum claim is made.
    """
    signals = []
    trend = (row.get("revenue_bridge") or {}).get("trend_inputs") or {}
    yoy = trend.get("latest_month_yoy")
    if (isinstance(yoy, (int, float)) and not isinstance(yoy, bool)
            and math.isfinite(yoy) and yoy < 0):
        signals.append("LATEST_REVENUE_YOY_NEGATIVE")
    margins = row.get("margin_bridge") or {}
    now = margins.get("current_ytd_gm")
    prior = margins.get("prior_ytd_gm")
    if (all(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) for value in (now, prior))
            and now < prior):
        signals.append("YTD_GROSS_MARGIN_BELOW_SAME_PERIOD_PRIOR_YEAR")
    return signals


def annotate_issuer_rows(rows, feed):
    """Add research warnings only; never change formal ranking or certificates."""
    watched = []
    by_code = feed.get("records", {})
    for row in rows:
        alert = assess_sell_risk(by_code.get(row.get("code")), feed["status"])
        # Corroboration is visible only for source-backed selling observations.
        # It never changes sell tiers, earnings, estimates or formal approvals.
        signals = operating_weakness_context(row) if alert["tier"] != "UNKNOWN" else []
        alert["operating_context_flags"] = signals
        alert["operating_crosscheck_is_research_only"] = True
        alert["dated_price_trend_verified"] = False
        row["insider_sell_overlay"] = alert
        if alert["needs_manual_review"]:
            row.setdefault("warning_flags", [])
            if "INSIDER_SELL_RESEARCH_REVIEW_REQUIRED" not in row["warning_flags"]:
                row["warning_flags"].append("INSIDER_SELL_RESEARCH_REVIEW_REQUIRED")
            if (signals and "INSIDER_SELL_AND_OPERATING_WEAKNESS_SHADOW_REVIEW"
                    not in row["warning_flags"]):
                row["warning_flags"].append("INSIDER_SELL_AND_OPERATING_WEAKNESS_SHADOW_REVIEW")
            watched.append({"code": row["code"], "name": row.get("name"),
                            "market": row.get("market"), **alert})
    watched.sort(key=lambda x: (-x["net_sell_pct_of_issued"],
                                -x["sell_pct_of_issued"], x["code"]))
    return watched
