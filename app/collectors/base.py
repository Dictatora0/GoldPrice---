from abc import ABC, abstractmethod
from typing import Optional
import asyncio
import logging
from datetime import datetime

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

                    logger.info(f"{self.source_name} collected price: ¥{price}/g")
                    return price
                logger.warning(f"{self.source_name} returned invalid price: {price}")
                metrics_collector.record_collection_failure(source=self.source_name)
                return None
            except Exception as e:
                logger.warning(
                    f"{self.source_name} attempt {attempt} failed: {e}"
                )
                if attempt < 3:
                    await asyncio.sleep(5)

        # Record failure after all retries
        metrics_collector.record_collection_failure(source=self.source_name)
        logger.error(f"{self.source_name} collection failed after retries")
        return None

    def save_price(self, price: float, metadata: dict = None):
        """Save price to database using connection pool."""
        from app.database import get_db_session
        from app.models import PriceSource
        from app.cache import cache_manager

        with get_db_session() as session:
            price_source = PriceSource(
                price_history_id=1,  # This would be set by the caller in practice
                source_name=self.source_name,
                price_cny_per_gram=price,
                is_valid=True
            )
            session.add(price_source)

        logger.info(f"Saved price: ¥{price:.2f}")

        # After saving price to database, invalidate all cached data
        cache_manager.delete_pattern("indicators:*")
        cache_manager.delete_pattern("signals:*")
        cache_manager.delete_pattern("analysis:*")
        cache_manager.delete_pattern("price:*")
        cache_manager.delete_pattern("history:*")
