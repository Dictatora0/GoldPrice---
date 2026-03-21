from app.analyzers.decision_engine import evaluate_decision_core


def test_decision_core_blocks_position_under_falling_knife():
    indicators = {
        "current_price": 480.0,
        "rsi": 22.0,
        "bb_lower": 485.0,
        "ma_medium": 495.0,
        "macd_histogram": -0.9,
    }
    momentum = {"change_pct": -1.2, "trend": "down", "acceleration": -0.01}
    timeframe = {
        "short_term": "bearish",
        "mid_term": "bearish",
        "long_term": "bearish",
        "alignment": "bearish_aligned",
    }

    decision = evaluate_decision_core(indicators, momentum=momentum, timeframe=timeframe)

    assert decision["regime"] == "risk_off_falling_knife"
    assert decision["entry_ready"] is False
    assert decision["suggested_position_pct"] == 0.0
    assert decision["expected_return_bp"] <= 0


def test_decision_core_promotes_confirmed_reversal():
    indicators = {
        "current_price": 480.0,
        "rsi": 19.0,
        "bb_lower": 482.0,
        "ma_medium": 500.0,
        "macd_histogram": -0.08,
    }
    momentum = {"change_pct": -0.2, "trend": "down", "acceleration": 0.02}
    timeframe = {
        "short_term": "bearish",
        "mid_term": "neutral",
        "long_term": "neutral",
        "alignment": "mixed",
    }

    decision = evaluate_decision_core(indicators, momentum=momentum, timeframe=timeframe)

    assert decision["regime"] == "confirmed_reversal"
    assert decision["entry_ready"] is True
    assert decision["entry_weak"] is False
    assert decision["suggested_position_pct"] > 0
    assert decision["upside_probability"] > 0.5


def test_decision_core_marks_tentative_reversal_for_weak_entry():
    indicators = {
        "current_price": 480.0,
        "rsi": 23.0,
        "bb_lower": 485.0,
        "ma_medium": 500.0,
        "macd_histogram": -0.8,
        "_entry_context": {
            "setup_flags": ["extreme_oversold", "band_break", "below_ma"],
            "confirmation_flags": ["selling_pressure_easing"],
            "risk_flags": [],
            "core_confirmation_flags": [],
            "entry_ready": False,
            "entry_weak": True,
        },
    }
    momentum = {"change_pct": -0.35, "trend": "down", "acceleration": -0.001}
    timeframe = {
        "short_term": "bearish",
        "mid_term": "neutral",
        "long_term": "neutral",
        "alignment": "mixed",
    }

    decision = evaluate_decision_core(indicators, momentum=momentum, timeframe=timeframe)

    assert decision["entry_ready"] is False
    assert decision["entry_weak"] is True
    assert decision["regime"] == "tentative_reversal"
    assert decision["suggested_position_pct"] >= 0


def test_decision_core_exposes_probability_source():
    indicators = {
        "current_price": 480.0,
        "rsi": 19.0,
        "bb_lower": 482.0,
        "ma_medium": 500.0,
        "macd_histogram": -0.08,
    }
    momentum = {"change_pct": -0.2, "trend": "down", "acceleration": 0.02}
    timeframe = {
        "short_term": "bearish",
        "mid_term": "neutral",
        "long_term": "neutral",
        "alignment": "mixed",
    }

    decision = evaluate_decision_core(indicators, momentum=momentum, timeframe=timeframe)

    assert decision["probability_source"] in {"heuristic", "logistic_regression"}
    assert "heuristic_upside_probability" in decision
