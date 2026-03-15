from datetime import datetime
import os

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
