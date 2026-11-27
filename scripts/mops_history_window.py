"""Bounded, fail-closed quarter selection for official MOPS detail backfill.

A dated normalized summary is not issuer filing PIT verification. Historical
detail collected through this schedule remains research-only.
"""
import calendar
import datetime as dt
import re


def desired_backfill_quarters(scan, *, today=None, seed_quarter="2026Q2", count=8):
    if not isinstance(scan, dict) or scan.get("status") != "ALL_BATCHES_PRESENT_UNAUDITED":
        raise ValueError("CURRENT_QUARTER_SCAN_INCOMPLETE")
    expected = scan.get("expected_market_quarter_statement_batches")
    verified = scan.get("verified_batches")
    if not isinstance(expected, int) or expected <= 0 or verified != expected:
        raise ValueError("CURRENT_QUARTER_BATCHES_UNVERIFIED")
    label = scan.get("last_eligible_quarter", "")
    matched = re.fullmatch(r"(20\d{2})-Q([1-4])", str(label))
    if matched is None:
        raise ValueError("CURRENT_QUARTER_LABEL_INVALID")
    year, quarter = map(int, matched.groups())
    now = today or dt.date.today()
    if not isinstance(now, dt.date):
        raise ValueError("ASOF_DATE_INVALID")
    close_month = quarter * 3
    quarter_end = dt.date(year, close_month, calendar.monthrange(year, close_month)[1])
    if quarter_end >= now:
        raise ValueError("CURRENT_QUARTER_NOT_YET_CLOSED")
    if not isinstance(count, int) or not 1 <= count <= 16:
        raise ValueError("QUARTER_WINDOW_INVALID")
    index = year * 4 + quarter - 1
    window = [f"{(index - k) // 4:04d}Q{(index - k) % 4 + 1}"
              for k in range(count)]
    if seed_quarter and seed_quarter not in window:
        # The external seed is not part of the active forecast window anymore.
        # Do not pretend an uncollected current quarter is separately seeded.
        return window
    return [quarter_key for quarter_key in window if quarter_key != seed_quarter]
