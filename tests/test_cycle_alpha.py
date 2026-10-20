from tw_model_v880.cycle_alpha import score_cycle, is_cyclical, WEIGHTS

def test_shoemaking_is_cyclical():
    assert is_cyclical("製鞋業")
    assert is_cyclical("紡織纖維")
    assert is_cyclical("航運業")

def test_future_release_cannot_leak_into_past():
    values = {key: 1.0 for key in WEIGHTS}
    times = {key: "2026-10-01" for key in WEIGHTS}
    times["peer_breadth"] = "2026-11-01"
    result = score_cycle(values, asof="2026-10-20", latest_available_at=times)
    assert result.score == 80.0
    assert result.observed_weight == 0.8
    assert not result.a_plus_certified

def test_missing_data_does_not_pass():
    result = score_cycle({"revenue_acceleration": 1.0},
                         asof="2026-10-20",
                         latest_available_at={"revenue_acceleration": "2026-10-01"})
    assert result.score is None
    assert result.status == "INSUFFICIENT_PIT_EVIDENCE"

def test_invalid_input_rejected():
    values = {key: 1.0 for key in WEIGHTS}
    values["margin_leading"] = float("nan")
    dates = {key: "2026-10-01" for key in WEIGHTS}
    result = score_cycle(values, asof="2026-10-20", latest_available_at=dates)
    assert "margin_leading" in result.missing

def test_missing_factor_reduces_score():
    values = {key: 1.0 for key in WEIGHTS}
    dates = {key: "2026-10-01" for key in WEIGHTS}
    dates["peer_breadth"] = "2026-11-01"
    result = score_cycle(values, asof="2026-10-20", latest_available_at=dates)
    assert result.score == 80.0

def test_same_day_publication_not_valid_before_release():
    values = {key: 1.0 for key in WEIGHTS}
    times = {key: "2026-10-19T17:00:00+08:00" for key in WEIGHTS}
    times["peer_breadth"] = "2026-10-20T16:00:00+08:00"
    result = score_cycle(values, asof="2026-10-20T13:40:00+08:00",
                         latest_available_at=times)
    assert result.score == 80.0
    assert "peer_breadth" in result.missing

def test_equivalent_utc_future_not_lexicographic():
    values = {key: 1.0 for key in WEIGHTS}
    times = {key: "2026-10-19T17:00:00+08:00" for key in WEIGHTS}
    times["peer_breadth"] = "2026-10-20T06:00:00Z"
    result = score_cycle(values, asof="2026-10-20T13:30:00+08:00",
                         latest_available_at=times)
    assert result.score == 80.0  # 06:00Z = 14:00 Taipei
    assert "peer_breadth" in result.missing

def test_undated_release_hour_is_not_intraday_evidence():
    values = {key: 1.0 for key in WEIGHTS}
    times = {key: "2026-10-19" for key in WEIGHTS}
    times["peer_breadth"] = "2026-10-20"
    result = score_cycle(values, asof="2026-10-20T13:40:00+08:00",
                         latest_available_at=times)
    assert result.score == 80.0
    end_of_day = score_cycle(values, asof="2026-10-20",
                             latest_available_at=times)
    assert end_of_day.score == 100.0

def test_bad_dates_and_coverage_fail_closed():
    import pytest
    values = {key: 1.0 for key in WEIGHTS}
    times = {key: "2026-10-19" for key in WEIGHTS}
    times["peer_breadth"] = "2026-02-30"
    result = score_cycle(values, asof="2026-10-20",
                         latest_available_at=times)
    assert result.score == 80.0
    for bad in ("2026-2-20", "2026-02-30", "2026-10-20T12:00:00"):
        with pytest.raises(ValueError):
            score_cycle(values, asof=bad, latest_available_at=times)
    for bad in (-.1, 0, 1.1, float("nan"), True):
        with pytest.raises(ValueError):
            score_cycle(values, asof="2026-10-20",
                        latest_available_at=times, min_coverage=bad)

def test_sports_leisure_industry_is_cycle_research():
    assert is_cyclical("運動休閒")
