from app.collectors.sina import SinaCollector
from app.collectors.eastmoney import EastMoneyCollector
from app.collectors.gold_cn import GoldCNCollector
from app.collectors.global_gold import GlobalGoldCollector
from typing import List, Dict, Tuple
from datetime import datetime
import asyncio
import logging
import statistics

logger = logging.getLogger(__name__)


class CollectorManager:
    """数据采集管理器"""

    def __init__(self, timeout: int = 10):
        self.collectors = [
            SinaCollector(timeout),
            EastMoneyCollector(timeout),
            GoldCNCollector(timeout),
            GlobalGoldCollector(timeout),
        ]

    @staticmethod
    def filter_outliers(
        prices: Dict[str, float], threshold: float = 0.03
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """
        过滤偏差过大的数据源

        Args:
            prices: 数据源价格字典
            threshold: 允许偏差比例(默认3%)

        Returns:
            (valid, invalid) 两个字典
        """
        if len(prices) <= 1:
            return prices, {}

        median_price = statistics.median(prices.values())
        if median_price <= 0:
            return prices, {}

        valid = {
            name: price
            for name, price in prices.items()
            if abs(price - median_price) / median_price <= threshold
        }
        invalid = {name: price for name, price in prices.items() if name not in valid}

        # 如果全部被过滤掉，回退为原始数据
        if not valid:
            return prices, {}

        return valid, invalid

    async def collect_all(self) -> Dict:
        """
        从所有数据源采集价格

        Returns:
            Dict: {
                "timestamp": datetime,
                "price_cny_per_gram": float,
                "sources": {"sina": float, "eastmoney": float, "gold_cn": float}
            }
        """
        tasks = [collector.collect() for collector in self.collectors]
        results = await asyncio.gather(*tasks)

        # 构建数据源字典
        sources = {}
        valid_prices = []

        for collector, price in zip(self.collectors, results):
            if price is not None:
                sources[collector.source_name] = price
                valid_prices.append(price)

        if not valid_prices:
            logger.error("All data sources failed")
            return None

        # 过滤异常值
        filtered_sources, invalid_sources = self.filter_outliers(sources)
        if invalid_sources:
            logger.warning(f"Outlier sources filtered: {list(invalid_sources.keys())}")

        valid_prices = list(filtered_sources.values())

        # 计算均价
        avg_price = sum(valid_prices) / len(valid_prices)

        return {
            "timestamp": datetime.now(),
            "price_cny_per_gram": round(avg_price, 2),
            "sources": filtered_sources,
            "invalid_sources": invalid_sources,
        }
