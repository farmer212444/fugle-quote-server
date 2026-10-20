"""Conservative, point-in-time friendly cycle discovery research.

This module never certifies an A+ rating. Missing observations are not
silently treated as positive evidence. Weights are provisional pending
out-of-sample validation.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from typing import Mapping, Optional
import re

_TAIPEI = timezone(timedelta(hours=8))
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

def _cutoff_time(value: str) -> datetime:
    """Use Taipei end of day for date-only research, never for intraday signals."""
    if not isinstance(value, str):
        raise ValueError("ASOF_TIME_INVALID")
    if _DATE_RE.fullmatch(value):
        return datetime.combine(date.fromisoformat(value), time.max, _TAIPEI)
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("ASOF_TIMEZONE_REQUIRED")
    return instant

def _published_by(value: object, cutoff: datetime) -> bool:
    """Unknown release time on a date is conservatively that day's end."""
    try:
        return _cutoff_time(value) <= cutoff
    except (ValueError, TypeError, OverflowError):
        return False

WEIGHTS = {
    "revenue_acceleration": 0.20,
    "peer_breadth": 0.20,
    "margin_leading": 0.20,
    "normalized_value": 0.20,
    "balance_sheet": 0.10,
    "relative_strength": 0.10,
}
CYCLICAL_INDUSTRY_TERMS = (
    "航運", "鋼鐵", "建材營造", "電子通路", "電器電纜",
    "製鞋", "鞋", "運動休閒", "紡織", "成衣", "塑膠", "化學", "造紙",
)

@dataclass(frozen=True)
class CycleSignal:
    score: Optional[float]
    observed_weight: float
    missing: tuple[str, ...]
    status: str
    a_plus_certified: bool = False

def is_cyclical(industry: str) -> bool:
    return any(term in (industry or "") for term in CYCLICAL_INDUSTRY_TERMS)

def score_cycle(observations: Mapping[str, Optional[float]],
                *, asof: str, latest_available_at: Mapping[str, str],
                min_coverage: float = 0.80) -> CycleSignal:
    """Inputs are normalized 0..1 evidence scores with publication timestamps.

    Excludes information released after asof. Date-only asof means Taipei
    end of day; date-only releases become available only at that day's end.
    No model signal is an A+ approval.
    """
    cutoff = _cutoff_time(asof)
    if (isinstance(min_coverage, bool) or not isinstance(min_coverage, (int, float))
            or not isfinite(min_coverage) or not 0 < min_coverage <= 1):
        raise ValueError("CYCLE_COVERAGE_THRESHOLD_INVALID")
    weighted = 0.0
    covered = 0.0
    missing = []
    for key, weight in WEIGHTS.items():
        value = observations.get(key)
        released = latest_available_at.get(key)
        if (value is None or not _published_by(released, cutoff)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value) or not 0 <= value <= 1):
            missing.append(key)
            continue
        weighted += weight * float(value)
        covered += weight
    if covered + 1e-12 < min_coverage:
        return CycleSignal(None, round(covered, 6), tuple(missing),
                           "INSUFFICIENT_PIT_EVIDENCE")
    # Missing evidence is scored as zero, never renormalized into a perfect score.
    score = round(100 * weighted, 2)
    return CycleSignal(score, round(covered, 6), tuple(missing),
                       "EARLY_DISCOVERY_RESEARCH_ONLY")
