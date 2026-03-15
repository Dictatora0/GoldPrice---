import asyncio

from app.collectors.base import BaseCollector


def test_collect_retries_and_succeeds():
    class FakeCollector(BaseCollector):
        def __init__(self):
            super().__init__(timeout=1)
            self.attempts = 0

        async def fetch_price(self):
            self.attempts += 1
            if self.attempts < 3:
                raise RuntimeError("fail")
            return 500.0

    collector = FakeCollector()
    price = asyncio.run(collector.collect())

    assert price == 500.0
    assert collector.attempts == 3


def test_collect_returns_none_after_retries():
    class FakeCollector(BaseCollector):
        def __init__(self):
            super().__init__(timeout=1)
            self.attempts = 0

        async def fetch_price(self):
            self.attempts += 1
            raise RuntimeError("fail")

    collector = FakeCollector()
    price = asyncio.run(collector.collect())

    assert price is None
    assert collector.attempts == 3
