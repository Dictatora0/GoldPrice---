import asyncio

from app.collectors import CollectorManager
from app.collectors.global_gold import GlobalGoldCollector
from app.collectors.sge_official import SGEOfficialCollector
from app.source_quality import calculate_consensus_price


def test_filter_outliers_excludes_large_deviation():
    prices = {
        "sina": 100.0,
        "eastmoney": 102.0,
        "gold_cn": 150.0,
    }

    valid, invalid = CollectorManager.filter_outliers(prices, threshold=0.03)

    assert set(valid.keys()) == {"sina", "eastmoney"}
    assert set(invalid.keys()) == {"gold_cn"}


def test_collect_all_includes_invalid_sources():
    class FakeCollector:
        def __init__(self, name, price):
            self.source_name = name
            self._price = price

        async def collect(self):
            return self._price

    manager = CollectorManager(timeout=1)
    manager.collectors = [
        FakeCollector("sina", 100.0),
        FakeCollector("eastmoney", 102.0),
        FakeCollector("gold_cn", 150.0),
    ]

    result = asyncio.run(manager.collect_all())

    assert "invalid_sources" in result
    assert set(result["invalid_sources"].keys()) == {"gold_cn"}


def test_collector_manager_registers_global_gold_backup():
    manager = CollectorManager(timeout=1)

    assert any(isinstance(collector, GlobalGoldCollector) for collector in manager.collectors)
    assert any(isinstance(collector, SGEOfficialCollector) for collector in manager.collectors)


def test_consensus_price_downweights_backup_and_unhealthy_sources():
    source_entries = [
        {
            "name": "gold_cn",
            "price_cny_per_gram": 600.0,
            "is_valid": True,
            "trust_tier": "high",
            "trust_score": 0.92,
            "is_backup": False,
            "health": {"recent_valid_rate_pct": 100.0},
        },
        {
            "name": "sina",
            "price_cny_per_gram": 601.0,
            "is_valid": True,
            "trust_tier": "medium",
            "trust_score": 0.78,
            "is_backup": False,
            "health": {"recent_valid_rate_pct": 95.0},
        },
        {
            "name": "global_gold",
            "price_cny_per_gram": 608.0,
            "is_valid": True,
            "trust_tier": "low",
            "trust_score": 0.58,
            "is_backup": True,
            "health": {"recent_valid_rate_pct": 45.0},
        },
    ]

    result = calculate_consensus_price(source_entries)

    assert result["method"] == "weighted_trust_mean"
    assert result["price_cny_per_gram"] < 603.0


def test_consensus_price_prefers_primary_trusted_sources_when_consensus_is_tight():
    source_entries = [
        {
            "name": "gold_cn",
            "price_cny_per_gram": 600.0,
            "is_valid": True,
            "trust_tier": "high",
            "trust_score": 0.92,
            "is_backup": False,
            "health": {"recent_valid_rate_pct": 100.0},
        },
        {
            "name": "gold_cn_secondary",
            "price_cny_per_gram": 600.2,
            "is_valid": True,
            "trust_tier": "high",
            "trust_score": 0.9,
            "is_backup": False,
            "health": {"recent_valid_rate_pct": 100.0},
        },
        {
            "name": "global_gold",
            "price_cny_per_gram": 601.4,
            "is_valid": True,
            "trust_tier": "low",
            "trust_score": 0.58,
            "is_backup": True,
            "health": {"recent_valid_rate_pct": 95.0},
        },
    ]

    result = calculate_consensus_price(source_entries)

    assert result["method"] == "primary_trusted_anchor"
    assert result["price_cny_per_gram"] == 600.1


def test_consensus_price_marks_backup_only_when_primary_source_missing():
    source_entries = [
        {
            "name": "sina",
            "price_cny_per_gram": 601.0,
            "is_valid": True,
            "trust_tier": "medium",
            "trust_score": 0.78,
            "is_backup": False,
            "health": {"recent_valid_rate_pct": 92.0},
        },
        {
            "name": "global_gold",
            "price_cny_per_gram": 601.6,
            "is_valid": True,
            "trust_tier": "low",
            "trust_score": 0.58,
            "is_backup": True,
            "health": {"recent_valid_rate_pct": 88.0},
        },
    ]

    result = calculate_consensus_price(source_entries)

    assert result["method"] == "secondary_weighted"
