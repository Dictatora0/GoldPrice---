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
        for attempt in range(1, 4):
            try:
                price = await self.fetch_price()
                if price and price > 0:
                    logger.info(f"{self.source_name} collected price: ¥{price}/g")
                    return price
                logger.warning(f"{self.source_name} returned invalid price: {price}")
                return None
            except Exception as e:
                logger.warning(
                    f"{self.source_name} attempt {attempt} failed: {e}"
                )
                if attempt < 3:
                    await asyncio.sleep(5)

        logger.error(f"{self.source_name} collection failed after retries")
        return None
