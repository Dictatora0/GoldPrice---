from datetime import datetime, timedelta
import os

import pytest
from fastapi.testclient import TestClient

from app.database import init_db, get_db_session, engine
from app.models import PriceHistory, AnalysisSignal
from config import settings
from app.main import app


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


def seed_signal(ts, price):
    with get_db_session() as session:
        session.add(
            AnalysisSignal(
                timestamp=ts,
                signal_type="buy",
                price_cny_per_gram=price,
                indicators="{}",
                notified=True,
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
    base = datetime.now() - timedelta(hours=2)
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
    # Expect last value per hour bucket (3 buckets: 23:00, 00:00, 01:00)
    assert len(data["items"]) == 3
    assert data["items"][0]["price_cny_per_gram"] == 481.0
    assert data["items"][1]["price_cny_per_gram"] == 483.0
    assert data["items"][2]["price_cny_per_gram"] == 484.0


def test_signals_endpoint_returns_recent(client):
    now = datetime.now()
    seed_signal(now - timedelta(hours=1), 470.0)

    response = client.get("/api/analysis/signals?days=7")
    data = response.json()

    assert response.status_code == 200
    assert len(data["items"]) == 1
    assert data["items"][0]["signal_type"] == "buy"


def test_metrics_endpoint(client):
    """Test Prometheus metrics endpoint."""
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    # Check for some expected metrics
    content = response.text
    assert "gold_http_requests_total" in content or "gold_collector_success_total" in content

