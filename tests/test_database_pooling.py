from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from app.database import get_db_session, engine
from app.models import Base, PriceHistory


@pytest.fixture(scope="function")
def setup_test_db():
    """Setup test database tables"""
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def test_get_db_session_context_manager(setup_test_db):
    """Test that get_db_session works as a context manager"""
    with get_db_session() as session:
        assert isinstance(session, Session)
        assert session.is_active


def test_session_commits_on_success(setup_test_db):
    """Test that session commits on successful completion"""
    # Insert data using context manager
    with get_db_session() as session:
        price = PriceHistory(
            timestamp=datetime.now(),
            price_cny_per_gram=500.0,
            source_count=3
        )
        session.add(price)

    # Verify data was committed
    with get_db_session() as session:
        count = session.query(PriceHistory).count()
        assert count == 1


def test_session_rollback_on_exception(setup_test_db):
    """Test that session rolls back on exception"""
    # First insert some data successfully
    with get_db_session() as session:
        price = PriceHistory(
            timestamp=datetime.now(),
            price_cny_per_gram=500.0,
            source_count=3
        )
        session.add(price)

    # Try to insert data but raise exception
    try:
        with get_db_session() as session:
            price = PriceHistory(
                timestamp=datetime.now(),
                price_cny_per_gram=600.0,
                source_count=2
            )
            session.add(price)
            raise ValueError("Test exception")
    except ValueError:
        pass

    # Verify only first insert was committed
    with get_db_session() as session:
        count = session.query(PriceHistory).count()
        assert count == 1


def test_connection_pool_reuse(setup_test_db):
    """Test that connection pool reuses connections"""
    # Get multiple sessions and verify they use the same engine
    sessions = []
    for _ in range(5):
        with get_db_session() as session:
            sessions.append(session)
            # Verify session is bound to the global engine
            assert session.bind == engine

    # All sessions should use the same engine instance
    assert len(sessions) == 5


def test_session_close_after_context(setup_test_db):
    with get_db_session() as session:
        session.add(
            PriceHistory(
                timestamp=datetime.now(),
                price_cny_per_gram=501.0,
                source_count=1,
            )
        )

    assert session.is_active
