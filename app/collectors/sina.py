import aiohttp
from app.collectors.base import BaseCollector
from typing import Optional
import re
from config import settings


class SinaCollector(BaseCollector):
    """新浪财经黄金价格采集器"""

    def __init__(self, timeout: int = 10):
        super().__init__(timeout)
        self.symbol = settings.sina_symbol
        self.url = f"https://hq.sinajs.cn/list={self.symbol}"

    @staticmethod
    def parse_price(text: str) -> Optional[float]:
        match = re.search(r'="([^"]+)"', text)
        if not match:
            return None
        fields = match.group(1).split(",")
        if len(fields) < 2:
            return None
        # Prefer the first numeric field after the name
        for field in fields[1:]:
            try:
                value = float(field)
                if value > 0:
                    return value
            except ValueError:
                continue
        return None

    async def fetch_price(self) -> Optional[float]:
        """从新浪财经接口获取黄金价格"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url, timeout=self.timeout) as response:
                if response.status == 200:
                    text = await response.text(encoding="gbk", errors="ignore")
                    return self.parse_price(text)

        return None
