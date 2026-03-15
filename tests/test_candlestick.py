from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, get_session
from app.models import PriceHistory
from config import settings
import os


@pytest.fixture()
def client():
    # Reset test database
    if os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    init_db()
    with TestClient(app) as test_client:
        yield test_client


def seed_candlestick_data():
    """生成K线测试数据"""
    session = get_session()
    try:
        base = datetime.now() - timedelta(hours=6)

        # 生成6小时的数据,每3分钟一个点
        for i in range(120):  # 6小时 * 20个点/小时
            timestamp = base + timedelta(minutes=i * 3)
            # 模拟价格波动
            price = 480.0 + (i % 20) * 0.5 - 5

            session.add(
                PriceHistory(
                    timestamp=timestamp,
                    price_cny_per_gram=price,
                    source_count=2,
                )
            )
        session.commit()
    finally:
        session.close()


def test_candlestick_endpoint_returns_ohlc_data(client):
    """测试K线端点返回OHLC数据"""
    seed_candlestick_data()

    response = client.get("/api/price/candlestick?days=1&interval=1h")
    data = response.json()

    assert response.status_code == 200
    assert "items" in data
    assert len(data["items"]) > 0

    # 验证第一个K线数据结构
    candle = data["items"][0]
    assert "timestamp" in candle
    assert "open" in candle
    assert "high" in candle
    assert "low" in candle
    assert "close" in candle
    assert "activity" in candle
    assert "data_points" in candle


def test_candlestick_ohlc_values_are_correct(client):
    """测试K线OHLC值的正确性"""
    seed_candlestick_data()

    response = client.get("/api/price/candlestick?days=1&interval=1h")
    data = response.json()

    candle = data["items"][0]

    # 验证OHLC关系
    assert candle["high"] >= candle["open"]
    assert candle["high"] >= candle["close"]
    assert candle["low"] <= candle["open"]
    assert candle["low"] <= candle["close"]
    assert candle["high"] >= candle["low"]


def test_candlestick_activity_calculation(client):
    """测试活跃度计算"""
    seed_candlestick_data()

    response = client.get("/api/price/candlestick?days=1&interval=1h")
    data = response.json()

    candle = data["items"][0]

    # 活跃度应该大于0
    assert candle["activity"] >= 0
    # 数据点数量应该大于0
    assert candle["data_points"] > 0


def test_candlestick_invalid_interval(client):
    """测试无效的时间间隔"""
    response = client.get("/api/price/candlestick?days=1&interval=5m")

    assert response.status_code == 400
    assert "Invalid interval" in response.json()["detail"]


def test_candlestick_different_intervals(client):
    """测试不同的时间间隔"""
    seed_candlestick_data()

    # 测试1小时间隔
    response_1h = client.get("/api/price/candlestick?days=1&interval=1h")
    data_1h = response_1h.json()

    # 测试4小时间隔
    response_4h = client.get("/api/price/candlestick?days=1&interval=4h")
    data_4h = response_4h.json()

    # 4小时间隔的K线数量应该少于1小时间隔
    assert len(data_4h["items"]) < len(data_1h["items"])


def test_candlestick_empty_data(client):
    """测试无数据时的响应"""
    response = client.get("/api/price/candlestick?days=1&interval=1h")
    data = response.json()

    assert response.status_code == 200
    assert data["items"] == []
