import aiohttp
import re
from typing import Optional

from app.collectors.base import BaseCollector


TROY_OUNCE_TO_GRAMS = 31.1034768


class GlobalGoldCollector(BaseCollector):
    """基于国际金价和实时汇率换算的备用黄金价格采集器"""

    def __init__(self, timeout: int = 10):
        super().__init__(timeout)
        self.source_name = "global_gold"
        self.gold_url = "https://qt.gtimg.cn/q=hf_GC"
        self.fx_url = "https://hq.sinajs.cn/list=fx_susdcny"

    @staticmethod
    def extract_usd_gold_price(text: str) -> Optional[float]:
        match = re.search(r'="([^"]+)"', text)
        if not match:
            return None

        fields = match.group(1).split(",")
        if len(fields) < 1:
            return None

        try:
            price = float(fields[0])
            return price if price > 0 else None
        except ValueError:
            return None

    @staticmethod
    def extract_usdcny_rate(text: str) -> Optional[float]:
        match = re.search(r'="([^"]+)"', text)
        if not match:
            return None

        fields = match.group(1).split(",")
        if len(fields) < 2:
            return None

        for field in fields[1:3]:
            try:
                value = float(field)
                if value > 0:
                    return value
            except ValueError:
                continue

        return None

    @staticmethod
    def convert_to_cny_per_gram(usd_per_ounce: float, usd_cny: float) -> float:
        return usd_per_ounce * usd_cny / TROY_OUNCE_TO_GRAMS

    async def fetch_price(self) -> Optional[float]:
        headers = {"User-Agent": "Mozilla/5.0"}
        fx_headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(self.gold_url, timeout=self.timeout) as response:
                if response.status != 200:
                    return None
                gold_text = await response.text(encoding="gbk", errors="ignore")

        async with aiohttp.ClientSession(headers=fx_headers) as session:
            async with session.get(self.fx_url, timeout=self.timeout) as response:
                if response.status != 200:
                    return None
                fx_text = await response.text(encoding="gbk", errors="ignore")

        usd_per_ounce = self.extract_usd_gold_price(gold_text)
        usd_cny = self.extract_usdcny_rate(fx_text)

        if usd_per_ounce is None or usd_cny is None:
            return None

        return round(self.convert_to_cny_per_gram(usd_per_ounce, usd_cny), 2)
