"""Research-only, fail-closed three-margin PIT signals. No A+ or backtest claims."""
from datetime import datetime

REQUIRED = ("issuer", "quarter", "published_at", "captured_at", "signal_at",
            "gross_margin", "operating_margin", "net_margin",
            "gross_margin_yoy_prev", "operating_margin_yoy_prev",
            "gross_margin_yoy", "operating_margin_yoy", "net_margin_yoy",
            "revenue_yoy_3m", "revenue_yoy_prior_3m", "operating_profit")


def _time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO8601 with timezone")
    t = datetime.fromisoformat(value)
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("timezone required")
    return t


def classify(row):
    """Return signals only when every required field is present and PIT-safe.

    Margin changes are percentage-point changes vs the same quarter a year ago.
    Previous-quarter changes are themselves YoY differences.
    Missing data and invalid source timing block both strategies.
    """
    missing = [key for key in REQUIRED if key not in row or row[key] is None]
    if missing:
        return {"status": "NOT_VALIDATED", "reasons": ["missing:" + ",".join(missing)], "A": False, "B": False}
    if row.get("is_financial", False):
        return {"status": "EXCLUDED", "reasons": ["financial_industry"], "A": False, "B": False}
    try:
        published = _time(row["published_at"])
        captured = _time(row["captured_at"])
        signal = _time(row["signal_at"])
        revised = _time(row["revision_at"]) if row.get("revision_at") else published
        if max(published, captured, revised) > signal:
            return {"status": "NOT_VALIDATED", "reasons": ["lookahead_source"], "A": False, "B": False}
        keys = ("gross_margin", "operating_margin", "net_margin",
                "gross_margin_yoy_prev", "operating_margin_yoy_prev",
                "gross_margin_yoy", "operating_margin_yoy", "net_margin_yoy",
                "revenue_yoy_3m", "revenue_yoy_prior_3m", "operating_profit")
        values = {k: float(row[k]) for k in keys}
        from math import isfinite
        if not all(isfinite(v) for v in values.values()):
            raise ValueError("non-finite")
    except (ValueError, TypeError, OverflowError):
        return {"status": "NOT_VALIDATED", "reasons": ["invalid_input"], "A": False, "B": False}
    a = (values["gross_margin_yoy"] > 0 and
         values["operating_margin_yoy"] > 0 and
         values["net_margin_yoy"] > 0 and
         values["operating_profit"] > 0)
    b = (values["gross_margin_yoy"] > 0 and
         values["gross_margin_yoy_prev"] <= 0 and
         values["operating_margin_yoy"] > values["operating_margin_yoy_prev"] and
         values["revenue_yoy_3m"] > values["revenue_yoy_prior_3m"])
    return {"status": "RESEARCH_SIGNAL", "reasons": [], "A": a, "B": b}
