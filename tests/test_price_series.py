from datetime import datetime, timedelta
import os

import pytest

from app.database import get_db_session, init_db
from app.models import PriceHistory
from app.price_series import load_price_series
from config import settings


def setup_function(_):
    if os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    init_db()


def seed_prices(points):
    with get_db_session() as session:
        for timestamp, price in points:
            session.add(
                PriceHistory(
                    timestamp=timestamp,
                    price_cny_per_gram=price,
                    source_count=1,
                )
            )


def test_daily_price_series_uses_last_price_per_day():
    base = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=1)
    seed_prices(
        [
            (base, 500.0),
            (base.replace(hour=15), 502.0),
            (base + timedelta(days=1, hours=1), 503.0),
            (base + timedelta(days=1, hours=8), 506.0),
        ]
    )

    series = load_price_series(lookback_days=30, interval="1d")

    assert series.interval == "1d"
    assert series.basis_interval == "1d"
    assert series.sample_count == 2
    assert [point.price for point in series.points] == [502.0, 506.0]


def test_hourly_price_series_uses_last_price_per_hour():
    base = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    seed_prices(
        [
            (base, 500.0),
            (base + timedelta(minutes=20), 501.0),
            (base + timedelta(hours=1, minutes=5), 502.0),
            (base + timedelta(hours=1, minutes=45), 503.5),
        ]
    )

    series = load_price_series(lookback_days=30, interval="1h")

    assert series.interval == "1h"
    assert series.sample_count == 2
    assert [point.price for point in series.points] == [501.0, 503.5]


def test_invalid_price_series_interval_is_rejected():
    with pytest.raises(ValueError):
        load_price_series(lookback_days=30, interval="15m")
