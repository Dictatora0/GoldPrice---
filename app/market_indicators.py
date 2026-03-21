from dataclasses import dataclass
from typing import Any, Mapping, Optional


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MarketIndicators:
    current_price: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    macd_histogram_std: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_upper: Optional[float] = None
    ma_short: Optional[float] = None
    ma_medium: Optional[float] = None
    ma_long: Optional[float] = None
    volatility: Optional[float] = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MarketIndicators":
        source = payload or {}
        return cls(
            current_price=_safe_float(source.get("current_price")),
            rsi=_safe_float(source.get("rsi")),
            macd=_safe_float(source.get("macd")),
            macd_signal=_safe_float(source.get("macd_signal")),
            macd_histogram=_safe_float(source.get("macd_histogram")),
            macd_histogram_std=_safe_float(source.get("macd_histogram_std")),
            bb_lower=_safe_float(source.get("bb_lower")),
            bb_middle=_safe_float(source.get("bb_middle")),
            bb_upper=_safe_float(source.get("bb_upper")),
            ma_short=_safe_float(source.get("ma_short")),
            ma_medium=_safe_float(source.get("ma_medium")),
            ma_long=_safe_float(source.get("ma_long")),
            volatility=_safe_float(source.get("volatility")),
        )

    def bollinger_band_width_ratio(self) -> Optional[float]:
        if self.bb_lower is None or self.bb_upper is None or self.bb_middle in (None, 0):
            return None
        return (self.bb_upper - self.bb_lower) / self.bb_middle

    def bollinger_break_depth_ratio(self) -> Optional[float]:
        if self.current_price is None or self.bb_lower in (None, 0):
            return None
        if self.current_price >= self.bb_lower:
            return 0.0
        return (self.bb_lower - self.current_price) / self.bb_lower
