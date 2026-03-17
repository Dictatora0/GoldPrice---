import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from app.monitoring.alerts import AlertManager, AlertRule, alert_manager


class TestAlertManager:
    """Test AlertManager functionality"""

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

    @patch('app.monitoring.alerts.apprise.Apprise.notify')
    def test_send_alert_respects_cooldown(self, mock_notify):
        """Test that alerts respect cooldown period"""
        manager = AlertManager()
        mock_notify.return_value = True

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
