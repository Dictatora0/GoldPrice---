import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from app.monitoring.alerts import AlertManager, AlertRule, alert_manager
from app.database import get_db_session, init_db
from app.models import NotificationDeliveryLog


class TestAlertManager:
    """Test AlertManager functionality"""

    @pytest.fixture(autouse=True)
    def _ensure_tables(self):
        init_db()

    def test_alert_manager_initialization(self):
        """Test that alert manager initializes correctly"""
        manager = AlertManager()
        assert manager.apprise is not None
        assert isinstance(manager.last_alert_time, dict)
        assert isinstance(manager.rules, list)
        assert len(manager.rules) == 5  # Should have 5 rules

    def test_alert_rule_names(self):
        """Test that all expected alert rules are registered"""
        manager = AlertManager()
        rule_names = [rule.name for rule in manager.rules]

        assert "collector_failure" in rule_names
        assert "price_spike" in rule_names
        assert "redis_down" in rule_names
        assert "high_memory" in rule_names
        assert "too_many_connections" in rule_names

    def test_alert_manager_registers_optional_custom_channels(self, monkeypatch):
        monkeypatch.setattr("app.monitoring.alerts.settings.alert_email_url", "mailto://example.com")
        monkeypatch.setattr("app.monitoring.alerts.settings.alert_wechat_url", "wxpusher://token")

        manager = AlertManager()
        assert manager.apprise is not None

    def test_alert_cooldown(self):
        """Test alert cooldown mechanism"""
        manager = AlertManager()

        # First alert should be sent
        assert manager._should_send_alert("test_rule") is True

        # Mark as sent
        manager.last_alert_time["test_rule"] = datetime.now()

        # Second alert should be blocked by cooldown
        assert manager._should_send_alert("test_rule") is False

        # After cooldown period, should be allowed
        manager.last_alert_time["test_rule"] = datetime.now() - timedelta(minutes=31)
        assert manager._should_send_alert("test_rule") is True

    @patch('app.monitoring.alerts.AlertManager.send_alert')
    def test_evaluate_rules_no_alerts(self, mock_send):
        """Test rule evaluation when no conditions are met"""
        manager = AlertManager()

        # Mock all conditions to return False
        for rule in manager.rules:
            rule.condition = lambda: False

        manager.evaluate_rules()

        # No alerts should be sent
        mock_send.assert_not_called()

    @patch('app.monitoring.alerts.AlertManager.send_alert')
    def test_evaluate_rules_with_alert(self, mock_send):
        """Test rule evaluation when a condition is met"""
        manager = AlertManager()

        # Mock one condition to return True
        manager.rules[0].condition = lambda: True

        # Mock other conditions to return False
        for rule in manager.rules[1:]:
            rule.condition = lambda: False

        manager.evaluate_rules()

        # One alert should be sent
        assert mock_send.call_count == 1

    @patch('app.monitoring.alerts.apprise.Apprise.notify')
    def test_send_alert_success(self, mock_notify):
        """Test successful alert sending"""
        manager = AlertManager()
        mock_notify.return_value = True
        manager.channel_clients["system"] = manager.apprise

        manager.send_alert(
            rule_name="test_rule",
            level="warning",
            title="Test Alert",
            message="This is a test",
            channels=["macos"]
        )

        # Verify notify was called
        mock_notify.assert_called_once()

        # Verify last alert time was updated
        assert "test_rule" in manager.last_alert_time

    def test_send_alert_routes_by_channel(self):
        manager = AlertManager()

        class FakeClient:
            def __init__(self):
                self.calls = 0

            def notify(self, title, body):
                self.calls += 1
                return True

        webhook_client = FakeClient()
        email_client = FakeClient()
        manager.channel_clients["webhook"] = webhook_client
        manager.channel_clients["email"] = email_client
        manager.last_alert_time["route_rule"] = datetime.now() - timedelta(hours=1)

        manager.send_alert(
            rule_name="route_rule",
            level="warning",
            title="Route Test",
            message="route",
            channels=["webhook"],
        )

        assert webhook_client.calls == 1
        assert email_client.calls == 0

    def test_send_alert_retries_and_logs_for_email(self):
        manager = AlertManager()
        with get_db_session() as session:
            session.query(NotificationDeliveryLog).filter(
                NotificationDeliveryLog.rule_name == "email_retry_rule"
            ).delete()

        class FlakyClient:
            def __init__(self):
                self.calls = 0

            def notify(self, title, body):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("temporary email error")
                return True

        manager.channel_clients["email"] = FlakyClient()
        manager.last_alert_time["email_retry_rule"] = datetime.now() - timedelta(hours=1)

        delivered = manager.send_alert(
            rule_name="email_retry_rule",
            level="warning",
            title="Email Retry Test",
            message="retry please",
            channels=["email"],
        )

        assert delivered is True

        with get_db_session(read_only=True) as session:
            log_pairs = (
                session.query(NotificationDeliveryLog)
                .filter(NotificationDeliveryLog.rule_name == "email_retry_rule")
                .order_by(NotificationDeliveryLog.id.asc())
                .all()
            )
            pairs = [(row.status, row.attempt) for row in log_pairs]
        assert len(pairs) == 2
        assert pairs[0] == ("failed", 1)
        assert pairs[1] == ("success", 2)

    def test_send_alert_logs_unconfigured_wechat_channel(self):
        manager = AlertManager()
        with get_db_session() as session:
            session.query(NotificationDeliveryLog).filter(
                NotificationDeliveryLog.rule_name == "wechat_missing_rule"
            ).delete()
        manager.last_alert_time["wechat_missing_rule"] = datetime.now() - timedelta(hours=1)
        manager.channel_clients.pop("wechat", None)

        delivered = manager.send_alert(
            rule_name="wechat_missing_rule",
            level="warning",
            title="Wechat Missing",
            message="no channel config",
            channels=["wechat"],
        )
        assert delivered is False

        with get_db_session(read_only=True) as session:
            log = (
                session.query(NotificationDeliveryLog)
                .filter(NotificationDeliveryLog.rule_name == "wechat_missing_rule")
                .order_by(NotificationDeliveryLog.id.desc())
                .first()
            )
            payload = None
            if log is not None:
                payload = (log.channel, log.status, log.error_message or "")
        assert payload is not None
        assert payload[0] == "wechat"
        assert payload[1] == "failed"
        assert "not configured" in payload[2]

    def test_send_alert_system_channel_single_attempt(self):
        manager = AlertManager()
        with get_db_session() as session:
            session.query(NotificationDeliveryLog).filter(
                NotificationDeliveryLog.rule_name == "system_once_rule"
            ).delete()

        class SuccessClient:
            def __init__(self):
                self.calls = 0

            def notify(self, title, body):
                self.calls += 1
                return True

        client = SuccessClient()
        manager.channel_clients["system"] = client
        manager.last_alert_time["system_once_rule"] = datetime.now() - timedelta(hours=1)

        delivered = manager.send_alert(
            rule_name="system_once_rule",
            level="warning",
            title="System One Shot",
            message="system channel",
            channels=["system"],
        )

        assert delivered is True
        assert client.calls == 1

        with get_db_session(read_only=True) as session:
            log = (
                session.query(NotificationDeliveryLog)
                .filter(NotificationDeliveryLog.rule_name == "system_once_rule")
                .order_by(NotificationDeliveryLog.id.desc())
                .first()
            )
            payload = None
            if log is not None:
                payload = (log.channel, log.max_attempts, log.status)
        assert payload is not None
        assert payload[0] == "system"
        assert payload[1] == 1
        assert payload[2] == "success"

    def test_send_alert_deduplicates_shared_client(self):
        manager = AlertManager()

        class SuccessClient:
            def __init__(self):
                self.calls = 0

            def notify(self, title, body):
                self.calls += 1
                return True

        shared = SuccessClient()
        manager.channel_clients["webhook"] = shared
        manager.channel_clients["slack"] = shared
        manager.last_alert_time["shared_client_rule"] = datetime.now() - timedelta(hours=1)

        delivered = manager.send_alert(
            rule_name="shared_client_rule",
            level="warning",
            title="Shared Client",
            message="one delivery expected",
            channels=["webhook", "slack"],
        )

        assert delivered is True
        assert shared.calls == 1

    @patch('app.monitoring.alerts.apprise.Apprise.notify')
    def test_send_alert_respects_cooldown(self, mock_notify):
        """Test that alerts respect cooldown period"""
        manager = AlertManager()
        mock_notify.return_value = True
        manager.channel_clients["system"] = manager.apprise

        # Send first alert
        manager.send_alert(
            rule_name="test_rule",
            level="warning",
            title="Test Alert",
            message="This is a test",
            channels=["macos"]
        )

        # Try to send second alert immediately
        manager.send_alert(
            rule_name="test_rule",
            level="warning",
            title="Test Alert",
            message="This is a test",
            channels=["macos"]
        )

        # Should only be called once due to cooldown
        assert mock_notify.call_count == 1

    def test_alert_rule_dataclass(self):
        """Test AlertRule dataclass"""
        rule = AlertRule(
            name="test_rule",
            level="critical",
            condition=lambda: True,
            message="Test message",
            channels=["macos", "webhook"]
        )

        assert rule.name == "test_rule"
        assert rule.level == "critical"
        assert rule.condition() is True
        assert rule.message == "Test message"
        assert rule.channels == ["macos", "webhook"]

    def test_global_alert_manager_instance(self):
        """Test that global alert_manager instance exists"""
        assert alert_manager is not None
        assert isinstance(alert_manager, AlertManager)
