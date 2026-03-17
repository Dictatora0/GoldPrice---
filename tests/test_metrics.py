import pytest
from app.monitoring.metrics import metrics_collector


def test_record_collection_success():
    """Test recording successful collection."""
    initial_value = metrics_collector.collection_success.labels(source="test")._value.get()

    metrics_collector.record_collection_success(source="test", duration=0.5)

    final_value = metrics_collector.collection_success.labels(source="test")._value.get()
    assert final_value > initial_value


def test_record_collection_failure():
    """Test recording collection failure."""
    initial_value = metrics_collector.collection_failure.labels(source="test")._value.get()

    metrics_collector.record_collection_failure(source="test")

    final_value = metrics_collector.collection_failure.labels(source="test")._value.get()
    assert final_value > initial_value


def test_record_cache_hit():
    """Test recording cache hit."""
    initial_value = metrics_collector.cache_hits.labels(key_prefix="test")._value.get()

    metrics_collector.record_cache_hit(key_prefix="test")

    final_value = metrics_collector.cache_hits.labels(key_prefix="test")._value.get()
    assert final_value > initial_value


def test_record_cache_miss():
    """Test recording cache miss."""
    initial_value = metrics_collector.cache_misses.labels(key_prefix="test")._value.get()

    metrics_collector.record_cache_miss(key_prefix="test")

    final_value = metrics_collector.cache_misses.labels(key_prefix="test")._value.get()
    assert final_value > initial_value


def test_update_price_gauge():
    """Test updating current price gauge."""
    metrics_collector.update_price_gauge(price=1850.50, source="test")

    value = metrics_collector.current_price.labels(source="test")._value.get()
    assert value == 1850.50
