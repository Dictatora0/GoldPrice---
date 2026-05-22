from abc import ABC, abstractmethod
from typing import Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """数据采集器基类"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.source_name = self.__class__.__name__.replace("Collector", "").lower()

    @abstractmethod
    async def fetch_price(self) -> Optional[float]:
        """
        获取黄金价格(人民币/克)

        Returns:
            Optional[float]: 价格,如果获取失败返回 None
        """
        pass

    async def collect(self) -> Optional[float]:
        """
        采集数据并处理异常

        Returns:
            Optional[float]: 价格,如果获取失败返回 None
        """
        from app.monitoring.metrics import metrics_collector
        import time

        start_time = time.time()

        for attempt in range(1, 4):
            try:
                price = await self.fetch_price()
                if price and price > 0:
                    duration = time.time() - start_time

                    # Record success metrics
                    metrics_collector.record_collection_success(
                        source=self.source_name,
                        duration=duration
                    )

                    # Update price gauge
                    metrics_collector.update_price_gauge(
                        price=price,
                        source=self.source_name
                    )

                    logger.info("%s collected price: ¥%s/g", self.source_name, price)
                    return price
                logger.warning("%s returned invalid price: %s", self.source_name, price)
                metrics_collector.record_collection_failure(source=self.source_name)
                return None
            except Exception as e:
                logger.warning("%s attempt %s failed: %s", self.source_name, attempt, e)
                if attempt < 3:
                    await asyncio.sleep(5)

        # Record failure after all retries
        metrics_collector.record_collection_failure(source=self.source_name)
        logger.error("%s collection failed after retries", self.source_name)
        return None

    def save_price(
        self,
        price: float,
        metadata: dict = None,
        price_history_id: Optional[int] = None,
    ):
        """Save price to database using connection pool."""
        from app.database import get_db_session
        from app.models import PriceSource
        from app.cache import cache_manager

        if price_history_id is None and isinstance(metadata, int):
            price_history_id = metadata
            metadata = None

        if price_history_id is None:
            raise ValueError("price_history_id is required")

        with get_db_session() as session:
            price_source = PriceSource(
                price_history_id=price_history_id,
                source_name=self.source_name,
                price_cny_per_gram=price,
                is_valid=True
            )
            session.add(price_source)

        logger.info("Saved price: ¥%.2f", price)

        # After saving price to database, invalidate all cached data
        cache_manager.delete_pattern("gold:indicator:*")
        cache_manager.delete_pattern("gold:signal:*")
        cache_manager.delete_pattern("gold:analysis:*")
        cache_manager.delete_pattern("gold:price:*")
        cache_manager.delete_pattern("gold:history:*")
