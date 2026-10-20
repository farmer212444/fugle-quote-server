"""Conservative, point-in-time friendly cycle discovery research.

This module never certifies an A+ rating. Missing observations are not
silently treated as positive evidence. Weights are provisional pending
out-of-sample validation.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Optional

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
    "製鞋", "鞋", "紡織", "成衣", "塑膠", "化學", "造紙",
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

    Excludes information released after asof. No model signal is an A+ approval.
    """
    weighted = 0.0
    covered = 0.0
    missing = []
    for key, weight in WEIGHTS.items():
        value = observations.get(key)
        released = latest_available_at.get(key)
        if (value is None or released is None or released > asof
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value) or not 0 <= value <= 1):
            missing.append(key)
            continue
        weighted += weight * float(value)
        covered += weight
    if covered < min_coverage:
        return CycleSignal(None, round(covered, 6), tuple(missing),
                           "INSUFFICIENT_PIT_EVIDENCE")
    score = round(100 * weighted / covered, 2)
    return CycleSignal(score, round(covered, 6), tuple(missing),
                       "EARLY_DISCOVERY_RESEARCH_ONLY")
