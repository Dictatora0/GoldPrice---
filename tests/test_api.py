from datetime import datetime, timedelta
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.database import get_db_session, engine, init_db
from app.models import PriceHistory, AnalysisSignal, PriceSource
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
    engine.dispose()
    if os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    with TestClient(app) as test_client:
        init_db()
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


def seed_price_with_sources(ts, price, sources):
    with get_db_session() as session:
        history = PriceHistory(
            timestamp=ts,
            price_cny_per_gram=price,
            source_count=sum(1 for item in sources if item.get("is_valid", True)),
        )
        session.add(history)
        session.flush()
        for item in sources:
            session.add(
                PriceSource(
                    price_history_id=history.id,
                    source_name=item["source_name"],
                    price_cny_per_gram=item["price_cny_per_gram"],
                    is_valid=item.get("is_valid", True),
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
    assert data["environment"] in {"development", "production"}
    assert data["version"] == "2.0.0"
    assert "runtime" in data
    assert "scheduler" in data["runtime"]
    assert "alerts_loop" in data["runtime"]
    assert "details" in data["runtime"]
    assert "collect" in data["runtime"]["details"]["scheduler"]


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


def test_latest_price_sources_endpoint_returns_quality_summary(client):
    now = datetime.now().replace(second=0, microsecond=0)
    seed_price_with_sources(
        now,
        612.4,
        [
            {"source_name": "sge_official", "price_cny_per_gram": 612.2, "is_valid": True},
            {"source_name": "gold_cn", "price_cny_per_gram": 612.3, "is_valid": True},
            {"source_name": "sina", "price_cny_per_gram": 612.4, "is_valid": True},
            {"source_name": "eastmoney", "price_cny_per_gram": 612.6, "is_valid": True},
            {"source_name": "global_gold", "price_cny_per_gram": 620.8, "is_valid": False},
        ],
    )

    response = client.get("/api/price/sources/latest")
    data = response.json()

    assert response.status_code == 200
    assert data["price_cny_per_gram"] == 612.4
    assert data["quality"]["confidence_level"] in {"high", "medium", "low"}
    assert data["quality"]["valid_source_count"] == 4
    assert data["quality"]["invalid_source_count"] == 1
    assert data["quality"]["trusted_valid_source_count"] >= 1
    assert data["quality"]["avg_recent_valid_rate_pct"] is not None
    assert isinstance(data["sources"], list)
    assert data["primary_source"]["name"] == "sge_official"
    assert data["primary_source"]["display_name"] == "SGE 官网延时行情"
    assert data["primary_source"]["status"] == "available"
    assert any(item["name"] == "sge_official" and item["trust_tier"] == "high" for item in data["sources"])
    assert any(item["name"] == "gold_cn" for item in data["sources"])
    assert any(item["is_backup"] for item in data["sources"] if item["name"] == "global_gold")
    assert any(item["health"]["sample_count"] >= 1 for item in data["sources"])
    assert data["aggregation"]["method"] in {
        "primary_trusted_anchor",
        "weighted_trust_mean",
        "fallback_mean",
        "unavailable",
    }


def test_latest_price_sources_v1_endpoint_matches_legacy_route(client):
    now = datetime.now().replace(second=0, microsecond=0)
    seed_price_with_sources(
        now,
        605.2,
        [
            {"source_name": "gold_cn", "price_cny_per_gram": 605.1, "is_valid": True},
            {"source_name": "sina", "price_cny_per_gram": 605.3, "is_valid": True},
        ],
    )

    legacy_response = client.get("/api/price/sources/latest")
    v1_response = client.get("/api/v1/price/sources/latest")

    assert legacy_response.status_code == 200
    assert v1_response.status_code == 200
    assert legacy_response.json()["quality"] == v1_response.json()["quality"]
    assert legacy_response.json()["primary_source"] == v1_response.json()["primary_source"]
    assert legacy_response.json()["sources"] == v1_response.json()["sources"]


def test_latest_price_sources_endpoint_marks_primary_source_missing(client):
    now = datetime.now().replace(second=0, microsecond=0)
    seed_price_with_sources(
        now,
        598.8,
        [
            {"source_name": "sge_official", "price_cny_per_gram": 598.7, "is_valid": False},
            {"source_name": "gold_cn", "price_cny_per_gram": 598.9, "is_valid": False},
            {"source_name": "sina", "price_cny_per_gram": 598.8, "is_valid": True},
            {"source_name": "global_gold", "price_cny_per_gram": 599.0, "is_valid": True},
        ],
    )

    response = client.get("/api/price/sources/latest")
    data = response.json()

    assert response.status_code == 200
    assert data["primary_source"]["name"] is None
    assert data["primary_source"]["display_name"] == "主源缺席"
    assert data["primary_source"]["status"] == "missing"


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


def test_indicators_endpoint_returns_basis_metadata(client):
    now = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    seed_price_history(
        [
            (now - timedelta(days=99 - offset), 500.0 + offset)
            for offset in range(100)
        ]
    )

    response = client.get("/api/analysis/indicators")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["items"]["basis_interval"] == "1d"
    assert payload["items"]["sample_count"] == 100


def test_signal_performance_endpoint_returns_backtest_stats(client):
    now = datetime.now().replace(second=0, microsecond=0)
    base_price = 500.0

    prices = []
    for offset in range(0, 50):
        prices.append((now - timedelta(days=49 - offset), base_price + offset))
    seed_price_history(prices)

    signal_one_time = now - timedelta(days=30)
    signal_two_time = now - timedelta(days=20)

    signal_one_price = next(price for ts, price in prices if ts == signal_one_time)
    signal_two_price = next(price for ts, price in prices if ts == signal_two_time)

    seed_signal(
        signal_one_time,
        signal_one_price,
        indicators={
            "current_price": signal_one_price,
            "evaluation_score": 85,
            "evaluation_reasons": ["强势回撤后确认"],
            "momentum": {"trend": "up"},
            "timeframe_analysis": {"alignment": "bullish_aligned"},
        },
        notified=False,
    )
    seed_signal(
        signal_two_time,
        signal_two_price,
        indicators={
            "current_price": signal_two_price,
            "evaluation_score": 72,
            "evaluation_reasons": ["超卖修复"],
            "momentum": {"trend": "neutral"},
            "timeframe_analysis": {"alignment": "mixed"},
        },
        notified=False,
    )

    response = client.get(
        "/api/analysis/signal-performance?window_days=90&horizons=3,7&limit=20&high_score_threshold=80"
    )
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["signal_count"] == 2
    assert data["evaluated_signal_count"] == 2
    assert len(data["horizon_stats"]) == 2
    by_horizon = {item["horizon_days"]: item for item in data["horizon_stats"]}
    assert by_horizon[3]["sample_count"] == 2
    assert by_horizon[3]["win_rate_pct"] == 100.0
    assert by_horizon[7]["sample_count"] == 2
    assert by_horizon[7]["avg_return_pct"] == pytest.approx(1.336, abs=0.01)
    assert data["high_score_segment"]["sample_count"] == 1
    assert data["high_score_segment"]["win_rate_pct"] == 100.0


def test_support_resistance_endpoint_returns_key_levels(client):
    now = datetime.now().replace(second=0, microsecond=0)
    values = [
        600.0,
        590.0,
        580.0,
        570.0,
        560.0,
        570.0,
        580.0,
        590.0,
        610.0,
        620.0,
        630.0,
        620.0,
        610.0,
        600.0,
        595.0,
        602.0,
    ]
    points = [
        (now - timedelta(days=len(values) - 1 - index), price)
        for index, price in enumerate(values)
    ]
    seed_price_history(points)

    response = client.get(
        "/api/analysis/support-resistance?window_days=365&pivot_window=2&max_levels=3"
    )
    payload = response.json()["data"]

    assert response.status_code == 200
    assert payload["current_price"] == 602.0
    assert payload["nearest_support"] is not None
    assert payload["nearest_resistance"] is not None
    assert payload["nearest_support"]["price"] == 560.0
    assert payload["nearest_resistance"]["price"] == 630.0
    assert payload["nearest_support"]["distance_pct"] == pytest.approx(6.977, abs=0.02)
    assert payload["nearest_resistance"]["distance_pct"] == pytest.approx(4.651, abs=0.02)
    assert payload["round_level_step"] == 10
    assert any(line["kind"] == "support" for line in payload["plot_lines"])
    assert any(line["kind"] == "resistance" for line in payload["plot_lines"])


def test_macro_correlation_endpoint_returns_data_shape(client):
    now = datetime.now().replace(second=0, microsecond=0)
    with get_db_session() as session:
        for idx in range(1, 16):
            ts = now - timedelta(hours=16 - idx)
            domestic = 600.0 + idx * 0.7
            global_price = 596.0 + idx * 0.6
            history = PriceHistory(
                timestamp=ts,
                price_cny_per_gram=domestic,
                source_count=2,
            )
            session.add(history)
            session.flush()
            session.add(
                PriceSource(
                    price_history_id=history.id,
                    source_name="global_gold",
                    price_cny_per_gram=global_price,
                    is_valid=True,
                )
            )

    response = client.get("/api/analysis/macro-correlation?window_days=120&limit=500&include_live_fx=false")
    payload = response.json()["data"]

    assert response.status_code == 200
    assert payload["sample_count"] >= 10
    assert payload["domestic_latest_cny_per_gram"] is not None
    assert payload["global_latest_cny_per_gram"] is not None
    assert payload["premium_cny_per_gram"] is not None
    assert payload["premium_pct"] is not None
    assert payload["domestic_global_corr"] is not None
    assert payload["domestic_global_return_corr"] is not None
    assert payload["correlation_basis"] == "return_pct"
    assert "macro_hint" in payload
    assert isinstance(payload.get("recent_points"), list)


def test_multi_timeframe_forecast_and_entry_plan_endpoints(client):
    now = datetime.now().replace(second=0, microsecond=0)
    points = []
    for idx in range(1, 121):
        ts = now - timedelta(days=121 - idx)
        points.append((ts, 560.0 + idx * 0.8))
    seed_price_history(points)

    timeframe_resp = client.get("/api/analysis/multi-timeframe?windows=1,7,30&lookback_days=180")
    timeframe_data = timeframe_resp.json()["data"]
    assert timeframe_resp.status_code == 200
    assert timeframe_data["alignment"] in {"bullish_aligned", "bearish_aligned", "mixed", "insufficient_data"}
    assert isinstance(timeframe_data.get("frames"), list)

    forecast_resp = client.get("/api/analysis/forecast?lookback_days=180&horizon_days=7&simulation_paths=300")
    forecast_data = forecast_resp.json()["data"]
    assert forecast_resp.status_code == 200
    assert forecast_data["current_price"] is not None
    assert forecast_data["expected_price"] is not None
    assert forecast_data["basis_interval"] == "1d"
    assert forecast_data["sample_count"] == 120
    assert forecast_data["confidence"]["level"] in {"high", "medium", "low", "insufficient"}
    assert "reason" in forecast_data["confidence"]
    assert forecast_data["forecast_range"]["lower"] is not None
    assert forecast_data["forecast_range"]["upper"] is not None

    entry_plan_resp = client.get(
        "/api/analysis/entry-plan?budget_cny=6000&batches=3&step_pct=2.0&target_profit_pct=5.0"
    )
    entry_plan_data = entry_plan_resp.json()["data"]
    assert entry_plan_resp.status_code == 200
    assert entry_plan_data["current_price"] is not None
    assert entry_plan_data["execution_gate"]["status"] in {"ready", "watch", "blocked", "unavailable"}
    assert "message" in entry_plan_data["execution_gate"]
    assert len(entry_plan_data["plan"]) == 3
    assert entry_plan_data["summary"]["avg_entry_price"] is not None


def test_confidence_center_endpoint_returns_audit_view(client):
    now = datetime.now().replace(second=0, microsecond=0)
    prices = []
    for offset in range(0, 70):
        prices.append((now - timedelta(days=69 - offset), 500.0 + offset * 1.5))
    seed_price_history(prices)

    signal_time = now - timedelta(days=10)
    signal_price = next(price for ts, price in prices if ts == signal_time)
    seed_signal(
        signal_time,
        signal_price,
        indicators={
            "current_price": signal_price,
            "evaluation_score": 84,
            "evaluation_reasons": ["趋势回踩", "动量修复"],
            "momentum": {"trend": "up", "change_pct": 0.8, "acceleration": 0.03},
            "timeframe_analysis": {"alignment": "bullish_aligned"},
        },
        notified=False,
    )

    response = client.get("/api/analysis/confidence-center?window_days=120&horizons=3,7,30")
    payload = response.json()["data"]

    assert response.status_code == 200
    assert payload["summary"]["signal_count"] >= 1
    assert payload["summary"]["degradation_status"] in {"healthy", "watch", "degraded", "insufficient_data"}
    assert "current_advice" in payload
    assert "performance_snapshot" in payload
    assert "risk_checks" in payload
    assert "similar_history" in payload
    assert "degradation_reason" in payload["summary"]
    assert isinstance(payload["similar_history"]["matches"], list)
    if payload["similar_history"]["matches"]:
        first_match = payload["similar_history"]["matches"][0]
        assert "forward_returns" in first_match
        assert "primary_horizon_return_pct" in first_match


def test_signal_performance_exposes_regime_breakdown(client):
    now = datetime.now().replace(second=0, microsecond=0)
    prices = []
    for offset in range(0, 80):
        prices.append((now - timedelta(days=79 - offset), 520.0 + offset * 1.1))
    seed_price_history(prices)

    for days_ago, alignment, risk_flags in [
        (20, "bullish_aligned", []),
        (16, "mixed", []),
        (12, "bearish_aligned", ["falling_knife"]),
    ]:
        signal_time = now - timedelta(days=days_ago)
        signal_price = next(price for ts, price in prices if ts == signal_time)
        seed_signal(
            signal_time,
            signal_price,
            indicators={
                "current_price": signal_price,
                "evaluation_score": 76,
                "evaluation_reasons": ["状态分层样本"],
                "risk_flags": risk_flags,
                "momentum": {"trend": "up", "change_pct": 0.4, "acceleration": 0.01},
                "timeframe_analysis": {"alignment": alignment},
            },
            notified=False,
        )

    response = client.get("/api/analysis/signal-performance?window_days=180&horizons=3,7,30")
    payload = response.json()["data"]

    assert response.status_code == 200
    assert "regime_breakdown" in payload
    labels = {item["label"] for item in payload["regime_breakdown"]}
    assert {"多头共振", "震荡混合", "飞刀风险"}.issubset(labels)


def test_confidence_center_similar_history_includes_realized_returns(client):
    now = datetime.now().replace(second=0, microsecond=0)
    prices = []
    for offset in range(0, 80):
        prices.append((now - timedelta(days=79 - offset), 560.0 + offset * 2.0))
    seed_price_history(prices)

    first_signal_time = now - timedelta(days=15)
    second_signal_time = now - timedelta(days=10)
    first_signal_price = next(price for ts, price in prices if ts == first_signal_time)
    second_signal_price = next(price for ts, price in prices if ts == second_signal_time)

    seed_signal(
        first_signal_time,
        first_signal_price,
        indicators={
            "current_price": first_signal_price,
            "evaluation_score": 83,
            "evaluation_reasons": ["趋势延续", "支撑确认"],
            "risk_flags": ["波动抬升"],
            "momentum": {"trend": "up", "change_pct": 0.9, "acceleration": 0.03},
            "timeframe_analysis": {"alignment": "bullish_aligned"},
        },
        notified=False,
    )
    seed_signal(
        second_signal_time,
        second_signal_price,
        indicators={
            "current_price": second_signal_price,
            "evaluation_score": 86,
            "evaluation_reasons": ["回踩确认", "量价配合"],
            "risk_flags": ["波动抬升"],
            "momentum": {"trend": "up", "change_pct": 1.1, "acceleration": 0.05},
            "timeframe_analysis": {"alignment": "bullish_aligned"},
        },
        notified=False,
    )

    response = client.get("/api/analysis/confidence-center?window_days=180&horizons=3,7,30")
    payload = response.json()["data"]

    assert response.status_code == 200
    assert payload["similar_history"]["match_count"] >= 1
    realized_match = payload["similar_history"]["matches"][0]
    assert realized_match["forward_returns"]["3d"] is not None
    assert realized_match["forward_returns"]["7d"] is not None
    assert realized_match["primary_horizon_return_pct"] is not None
    assert payload["summary"]["degradation_reason"]


def test_confidence_center_exposes_regime_breakdown(client):
    now = datetime.now().replace(second=0, microsecond=0)
    prices = []
    for offset in range(0, 90):
        prices.append((now - timedelta(days=89 - offset), 600.0 + offset * 1.4))
    seed_price_history(prices)

    signal_specs = [
        (now - timedelta(days=20), "bullish_aligned", []),
        (now - timedelta(days=16), "bullish_aligned", []),
        (now - timedelta(days=12), "mixed", []),
        (now - timedelta(days=9), "bearish_aligned", ["falling_knife"]),
    ]
    for signal_time, alignment, risk_flags in signal_specs:
        signal_price = next(price for ts, price in prices if ts == signal_time)
        seed_signal(
            signal_time,
            signal_price,
            indicators={
                "current_price": signal_price,
                "evaluation_score": 78,
                "evaluation_reasons": ["状态样本"],
                "risk_flags": risk_flags,
                "momentum": {"trend": "up", "change_pct": 0.5, "acceleration": 0.02},
                "timeframe_analysis": {"alignment": alignment},
            },
            notified=False,
        )

    response = client.get("/api/analysis/confidence-center?window_days=180&horizons=3,7,30")
    payload = response.json()["data"]

    assert response.status_code == 200
    assert "regime_breakdown" in payload["performance_snapshot"]
    breakdown = payload["performance_snapshot"]["regime_breakdown"]
    assert isinstance(breakdown, list)
    labels = {item["label"] for item in breakdown}
    assert "多头共振" in labels
    assert "震荡混合" in labels
    assert "飞刀风险" in labels
    current_items = [item for item in breakdown if item.get("is_current")]
    assert len(current_items) == 1
    assert current_items[0]["label"] in labels


def test_confidence_center_v1_endpoint_matches_legacy_route(client):
    now = datetime.now().replace(second=0, microsecond=0)
    prices = []
    for offset in range(0, 70):
        prices.append((now - timedelta(days=69 - offset), 520.0 + offset * 1.2))
    seed_price_history(prices)

    signal_time = now - timedelta(days=8)
    signal_price = next(price for ts, price in prices if ts == signal_time)
    seed_signal(
        signal_time,
        signal_price,
        indicators={
            "current_price": signal_price,
            "evaluation_score": 81,
            "evaluation_reasons": ["回踩支撑", "短期动能回升"],
            "momentum": {"trend": "up", "change_pct": 0.6, "acceleration": 0.02},
            "timeframe_analysis": {"alignment": "bullish_aligned"},
        },
        notified=False,
    )

    legacy_response = client.get("/api/analysis/confidence-center?window_days=120&horizons=3,7,30")
    v1_response = client.get("/api/v1/analysis/confidence-center?window_days=120&horizons=3,7,30")

    assert legacy_response.status_code == 200
    assert v1_response.status_code == 200
    assert legacy_response.json()["data"]["summary"] == v1_response.json()["data"]["summary"]
    assert set(legacy_response.json()["data"].keys()) == set(v1_response.json()["data"].keys())


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


def test_buy_signal_endpoint_exposes_unified_decision_metrics(client, monkeypatch):
    from app.api import analysis as analysis_api

    class FakeDetector:
        def evaluate_buy_signal_cached(self):
            return {
                "score": 68,
                "entry_ready": False,
                "setup_flags": ["oversold", "band_break"],
                "confirmation_flags": ["selling_pressure_easing"],
                "risk_flags": [],
                "reasons": ["超卖条件具备,但反转确认不足"],
                "regime": "reversal_watch",
                "upside_probability": 0.58,
                "downside_risk_bp": 11.2,
                "expected_return_bp": 6.8,
                "suggested_position_pct": 8.0,
            }

    monkeypatch.setattr(analysis_api, "SignalDetector", FakeDetector)

    response = client.get("/api/analysis/buy-signal")
    data = response.json()

    assert response.status_code == 200
    assert data["data"]["regime"] == "reversal_watch"
    assert data["data"]["upside_probability"] == 0.58
    assert data["data"]["expected_return_bp"] == 6.8
    assert data["data"]["suggested_position_pct"] == 8.0


def test_index_html_uses_cache_busted_local_assets(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "no-store" in response.headers.get("cache-control", "")
    assert "/static/js/chart.js?v=" in response.text
    assert "/static/js/candlestick.js?v=" in response.text
    assert "/static/js/websocket.js?v=" in response.text
    assert "/static/css/style.css?v=" in response.text


def test_candlestick_invalid_interval_uses_unified_error_payload(client):
    response = client.get("/api/price/candlestick?days=1&interval=5m")
    data = response.json()

    assert response.status_code == 400
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_INTERVAL"
    assert "Invalid interval" in data["detail"]


def test_advice_endpoint_uses_unified_error_payload_when_unavailable(client, monkeypatch):
    from app.api import analysis as analysis_api

    class FakeAdvisor:
        def analyze_cached(self):
            return None

    monkeypatch.setattr(analysis_api, "MarketAdvisor", FakeAdvisor)

    response = client.get("/api/analysis/advice")
    data = response.json()

    assert response.status_code == 503
    assert data["success"] is False
    assert data["error"]["code"] == "INSUFFICIENT_DATA"
    assert data["detail"]
