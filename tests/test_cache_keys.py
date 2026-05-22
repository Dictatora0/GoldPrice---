from app.cache import build_cache_key, CacheManager, warm_cache


def test_build_cache_key_uses_gold_namespace():
    assert build_cache_key("price", "latest") == "gold:price:latest"
    assert build_cache_key("history", "sina", "30d") == "gold:history:sina:30d"


def test_cache_manager_reset_clears_stats():
    cache = CacheManager()
    cache.cache_hits = 3
    cache.cache_misses = 5

    cache.reset()

    assert cache.get_stats() == {
        "hits": 0,
        "misses": 0,
        "total_requests": 0,
        "hit_rate": 0.0,
    }


def test_warm_cache_counts_success_and_failure(monkeypatch):
    calls = []

    def fake_set(key, payload, ttl):
        calls.append((key, payload, ttl))
        return key.endswith("ok")

    monkeypatch.setattr("app.cache.set_json_cache", fake_set)

    result = warm_cache(
        [
            ("gold:price:ok", {"value": 1}, 10),
            ("gold:price:fail", {"value": 2}, 10),
        ]
    )

    assert result == {"warmed": 1, "failed": 1}
    assert len(calls) == 2
