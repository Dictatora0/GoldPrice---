from datetime import datetime
import os

import pandas as pd

from app.analyzers.signals import SignalDetector
from app.database import init_db, get_session
from app.models import AnalysisSignal
from config import settings


def setup_function(_):
    if os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    init_db()


def test_evaluate_buy_signal_true_when_all_conditions_met():
    indicators = {
        "current_price": 95.0,
        "rsi": 25.0,
        "bb_lower": 100.0,
        "ma_medium": 100.0,
        "volatility": 1.0,
    }

    assert SignalDetector.evaluate_buy_signal(indicators) is True


def test_should_notify_respects_cooldown_setting():
    detector = SignalDetector()

    session = get_session()
    try:
        session.add(
            AnalysisSignal(
                timestamp=datetime.now(),
                signal_type="buy",
                price_cny_per_gram=480.0,
                indicators="{}",
                notified=True,
            )
        )
        session.commit()
    finally:
        session.close()

    original = settings.notification_cooldown
    settings.notification_cooldown = 1
    try:
        assert detector.should_notify() is False
    finally:
        settings.notification_cooldown = original


def test_downtrend_and_volatility_contracting():
    prices = [110, 100, 90, 89, 88, 87]
    assert SignalDetector.is_downtrend_volatility_contracting(prices) is True


def test_downtrend_without_contracting_is_false():
    prices = [110, 100, 90, 85, 75, 65]
    assert SignalDetector.is_downtrend_volatility_contracting(prices) is False


def test_enhanced_signal_penalizes_falling_knife_setup(monkeypatch):
    detector = SignalDetector()
    indicators = {
        "current_price": 90.0,
        "rsi": 24.0,
        "volatility": 3.0,
        "bb_lower": 92.0,
        "bb_middle": 100.0,
        "ma_medium": 100.0,
        "ma_long": 110.0,
        "macd": -2.0,
        "macd_signal": -1.0,
        "macd_histogram": -1.0,
    }

    monkeypatch.setattr(
        detector,
        "_get_price_momentum",
        lambda minutes=30: {"change_pct": -1.8, "trend": "down", "acceleration": -0.02},
    )
    monkeypatch.setattr(
        detector,
        "_analyze_multi_timeframe",
        lambda: {
            "short_term": "bearish",
            "mid_term": "bearish",
            "long_term": "bearish",
            "alignment": "bearish_aligned",
        },
    )

    result = detector._evaluate_buy_signal_enhanced(indicators)

    assert result["score"] < 65
    assert "falling_knife" in result["risk_flags"]


def test_check_buy_signal_skips_recent_duplicate_signal(monkeypatch):
    detector = SignalDetector()
    indicators = {
        "current_price": 480.0,
        "rsi": 18.0,
        "volatility": 1.5,
        "bb_lower": 482.0,
        "bb_middle": 490.0,
        "ma_medium": 500.0,
        "ma_long": 510.0,
        "macd": -0.6,
        "macd_signal": -0.2,
        "macd_histogram": -0.15,
    }

    session = get_session()
    try:
        session.add(
            AnalysisSignal(
                timestamp=datetime.now(),
                signal_type="buy",
                price_cny_per_gram=480.0,
                indicators="{}",
                notified=False,
            )
        )
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr(detector.calculator, "calculate_all", lambda: indicators)
    monkeypatch.setattr(detector.calculator, "get_price_data", lambda days=10: pd.DataFrame())
    monkeypatch.setattr(
        detector,
        "_get_price_momentum",
        lambda minutes=30: {"change_pct": -0.6, "trend": "down", "acceleration": 0.02},
    )
    monkeypatch.setattr(
        detector,
        "_analyze_multi_timeframe",
        lambda: {
            "short_term": "bearish",
            "mid_term": "neutral",
            "long_term": "neutral",
            "alignment": "mixed",
        },
    )

    created = detector.check_buy_signal()

    session = get_session()
    try:
        signal_count = session.query(AnalysisSignal).count()
    finally:
        session.close()

    assert created is False
    assert signal_count == 1


def test_check_buy_signal_requires_reversal_confirmation(monkeypatch):
    detector = SignalDetector()
    indicators = {
        "current_price": 480.0,
        "rsi": 22.0,
        "volatility": 2.2,
        "bb_lower": 482.0,
        "bb_middle": 490.0,
        "ma_medium": 498.0,
        "ma_long": 500.0,
        "macd": -0.9,
        "macd_signal": -0.5,
        "macd_histogram": -0.7,
    }

    monkeypatch.setattr(detector.calculator, "calculate_all", lambda: indicators)
    monkeypatch.setattr(detector.calculator, "get_price_data", lambda days=10: pd.DataFrame())
    monkeypatch.setattr(
        detector,
        "_get_price_momentum",
        lambda minutes=30: {"change_pct": -0.4, "trend": "down", "acceleration": -0.001},
    )
    monkeypatch.setattr(
        detector,
        "_analyze_multi_timeframe",
        lambda: {
            "short_term": "bearish",
            "mid_term": "neutral",
            "long_term": "neutral",
            "alignment": "mixed",
        },
    )

    created = detector.check_buy_signal()

    assert created is False


def test_check_buy_signal_accepts_confirmed_reversal_setup(monkeypatch):
    detector = SignalDetector()
    indicators = {
        "current_price": 480.0,
        "rsi": 18.0,
        "volatility": 1.8,
        "bb_lower": 482.0,
        "bb_middle": 491.0,
        "ma_medium": 500.0,
        "ma_long": 506.0,
        "macd": -0.3,
        "macd_signal": -0.2,
        "macd_histogram": -0.08,
    }

    captured = {}

    monkeypatch.setattr(detector.calculator, "calculate_all", lambda: indicators)
    monkeypatch.setattr(detector.calculator, "get_price_data", lambda days=10: pd.DataFrame())
    monkeypatch.setattr(
        detector,
        "_get_price_momentum",
        lambda minutes=30: {"change_pct": -0.25, "trend": "down", "acceleration": 0.02},
    )
    monkeypatch.setattr(
        detector,
        "_analyze_multi_timeframe",
        lambda: {
            "short_term": "bearish",
            "mid_term": "neutral",
            "long_term": "neutral",
            "alignment": "mixed",
        },
    )
    monkeypatch.setattr(detector, "_has_recent_similar_signal", lambda price, score: False)
    monkeypatch.setattr(
        detector,
        "_save_signal",
        lambda indicators_arg, evaluation_arg: captured.update(
            {"indicators": indicators_arg, "evaluation": evaluation_arg}
        ),
    )

    created = detector.check_buy_signal()

    assert created is True
    assert captured["evaluation"]["score"] >= 65
