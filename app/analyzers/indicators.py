import pandas as pd
from typing import Dict, Optional
from app.database import get_db_session
from app.models import PriceHistory
from app.price_regime import filter_current_regime
from app.trading_thresholds import TradingThresholds
from app.cache import build_cache_key, get_json_cache, set_json_cache
from config import settings


class IndicatorCalculator:
    """技术指标计算器"""

    CACHE_SCHEMA_VERSION = "v2"

    def __init__(self):
        self.rsi_period = settings.rsi_period
        self.bollinger_period = settings.bollinger_period
        self.bollinger_std = settings.bollinger_std
        self.ma_short = settings.ma_short
        self.ma_medium = settings.ma_medium
        self.ma_long = settings.ma_long
        self.macd_fast_period = settings.macd_fast_period
        self.macd_slow_period = settings.macd_slow_period
        self.macd_signal_period = settings.macd_signal_period

    def get_price_data(self, days: int = 90, *, limit: Optional[int] = None) -> pd.DataFrame:
        """获取历史价格数据"""
        with get_db_session(read_only=True) as session:
            query = session.query(
                PriceHistory.timestamp,
                PriceHistory.price_cny_per_gram,
            ).order_by(PriceHistory.timestamp.desc())
            if limit is None:
                limit = days * 480
            records = query.limit(limit).all()

            if not records:
                return pd.DataFrame()

            filtered_records = filter_current_regime(
                list(reversed(records)),
                price_getter=lambda row: row[1],
            )

            df = pd.DataFrame([
                {
                    "timestamp": timestamp,
                    "price": price,
                }
                for timestamp, price in filtered_records
            ])

            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
            return df

    def calculate_ma(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算移动平均线"""
        if len(df) < self.ma_long:
            return {}

        return {
            "ma_short": df['price'].rolling(window=self.ma_short).mean().iloc[-1],
            "ma_medium": df['price'].rolling(window=self.ma_medium).mean().iloc[-1],
            "ma_long": df['price'].rolling(window=self.ma_long).mean().iloc[-1],
        }

    def calculate_bollinger_bands(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算布林带"""
        if len(df) < self.bollinger_period:
            return {}

        ma = df['price'].rolling(window=self.bollinger_period).mean()
        std = df['price'].rolling(window=self.bollinger_period).std()

        return {
            "bb_middle": ma.iloc[-1],
            "bb_upper": (ma + self.bollinger_std * std).iloc[-1],
            "bb_lower": (ma - self.bollinger_std * std).iloc[-1],
        }

    def calculate_rsi(self, df: pd.DataFrame) -> float:
        """计算相对强弱指标"""
        if len(df) < self.rsi_period + 1:
            return None

        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return rsi.iloc[-1]

    def calculate_volatility(self, df: pd.DataFrame, period: int = 30) -> float:
        """计算价格波动率"""
        if len(df) < period:
            return None

        return df['price'].tail(period).std()

    def calculate_ema(self, df: pd.DataFrame, period: int) -> pd.Series:
        """计算指数移动平均线"""
        return df['price'].ewm(span=period, adjust=False).mean()

    def calculate_macd(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算 MACD 指标

        返回值说明:
        - 数据不足时返回 None 值
        - API 端点应保留 None 值(不省略键)
        - 前端需处理 None 值显示为 "--"
        """
        if len(df) < self.macd_slow_period:
            return {
                "macd": None,
                "macd_signal": None,
                "macd_histogram": None,
                "macd_histogram_std": None,
            }

        ema_fast = self.calculate_ema(df, self.macd_fast_period)
        ema_slow = self.calculate_ema(df, self.macd_slow_period)
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.macd_signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        histogram_lookback = max(20, TradingThresholds.MACD_STD_LOOKBACK_POINTS)
        histogram_std = float(histogram.tail(histogram_lookback).std())

        return {
            "macd": float(macd_line.iloc[-1]),
            "macd_signal": float(signal_line.iloc[-1]),
            "macd_histogram": float(histogram.iloc[-1]),
            "macd_histogram_std": histogram_std,
        }

    def calculate_all(self) -> Optional[Dict]:
        """计算所有技术指标"""
        import math

        df = self.get_price_data()

        if df.empty:
            return None

        current_price = df['price'].iloc[-1]

        indicators = {
            "current_price": current_price,
            "rsi": self.calculate_rsi(df),
            "volatility": self.calculate_volatility(df),
        }

        # 添加移动平均线
        ma_indicators = self.calculate_ma(df)
        indicators.update(ma_indicators)

        # 添加布林带
        bb_indicators = self.calculate_bollinger_bands(df)
        indicators.update(bb_indicators)

        # 添加 MACD
        macd_indicators = self.calculate_macd(df)
        indicators.update(macd_indicators)

        # 过滤掉 NaN 和 Inf 值，替换为 None
        for key, value in indicators.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                indicators[key] = None

        return indicators

    def calculate_all_cached(self) -> Optional[Dict]:
        """计算所有技术指标(带缓存)"""
        from config import settings

        with get_db_session(read_only=True) as session:
            latest = session.query(PriceHistory.timestamp).order_by(
                PriceHistory.timestamp.desc()
            ).first()

            if not latest:
                return self.calculate_all()

            cache_key = build_cache_key("indicator", self.CACHE_SCHEMA_VERSION, latest[0].isoformat())

        cached = get_json_cache(cache_key)
        if cached is not None:
            return cached

        result = self.calculate_all()
        if result is None:
            return None

        set_json_cache(cache_key, result, settings.cache_indicators_ttl)

        return result
