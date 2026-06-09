import pandas as pd
from datetime import datetime, timedelta
import os

from app.analyzers.indicators import IndicatorCalculator
from app.database import init_db, get_db_session
from app.models import PriceHistory
from config import settings


def setup_function(_):
    if os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    init_db()


def test_calculate_ma_returns_expected_values():
    calc = IndicatorCalculator()
    prices = list(range(1, 101))
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range(datetime(2026, 1, 1), periods=len(prices), freq="D"),
            "price": prices,
        }
    ).set_index("timestamp")

    ma = calc.calculate_ma(df)

    assert round(ma["ma_short"], 2) == 97.0
    assert round(ma["ma_medium"], 2) == 85.5
    assert round(ma["ma_long"], 2) == 55.5


def test_get_price_data_uses_only_current_price_regime():
    calc = IndicatorCalculator()
    now = datetime.now().replace(second=0, microsecond=0)

    with get_db_session() as session:
        older_points = [
            (now - pd.Timedelta(hours=26) + pd.Timedelta(minutes=offset * 30), 546.0 + offset * 0.1)
            for offset in range(4)
        ]
        recent_points = [
            (now - pd.Timedelta(hours=2) + pd.Timedelta(minutes=offset * 15), 1015.0 + offset * 0.2)
            for offset in range(8)
        ]

        for ts, price in older_points + recent_points:
            session.add(
                PriceHistory(
                    timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    price_cny_per_gram=price,
                    source_count=1,
                )
            )

    df = calc.get_price_data(days=30, interval="raw")

    assert not df.empty
    assert len(df) == len(recent_points)
    assert df["price"].min() > 900


def test_get_price_data_daily_interval_is_stable_across_intraday_sampling():
    calc = IndicatorCalculator()
    base = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=39)

    with get_db_session() as session:
        for day in range(40):
            day_start = base + timedelta(days=day)
            session.add(
                PriceHistory(
                    timestamp=day_start,
                    price_cny_per_gram=500.0 + day,
                    source_count=1,
                )
            )
            session.add(
                PriceHistory(
                    timestamp=day_start + timedelta(hours=6),
                    price_cny_per_gram=500.5 + day,
                    source_count=1,
                )
            )

    df = calc.get_price_data(days=90, interval="1d")

    assert len(df) == 40
    assert df.attrs["basis_interval"] == "1d"
    assert df["price"].iloc[0] == 500.5
    assert df["price"].iloc[-1] == 539.5


def test_calculate_all_exposes_indicator_basis_interval():
    calc = IndicatorCalculator()
    base = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=99)

    with get_db_session() as session:
        for day in range(100):
            session.add(
                PriceHistory(
                    timestamp=base + timedelta(days=day),
                    price_cny_per_gram=480.0 + day,
                    source_count=1,
                )
            )

    indicators = calc.calculate_all()

    assert indicators["basis_interval"] == "1d"
    assert indicators["sample_count"] == 100
