import pandas as pd
from datetime import datetime

from app.analyzers.indicators import IndicatorCalculator


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
