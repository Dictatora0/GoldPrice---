from datetime import datetime, timedelta
import os

from fastapi.testclient import TestClient

from app.database import engine, get_db_session, init_db
from app.main import app
from app.models import PriceHistory, NotificationDeliveryLog
from config import settings


def _seed_prices():
    now = datetime.now().replace(second=0, microsecond=0)
    with get_db_session() as session:
        session.add(
            PriceHistory(
                timestamp=now - timedelta(days=1, minutes=5),
                price_cny_per_gram=590.0,
                source_count=2,
            )
        )
        session.add(
            PriceHistory(
                timestamp=now - timedelta(minutes=2),
                price_cny_per_gram=580.0,
                source_count=2,
            )
        )


def _new_client():
    engine.dispose()
    if os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    with TestClient(app) as test_client:
        init_db()
        yield test_client
    engine.dispose()


def test_custom_alert_crud_and_filtering():
    for client in _new_client():
        response = client.post(
            "/api/alerts?name=price-floor&rule_type=price_below&threshold=582&channels=system,webhook&cooldown_minutes=30&enabled=true"
        )
        assert response.status_code == 200
        created = response.json()["data"]
        assert created["name"] == "price-floor"
        assert created["rule_type"] == "price_below"
        assert created["channels"] == ["system", "webhook"]

        rule_id = created["id"]

        update_response = client.patch(f"/api/alerts/{rule_id}?enabled=false")
        assert update_response.status_code == 200
        assert update_response.json()["data"]["enabled"] is False

        list_enabled = client.get("/api/alerts?enabled_only=true")
        assert list_enabled.status_code == 200
        assert list_enabled.json()["items"] == []

        delete_response = client.delete(f"/api/alerts/{rule_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["success"] is True


def test_custom_alert_rule_rejects_invalid_payload():
    for client in _new_client():
        response = client.post(
            "/api/alerts?name=bad-rsi&rule_type=rsi_below&threshold=-1&channels=system&cooldown_minutes=30&enabled=true"
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["error"]["code"] == "INVALID_ALERT_RULE"


def test_custom_alert_rule_triggered_by_alert_manager():
    from app.monitoring.alerts import AlertManager

    for client in _new_client():
        _seed_prices()

        create_resp = client.post(
            "/api/alerts?name=drop-watch&rule_type=price_below&threshold=585&channels=system&cooldown_minutes=1&enabled=true"
        )
        assert create_resp.status_code == 200

        manager = AlertManager()
        sent_payloads = []

        def fake_send(rule_name, level, title, message, channels=None):
            sent_payloads.append(
                {
                    "rule_name": rule_name,
                    "level": level,
                    "title": title,
                    "message": message,
                    "channels": channels,
                }
            )
            return True

        manager.send_alert = fake_send
        manager._evaluate_custom_rules()

        assert sent_payloads
        assert sent_payloads[0]["rule_name"].startswith("custom_rule_")
        assert "价格触发下破阈值" in sent_payloads[0]["message"]


def test_delivery_logs_endpoint_filters():
    for client in _new_client():
        with get_db_session() as session:
            session.add(
                NotificationDeliveryLog(
                    rule_name="r1",
                    channel="email",
                    level="warning",
                    title="Email Test",
                    message="m1",
                    status="success",
                    attempt=1,
                    max_attempts=3,
                )
            )
            session.add(
                NotificationDeliveryLog(
                    rule_name="r2",
                    channel="wechat",
                    level="warning",
                    title="Wechat Test",
                    message="m2",
                    status="failed",
                    attempt=2,
                    max_attempts=3,
                    error_message="timeout",
                )
            )

        all_resp = client.get("/api/alerts/deliveries?limit=10")
        assert all_resp.status_code == 200
        assert len(all_resp.json()["items"]) >= 2

        failed_wechat = client.get("/api/alerts/deliveries?channel=wechat&status=failed&limit=10")
        assert failed_wechat.status_code == 200
        rows = failed_wechat.json()["items"]
        assert len(rows) == 1
        assert rows[0]["channel"] == "wechat"
        assert rows[0]["status"] == "failed"

        v1_resp = client.get("/api/v1/alerts/deliveries?channel=email&status=success&limit=10")
        assert v1_resp.status_code == 200
        v1_rows = v1_resp.json()["items"]
        assert len(v1_rows) == 1
        assert v1_rows[0]["channel"] == "email"
