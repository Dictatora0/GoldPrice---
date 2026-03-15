import aiohttp
from bs4 import BeautifulSoup
from app.collectors.base import BaseCollector
from typing import Optional
import re
from config import settings


class GoldCNCollector(BaseCollector):
    """黄金价格采集器(使用上海黄金交易所延迟行情)"""

    def __init__(self, timeout: int = 10):
        super().__init__(timeout)
        self.url = "https://en.sgenow.cn/h5_data_DelayedQuotes"
        self.symbol = settings.sge_symbol

    @staticmethod
    def extract_price(html: str, symbol: str) -> Optional[float]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")
        if not table:
            return None

        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        price_index = None
        for idx, header in enumerate(headers):
            if "最新" in header or "Latest" in header:
                price_index = idx
                break
        if price_index is None:
            price_index = 1

        for row in table.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cols:
                continue
            if symbol not in cols[0] and all(symbol not in col for col in cols):
                continue
            if len(cols) <= price_index:
                continue
            try:
                value = float(cols[price_index])
                if value > 0:
                    return value
            except ValueError:
                return None
        return None

    async def fetch_price(self) -> Optional[float]:
        """从上海黄金交易所延迟行情页面获取黄金价格"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url, timeout=self.timeout) as response:
                if response.status == 200:
                    html = await response.text()
                    return self.extract_price(html, symbol=self.symbol)

        return None
