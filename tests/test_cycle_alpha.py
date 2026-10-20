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
    assert result.score == 100.0
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
