"""Price-vintage guard aware of bounded, *dated* confirmed exchange closures.

A fully observed exchange closure can remove a false weekday gap, but never
proves a security was tradable or guarantees a current close. The list of
closures is not a certified full historical exchange calendar.
"""
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

TAIPEI=ZoneInfo("Asia/Taipei")
SCHEMA="DATED_PARTIAL_TW_EQUITY_EXCHANGE_CLOSURES_V1"
ALLOWED_NEWS_HOSTS={"www.cna.com.tw","wwwc.twse.com.tw","www.pocket.tw"}


def load_dated_exchange_closures(root):
    """Load source-scoped closed sessions; absent file retains old heuristic."""
    path=Path(root)/"config/daily_price_closures_v1.json"
    if not path.is_file():
        return []
    record=json.loads(path.read_text(encoding="utf-8"))
    if (record.get("schema")!=SCHEMA or record.get("scope")!="TWSE_AND_TPEX"
        or record.get("complete_annual_calendar") is not False):
        raise ValueError("UNVERIFIED_COMPLETE_EXCHANGE_CALENDAR_OR_SCHEMA")
    rows=record.get("closing_sessions")
    if not isinstance(rows,list) or len(rows)>100:
        raise ValueError("EXCHANGE_CLOSURE_LEDGER_INVALID")
    dates=set()
    for row in rows:
        try:
            day=dt.date.fromisoformat(row["date"])
            published=dt.datetime.fromisoformat(row["observed_public_at"])
            parsed=urlsplit(row["source_url"])
        except (ValueError,KeyError,TypeError) as exc:
            raise ValueError("EXCHANGE_CLOSURE_EVIDENCE_MALFORMED") from exc
        if (day.isoformat() in dates or day.weekday()>=5 or published.tzinfo is None
            or published.date()>day
            or parsed.scheme!="https" or parsed.hostname not in ALLOWED_NEWS_HOSTS
            or parsed.username is not None or parsed.password is not None
            or row.get("markets")!=["TWSE","TPEX"]
            or row.get("publisher_date_is_not_historical_trade_snapshot") is not True):
            raise ValueError("EXCHANGE_CLOSURE_EVIDENCE_INVALID_OR_DUPLICATED")
        dates.add(day.isoformat())
    return rows


def _clock(estimate_vintage):
    instant=dt.datetime.fromisoformat(str(estimate_vintage).replace("Z","+00:00"))
    if instant.tzinfo is None:
        raise ValueError("FRESHNESS_ASOF_TIMEZONE_REQUIRED")
    return instant


def possible_completed_weekday_sessions(estimate_vintage,reference_close_day):
    instant=_clock(estimate_vintage)
    today=instant.astimezone(TAIPEI)
    ref=dt.date.fromisoformat(str(reference_close_day))
    if ref>today.date():
        raise ValueError("FUTURE_REFERENCE_PRICE")
    # Before 16:00 do not assume an exchange session was completed.
    end=(today.date() if today.weekday()<5 and today.hour>=16
         else today.date()-dt.timedelta(days=1))
    day=ref+dt.timedelta(days=1)
    result=[]
    while day<=end:
        if day.weekday()<5:
            result.append(day.isoformat())
        day+=dt.timedelta(days=1)
        if len(result)>25:
            raise ValueError("FRESHNESS_TOO_MANY_POSSIBLE_SESSIONS")
    return result


def assess_price_freshness(estimate_vintage,reference_close_day,closed_sessions=None):
    potential=possible_completed_weekday_sessions(estimate_vintage,reference_close_day)
    instant=_clock(estimate_vintage)
    # Only closures publicly confirmed at or before the modeled as-of time
    # are eligible. A retrospective ledger cannot leak a later announcement
    # into a historical model vintage.
    observed=[]
    for record in (closed_sessions or []):
        pub=dt.datetime.fromisoformat(record["observed_public_at"])
        if pub.tzinfo is None:
            raise ValueError("CLOSURE_EVIDENCE_CLOCK_UNAWARE")
        if pub<=instant and record["date"] in potential:
            observed.append(record["date"])
    if len(observed)!=len(set(observed)):
        raise ValueError("DUPLICATE_CLOSURE_OBSERVATION")
    missing=[day for day in potential if day not in set(observed)]
    status=("POSSIBLY_STALE_CONFIRM_EXCHANGE_SESSION" if missing else
            "KNOWN_CLOSURES_ELIMINATE_WEEKDAY_GAP_NOT_TRADING_CERTIFIED"
            if observed else "NO_POTENTIAL_WEEKDAY_PRICE_GAP")
    return {
        "status":status,
        "reference_close_date":reference_close_day,
        "estimate_vintage":estimate_vintage,
        "potentially_missing_weekdays":missing,
        "possible_completed_weekday_gap_count":len(missing),
        "known_confirmed_closed_weekdays":sorted(observed),
        "partial_exchange_closure_evidence_used":bool(observed),
        "quote_is_confirmed_latest_session":False,
        "market_holiday_calendar_certified":False,
        "equity_source_may_be_stale":bool(missing),
        "quotes_imputed_or_backfilled":False,
        "research_model_2027_unchanged":True,
        "formal_Aplus_status_unchanged":True,
        "note":("Bounded TWSE/TPEx closures exclude confirmed nontrading"
                " weekdays only after their public announcement. Unknown days"
                " remain potential gaps. No complete calendar, inferred prices,"
                " security-specific tradability, or official fresh-close"
                " certification is claimed.")
    }
