from app import market_context


def test_get_trend_uses_dynamic_thresholds_by_timeframe():
    prices = [(100.0,), (100.35,)]

    short_trend = market_context._get_trend(prices, window_hours=1)
    long_trend = market_context._get_trend(prices, window_hours=24)

    assert short_trend == "bullish"
    assert long_trend == "neutral"


def test_build_entry_context_supports_weak_entry_without_core_confirmation():
    indicators = {
        "current_price": 480.0,
        "rsi": 22.0,
        "bb_lower": 485.0,
        "ma_medium": 500.0,
        "macd_histogram": -0.8,
        "macd_histogram_std": 0.2,
    }
    momentum = {"change_pct": -0.3, "trend": "down", "acceleration": -0.003}
    timeframe = {"alignment": "mixed"}

    result = market_context.build_entry_context(indicators, momentum, timeframe)

    assert len(result["setup_flags"]) >= 3
    assert len(result["confirmation_flags"]) >= 1
    assert result["core_confirmation_flags"] == []
    assert result["entry_ready"] is False
    assert result["entry_weak"] is True


def test_build_entry_context_allows_strong_entry_without_core_confirmation():
    indicators = {
        "current_price": 480.0,
        "rsi": 22.0,
        "bb_lower": 485.0,
        "ma_medium": 500.0,
        "macd_histogram": -0.8,
        "macd_histogram_std": 0.2,
    }
    momentum = {"change_pct": -0.3, "trend": "down", "acceleration": -0.001}
    timeframe = {"alignment": "mixed"}

    result = market_context.build_entry_context(indicators, momentum, timeframe)

    assert len(result["confirmation_flags"]) >= 2
    assert result["core_confirmation_flags"] == []
    assert result["entry_ready"] is True


def test_build_entry_context_rsi_oversold_tiers():
    base = {
        "current_price": 500.0,
        "bb_lower": 490.0,
        "ma_medium": 505.0,
        "macd_histogram": -0.05,
        "macd_histogram_std": 0.2,
    }
    momentum = {"change_pct": 0.0, "trend": "flat", "acceleration": 0.0}
    timeframe = {"alignment": "mixed"}

    extreme = market_context.build_entry_context({**base, "rsi": 20.0}, momentum, timeframe)
    normal = market_context.build_entry_context({**base, "rsi": 28.0}, momentum, timeframe)
    mild = market_context.build_entry_context({**base, "rsi": 33.0}, momentum, timeframe)

    assert "extreme_oversold" in extreme["setup_flags"]
    assert "oversold" in normal["setup_flags"]
    assert "mild_oversold" in mild["setup_flags"]


def test_calculate_momentum_acceleration_is_robust_to_midpoint_spike():
    stable_downtrend = [100.0, 99.8, 99.6, 99.4, 99.2, 99.0, 98.8, 98.6]
    with_spike = [100.0, 99.8, 99.6, 104.0, 99.2, 99.0, 98.8, 98.6]

    baseline = market_context._calculate_momentum_acceleration(stable_downtrend)
    robust = market_context._calculate_momentum_acceleration(with_spike)

    assert abs(robust - baseline) < 0.02


def test_calculate_momentum_acceleration_with_small_sample_is_not_zero():
    prices = [100.0, 99.9, 99.8, 99.6]

    acceleration = market_context._calculate_momentum_acceleration(prices)

    assert acceleration != 0.0


def test_build_entry_context_macd_thresholds_are_std_adaptive():
    momentum = {"change_pct": 0.0, "trend": "flat", "acceleration": 0.0}
    timeframe = {"alignment": "mixed"}
    indicators = {
        "current_price": 500.0,
        "rsi": 32.0,
        "bb_lower": 490.0,
        "ma_medium": 505.0,
        "macd_histogram": -0.22,
    }

    low_std = market_context.build_entry_context(
        {**indicators, "macd_histogram_std": 0.2},
        momentum,
        timeframe,
    )
    high_std = market_context.build_entry_context(
        {**indicators, "macd_histogram_std": 0.6},
        momentum,
        timeframe,
    )

    assert "macd_stabilizing" not in low_std["confirmation_flags"]
    assert "macd_stabilizing" in high_std["confirmation_flags"]
