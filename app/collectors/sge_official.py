import aiohttp
from bs4 import BeautifulSoup
from typing import Optional

from app.collectors.base import BaseCollector
from config import settings


class SGEOfficialCollector(BaseCollector):
    """上海黄金交易所官网延时行情采集器"""

    def __init__(self, timeout: int = 10):
        super().__init__(timeout)
        self.source_name = "sge_official"
        self.url = "https://www.sge.com.cn/sjzx/yshqbg"
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
            if "最新价" in header or "最新" in header:
                price_index = idx
                break
        if price_index is None:
            price_index = 1

        for row in table.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cols:
                continue
            if symbol not in cols[0]:
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
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(self.url, timeout=self.timeout) as response:
                if response.status == 200:
                    html = await response.text()
                    return self.extract_price(html, symbol=self.symbol)
        return None
