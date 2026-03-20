import pandas as pd
from datetime import datetime
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

    df = calc.get_price_data(days=30)

    assert not df.empty
    assert len(df) == len(recent_points)
    assert df["price"].min() > 900
