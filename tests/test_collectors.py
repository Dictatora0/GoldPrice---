import asyncio

from app.collectors import CollectorManager
from app.collectors.global_gold import GlobalGoldCollector


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
