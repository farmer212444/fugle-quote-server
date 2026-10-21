"""Explicit price-vintage warning for live Taiwan-stock research.

Only a *weekday heuristic*. Without an official exchange holiday calendar and
confirmed late-session publications, a warning does NOT prove missing trades.
Never impute prices, silently alter Base targets, or certify tradability.
"""
import datetime as dt
from zoneinfo import ZoneInfo

TAIPEI=ZoneInfo("Asia/Taipei")


def possible_completed_weekday_sessions(estimate_vintage,reference_close_day):
    instant=dt.datetime.fromisoformat(str(estimate_vintage).replace("Z","+00:00"))
    if instant.tzinfo is None:
        raise ValueError("FRESHNESS_ASOF_TIMEZONE_REQUIRED")
    today=instant.astimezone(TAIPEI)
    ref=dt.date.fromisoformat(str(reference_close_day))
    if ref>today.date():
        raise ValueError("FUTURE_REFERENCE_PRICE")
    # Do not claim an exchange session is completed before 16:00 local time.
    # This is a generous operational cutoff (not an observed publication time).
    end=today.date() if (today.weekday()<5 and today.hour>=16) else today.date()-dt.timedelta(days=1)
    candidate=ref+dt.timedelta(days=1)
    days=[]
    while candidate<=end:
        if candidate.weekday()<5:
            days.append(candidate.isoformat())
        candidate+=dt.timedelta(days=1)
        if len(days)>25:
            raise ValueError("FRESHNESS_TOO_MANY_POSSIBLE_SESSIONS")
    return days


def assess_price_freshness(estimate_vintage,reference_close_day):
    missing=possible_completed_weekday_sessions(estimate_vintage,reference_close_day)
    status=("POSSIBLY_STALE_CONFIRM_EXCHANGE_SESSION" if missing
            else "NO_POTENTIAL_WEEKDAY_PRICE_GAP")
    return {
        "status":status,
        "reference_close_date":reference_close_day,
        "estimate_vintage":estimate_vintage,
        "potentially_missing_weekdays":missing,
        "possible_completed_weekday_gap_count":len(missing),
        "quote_is_confirmed_latest_session":False,
        "market_holiday_calendar_certified":False,
        "equity_source_may_be_stale":bool(missing),
        "quotes_imputed_or_backfilled":False,
        "2027_research_model_unchanged":True,
        "formal_Aplus_status_unchanged":True,
        "note":("Weekday-only screening does not establish an actual exchange"
                " session or data delivery time. Confirm TWSE/TPEx official"
                " daily records before treating prices as current or tradable.")
    }
