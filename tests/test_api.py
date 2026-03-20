from datetime import datetime, timedelta
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.database import init_db, get_db_session, engine
from app.models import PriceHistory, AnalysisSignal
from config import settings
from app.main import app


def build_valid_signal_indicators(price: float) -> dict:
    return {
        "current_price": price,
        "rsi": 28.5,
        "volatility": 1.2,
        "ma_medium": price + 5,
        "bb_lower": price + 1,
        "evaluation_score": 72,
        "evaluation_reasons": ["RSI超卖"],
        "momentum": {"change_pct": -0.6, "trend": "down", "acceleration": 0.01},
        "timeframe_analysis": {
            "short_term": "bearish",
            "mid_term": "neutral",
            "long_term": "neutral",
            "alignment": "mixed",
        },
    }


@pytest.fixture()
def client():
    # Reset test database
    if os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    # Dispose of all connections before reinitializing
    engine.dispose()
    init_db()
    with TestClient(app) as test_client:
        yield test_client
    # Clean up after test
    engine.dispose()


def seed_price_history(points):
    with get_db_session() as session:
        for ts, price in points:
            session.add(
                PriceHistory(
                    timestamp=ts,
                    price_cny_per_gram=price,
                    source_count=2,
                )
            )


def seed_mixed_regime_history():
    now = datetime.now().replace(second=0, microsecond=0)
    older_points = [
        (now - timedelta(hours=26) + timedelta(minutes=offset * 30), 546.0 + offset * 0.1)
        for offset in range(4)
    ]
    recent_points = [
        (now - timedelta(hours=2) + timedelta(minutes=offset * 15), 1015.0 + offset * 0.2)
        for offset in range(8)
    ]
    seed_price_history(older_points + recent_points)
    return older_points, recent_points


def seed_signal(ts, price, *, indicators=None, notified=True):
    with get_db_session() as session:
        session.add(
            AnalysisSignal(
                timestamp=ts,
                signal_type="buy",
                price_cny_per_gram=price,
                indicators=json.dumps(indicators or {}),
                notified=notified,
            )
        )


def test_health_endpoint_returns_ok(client):
    now = datetime.now()
    seed_price_history([(now, 500.0)])

    response = client.get("/api/health")
    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "ok"
    assert data["last_collection"] is not None


def test_current_price_returns_latest(client):
    now = datetime.now()
    seed_price_history(
        [
            (now - timedelta(minutes=5), 480.0),
            (now, 485.5),
        ]
    )

    response = client.get("/api/price/current")
    data = response.json()

    assert response.status_code == 200
    assert data["price_cny_per_gram"] == 485.5


def test_price_history_downsample_interval(client):
    # Use a fixed minute anchor to avoid hour-bucket flakiness.
    # With minute=50, the generated points always span exactly 3 hourly buckets.
    base = datetime.now().replace(minute=50, second=0, microsecond=0) - timedelta(hours=2)
    points = [
        (base + timedelta(minutes=5), 480.0),
        (base + timedelta(minutes=10), 481.0),
        (base + timedelta(minutes=55), 482.0),
        (base + timedelta(hours=1, minutes=5), 483.0),
        (base + timedelta(hours=1, minutes=30), 484.0),
    ]
    seed_price_history(points)

    response = client.get("/api/price/history?days=1&interval=1h")
    data = response.json()

    assert response.status_code == 200
    # Expect last value per hour bucket (3 buckets).
    assert len(data["items"]) == 3
    assert data["items"][0]["price_cny_per_gram"] == 480.0
    assert data["items"][1]["price_cny_per_gram"] == 483.0
    assert data["items"][2]["price_cny_per_gram"] == 484.0


def test_price_history_uses_normalized_interval_cache_key(client, monkeypatch):
    from app.api import price as price_api

    price_api._HISTORY_LOCAL_CACHE.clear()

    latest = datetime.now().replace(second=0, microsecond=0)
    seed_price_history(
        [
            (latest - timedelta(minutes=20), 480.0),
            (latest, 481.0),
        ]
    )

    cached_payload = {
        "items": [
            {
                "timestamp": latest.isoformat(),
                "price_cny_per_gram": 999.0,
            }
        ]
    }
    expected_key = price_api._history_cache_key(1, price_api.parse_interval("1h"), latest)
    observed_keys = []

    def fake_get(key):
        observed_keys.append(key)
        if key == expected_key:
            return json.dumps(cached_payload)
        return None

    monkeypatch.setattr(price_api.cache_manager, "get", fake_get)
    monkeypatch.setattr(price_api.cache_manager, "set", lambda *args, **kwargs: True)

    response = client.get("/api/price/history?days=1&interval=1H")

    assert response.status_code == 200
    assert response.json() == cached_payload
    assert observed_keys == [expected_key]


def test_signals_endpoint_returns_recent(client):
    now = datetime.now()
    seed_signal(
        now - timedelta(hours=1),
        470.0,
        indicators=build_valid_signal_indicators(470.0),
    )

    response = client.get("/api/analysis/signals?days=7")
    data = response.json()

    assert response.status_code == 200
    assert any(item["price_cny_per_gram"] == 470.0 for item in data["items"])
    assert all("evaluation_score" in item["indicators"] for item in data["items"])


def test_signals_endpoint_filters_malformed_signal_records(client):
    now = datetime.now()
    seed_signal(
        now - timedelta(minutes=30),
        548.2,
        indicators={"rsi": 29.8},
        notified=False,
    )
    seed_signal(
        now - timedelta(minutes=5),
        470.0,
        indicators=build_valid_signal_indicators(470.0),
        notified=False,
    )

    response = client.get("/api/analysis/signals?days=7")
    data = response.json()

    assert response.status_code == 200
    assert len(data["items"]) == 1
    assert data["items"][0]["price_cny_per_gram"] == 470.0
    assert data["items"][0]["indicators"]["evaluation_score"] == 72


def test_metrics_endpoint(client):
    """Test Prometheus metrics endpoint."""
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    # Check for some expected metrics
    content = response.text
    assert "gold_http_requests_total" in content or "gold_collector_success_total" in content


def test_history_endpoint_ignores_stale_price_regime(client):
    _, recent_points = seed_mixed_regime_history()

    response = client.get("/api/price/history?days=30")
    data = response.json()

    assert response.status_code == 200
    assert len(data["items"]) == len(recent_points)
    assert all(item["price_cny_per_gram"] > 900 for item in data["items"])
    assert data["meta"]["regime_filtered"] is True
    assert data["meta"]["returned_points"] == len(recent_points)


def test_advice_endpoint_exposes_risk_flags(client, monkeypatch):
    from app.api import analysis as analysis_api

    class FakeAdvisor:
        def analyze_cached(self):
            return {
                "score": 72,
                "confidence": 0.84,
                "dominant_factor": "飞刀风险主导",
                "recommendation_change_reason": "建议由观望转为不推荐，主因是飞刀风险形成。",
                "explainability": {
                    "previous_advice": "观望 / 继续观望",
                    "changed_at": "2026-03-20T18:30:00",
                    "factor_changes": [
                        "新增风险标签：飞刀风险",
                        "评分上升 18（54 → 72）",
                    ],
                    "summary": "建议由观望 / 继续观望切换为不推荐 / 避免抄底，变化发生在 2026-03-20T18:30:00，主因是新增风险标签：飞刀风险。",
                },
                "chart_status": {
                    "line": {
                        "label": "已切换当前有效价格段",
                        "detail": "折线图已剔除旧异常价格段，当前断点属于预期表现。",
                    },
                    "candlestick": {
                        "label": "按当前价格段聚合",
                        "detail": "K线图仅基于当前连续有效价格段生成。",
                    },
                },
                "recommendation": "不推荐",
                "market_state": "市场处于飞刀式下跌阶段",
                "risk_flags": ["falling_knife"],
                "action_label": "避免抄底",
                "action_detail": "等待跌势钝化后，再考虑试探性布局。",
                "insights": ["⚠️ 当前处于下跌共振阶段,超卖不等于止跌,不宜贸然抄底"],
                "risks": ["存在飞刀风险: 多周期下跌共振且动能未明显衰减,当前不宜贸然抄底"],
                "disclaimer": "本建议仅供参考,不构成投资建议,投资有风险",
                "key_indicators": {"current_price": 480.0, "rsi": 25.0, "macd_signal": "死叉"},
            }

    monkeypatch.setattr(analysis_api, "MarketAdvisor", FakeAdvisor)

    response = client.get("/api/analysis/advice")
    data = response.json()

    assert response.status_code == 200
    assert data["data"]["risk_flags"] == ["falling_knife"]
    assert data["data"]["recommendation"] == "不推荐"
    assert data["data"]["action_label"] == "避免抄底"
    assert data["data"]["confidence"] == 0.84
    assert data["data"]["dominant_factor"] == "飞刀风险主导"
    assert "飞刀风险" in data["data"]["recommendation_change_reason"]
    assert data["data"]["explainability"]["previous_advice"] == "观望 / 继续观望"
    assert data["data"]["explainability"]["factor_changes"][0] == "新增风险标签：飞刀风险"
    assert data["data"]["chart_status"]["line"]["label"] == "已切换当前有效价格段"


def test_buy_signal_endpoint_exposes_debug_fields(client, monkeypatch):
    from app.api import analysis as analysis_api

    class FakeDetector:
        def evaluate_buy_signal_cached(self):
            return {
                "score": 68,
                "entry_ready": False,
                "setup_flags": ["oversold", "band_break"],
                "confirmation_flags": ["selling_pressure_easing"],
                "risk_flags": ["falling_knife"],
                "reasons": ["超卖条件具备,但反转确认不足"],
            }

    monkeypatch.setattr(analysis_api, "SignalDetector", FakeDetector)

    response = client.get("/api/analysis/buy-signal")
    data = response.json()

    assert response.status_code == 200
    assert data["data"]["entry_ready"] is False
    assert data["data"]["setup_flags"] == ["oversold", "band_break"]
    assert data["data"]["confirmation_flags"] == ["selling_pressure_easing"]
    assert data["data"]["risk_flags"] == ["falling_knife"]


def test_index_html_uses_cache_busted_local_assets(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "no-store" in response.headers.get("cache-control", "")
    assert "/static/js/chart.js?v=" in response.text
    assert "/static/js/candlestick.js?v=" in response.text
    assert "/static/js/websocket.js?v=" in response.text
    assert "/static/css/style.css?v=" in response.text
