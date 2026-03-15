import aiohttp
from app.collectors.base import BaseCollector
from typing import Optional, Dict, Any
from config import settings


class EastMoneyCollector(BaseCollector):
    """东方财富网黄金价格采集器"""

    def __init__(self, timeout: int = 10):
        super().__init__(timeout)
        self.url = "https://push2.eastmoney.com/api/qt/clist/get"
        self.fs = settings.eastmoney_fs
        self.code = settings.eastmoney_code
        self.name = settings.eastmoney_name

    @staticmethod
    def extract_price(payload: Dict[str, Any], code: Optional[str] = None, name: Optional[str] = None) -> Optional[float]:
        diff = payload.get("data", {}).get("diff", [])
        if not diff:
            return None

        if code:
            for item in diff:
                if str(item.get("f12")) == code:
                    try:
                        value = float(item.get("f2"))
                        if value > 0:
                            return value
                    except (TypeError, ValueError):
                        return None

        if name:
            for item in diff:
                if name in str(item.get("f14")):
                    try:
                        value = float(item.get("f2"))
                        if value > 0:
                            return value
                    except (TypeError, ValueError):
                        return None

        return None

    async def fetch_price(self) -> Optional[float]:
        """从东方财富网接口获取黄金价格"""
        async with aiohttp.ClientSession() as session:
            params = {
                "pn": 1,
                "pz": 200,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f3",
                "fs": self.fs,
                "fields": "f12,f14,f2",
            }
            async with session.get(self.url, params=params, timeout=self.timeout) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    return self.extract_price(data, code=self.code, name=self.name)

        return None
