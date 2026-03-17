"""Tests for PostgreSQL logging functionality."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import logging

from app.log_models import LogEntry, get_log_engine, init_log_db, PostgreSQLLogHandler
from config import settings


class TestLogEntry:
    """Test LogEntry model."""

    def test_log_entry_creation(self):
        """Test creating a log entry."""
        log = LogEntry(
            timestamp=datetime.now(),
            level="INFO",
            logger="test_logger",
            event="test_event",
            message="Test message",
            context={"key": "value"},
            request_id="req-123"
        )
        assert log.level == "INFO"
        assert log.logger == "test_logger"
        assert log.event == "test_event"
        assert log.message == "Test message"
        assert log.context == {"key": "value"}
        assert log.request_id == "req-123"


class TestLogEngine:
    """Test log database engine functions."""

    @patch('app.log_models.settings')
    def test_get_log_engine_disabled(self, mock_settings):
        """Test get_log_engine when logging is disabled."""
        mock_settings.log_to_postgres = False
        engine = get_log_engine()
        assert engine is None

    @patch('app.log_models.create_engine')
    @patch('app.log_models.settings')
    def test_get_log_engine_success(self, mock_settings, mock_create_engine):
        """Test successful log engine creation."""
        mock_settings.log_to_postgres = True
        mock_settings.postgres_user = "user"
        mock_settings.postgres_password = "pass"
        mock_settings.postgres_host = "localhost"
        mock_settings.postgres_port = 5432
        mock_settings.postgres_db = "testdb"

        mock_engine = Mock()
        mock_create_engine.return_value = mock_engine

        engine = get_log_engine()
        assert engine == mock_engine
        mock_create_engine.assert_called_once()

    @patch('app.log_models.create_engine')
    @patch('app.log_models.settings')
    def test_get_log_engine_failure(self, mock_settings, mock_create_engine):
        """Test log engine creation failure."""
        mock_settings.log_to_postgres = True
        mock_settings.postgres_user = "user"
        mock_settings.postgres_password = "pass"
        mock_settings.postgres_host = "localhost"
        mock_settings.postgres_port = 5432
        mock_settings.postgres_db = "testdb"

        mock_create_engine.side_effect = Exception("Connection failed")

        engine = get_log_engine()
        assert engine is None


class TestPostgreSQLLogHandler:
    """Test PostgreSQL log handler."""

    @patch('app.log_models.settings')
    def test_handler_emit_disabled(self, mock_settings):
        """Test handler when logging is disabled."""
        mock_settings.log_to_postgres = False
        handler = PostgreSQLLogHandler()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )

        # Should not raise any exception
        handler.emit(record)

    @patch('app.log_models.get_log_session')
    @patch('app.log_models.settings')
    def test_handler_emit_success(self, mock_settings, mock_get_session):
        """Test successful log emission."""
        mock_settings.log_to_postgres = True

        mock_session = Mock()
        mock_get_session.return_value = mock_session

        handler = PostgreSQLLogHandler()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.event = "test_event"
        record.context = {"key": "value"}
        record.request_id = "req-123"

        handler.emit(record)

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    @patch('app.log_models.get_log_session')
    @patch('app.log_models.settings')
    def test_handler_emit_failure(self, mock_settings, mock_get_session):
        """Test log emission failure handling."""
        mock_settings.log_to_postgres = True

        mock_session = Mock()
        mock_session.add.side_effect = Exception("Database error")
        mock_get_session.return_value = mock_session

        handler = PostgreSQLLogHandler()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )

        # Should not raise exception (silently fails)
        handler.emit(record)


class TestLogCleanup:
    """Test log cleanup functionality."""

    def test_cleanup_old_logs_disabled(self):
        """Test cleanup when logging is disabled."""
        # Import and test directly without mocking settings
        # The function checks settings.log_to_postgres internally
        from app.main import cleanup_old_logs

        # Should not raise exception even if PostgreSQL is not configured
        cleanup_old_logs()

    @patch('app.log_models.get_log_session')
    def test_cleanup_old_logs_no_connection(self, mock_get_session):
        """Test cleanup when database connection fails."""
        from app.main import cleanup_old_logs

        mock_get_session.return_value = None

        # Should not raise exception
        cleanup_old_logs()
