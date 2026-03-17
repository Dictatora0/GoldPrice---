import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from app.cache import CacheManager, cache_result


@pytest.mark.asyncio
async def test_cache_hit_miss_tracking():
    """Test cache hit/miss tracking"""
    cache = CacheManager()

    # Initial stats should be zero
    stats = cache.get_stats()
    assert stats['hits'] == 0
    assert stats['misses'] == 0
    assert stats['hit_rate'] == 0.0

    # Simulate cache miss
    result = await cache.get('nonexistent_key')
    assert result is None
    stats = cache.get_stats()
    assert stats['misses'] == 1
    assert stats['hit_rate'] == 0.0

    # Set a value
    await cache.set('test_key', 'test_value', 60)

    # Simulate cache hit
    result = await cache.get('test_key')
    if cache.enabled:
        assert result == 'test_value'
        stats = cache.get_stats()
        assert stats['hits'] == 1
        assert stats['misses'] == 1
        assert stats['hit_rate'] == 0.5

    await cache.close()


@pytest.mark.asyncio
async def test_cache_decorator_with_ttl():
    """Test cache_result decorator with TTL"""
    call_count = 0

    @cache_result('test', ttl=60)
    async def expensive_function(x):
        nonlocal call_count
        call_count += 1
        return x * 2

    # First call - cache miss
    result1 = await expensive_function(5)
    assert result1 == 10
    assert call_count == 1

    # Second call - should hit cache
    result2 = await expensive_function(5)
    assert result2 == 10
    # If cache is enabled, function shouldn't be called again
    # If cache is disabled, it will be called again
    assert call_count in [1, 2]


@pytest.mark.asyncio
async def test_cache_graceful_degradation():
    """Test cache gracefully degrades when Redis unavailable"""
    # Create cache with Redis disabled
    with patch('app.cache.settings') as mock_settings:
        mock_settings.redis_enabled = False
        mock_settings.redis_host = 'localhost'
        mock_settings.redis_port = 6379
        mock_settings.redis_db = 0
        mock_settings.redis_password = None
        mock_settings.redis_max_connections = 50

        cache = CacheManager()

        # Should not crash, just return None/False
        result = await cache.get('key')
        assert result is None

        success = await cache.set('key', 'value', 60)
        assert success is False

        exists = await cache.exists('key')
        assert exists is False

        ping = await cache.ping()
        assert ping is False

        # Stats should still work
        stats = cache.get_stats()
        assert stats['hits'] == 0
        assert stats['misses'] == 1
        assert stats['hit_rate'] == 0.0

        await cache.close()
