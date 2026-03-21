from datetime import datetime, timedelta
from typing import Dict

import numpy as np

from app.database import get_db_session
from app.market_indicators import MarketIndicators
from app.models import PriceHistory
from app.price_regime import filter_current_regime
from app.trading_thresholds import TradingThresholds


def _calculate_momentum_acceleration(price_values: list[float]) -> float:
    if len(price_values) < 3:
        return 0.0

    if len(price_values) < 6:
        mid = max(1, len(price_values) // 2)
        first_half = price_values[:mid]
        second_half = price_values[mid:]
        if len(first_half) < 2 or len(second_half) < 2:
            return 0.0

        slope_first = (first_half[-1] - first_half[0]) / max(1, len(first_half) - 1)
        slope_second = (second_half[-1] - second_half[0]) / max(1, len(second_half) - 1)
        baseline = abs(price_values[0]) if price_values and price_values[0] else 1.0
        return (slope_second - slope_first) / baseline

    # 3点中位平滑，降低单点异常对斜率的破坏
    smoothed = np.array(price_values, dtype=float)
    smoothed = np.convolve(smoothed, np.array([0.25, 0.5, 0.25]), mode="same")
    smoothed[0] = price_values[0]
    smoothed[-1] = price_values[-1]

    half = len(smoothed) // 2
    first = smoothed[:half]
    second = smoothed[half:]
    if len(first) < 2 or len(second) < 2:
        return 0.0

    slope_first = float(np.polyfit(np.arange(len(first)), first, 1)[0])
    slope_second = float(np.polyfit(np.arange(len(second)), second, 1)[0])
    baseline = abs(price_values[0]) if price_values and price_values[0] else 1.0
    return (slope_second - slope_first) / baseline


def get_price_momentum(minutes: int = 30) -> dict:
    with get_db_session(read_only=True) as session:
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        prices = (
            session.query(PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= cutoff_time)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

    prices = filter_current_regime(prices, price_getter=lambda row: row[0])

    if len(prices) < 3:
        return {"change_pct": 0, "trend": "flat", "acceleration": 0}

    price_values = [price for (price,) in prices]
    first_price = price_values[0]
    last_price = price_values[-1]
    change_pct = ((last_price - first_price) / first_price) * 100

    if change_pct > TradingThresholds.MOMENTUM_TREND_UP_THRESHOLD:
        trend = "up"
    elif change_pct < TradingThresholds.MOMENTUM_TREND_DOWN_THRESHOLD:
        trend = "down"
    else:
        trend = "flat"

    acceleration = _calculate_momentum_acceleration(price_values)

    return {
        "change_pct": change_pct,
        "trend": trend,
        "acceleration": acceleration,
    }


def check_trend_alignment(short: str, mid: str, long: str) -> str:
    trends = [short, mid, long]

    if trends.count("bearish") >= 2:
        return "bearish_aligned"
    if trends.count("bullish") >= 2:
        return "bullish_aligned"
    return "mixed"


def _trend_threshold(window_hours: int) -> float:
    hours = max(1.0, float(window_hours))
    # 短周期允许更敏感，长周期提高阈值以减少噪声误判
    dynamic_threshold = (
        TradingThresholds.TREND_THRESHOLD_BASE
        + min(hours, 24.0) * TradingThresholds.TREND_THRESHOLD_PER_HOUR
    )
    return max(
        TradingThresholds.TREND_THRESHOLD_MIN,
        min(dynamic_threshold, TradingThresholds.TREND_THRESHOLD_MAX),
    )


def _get_trend(prices, *, window_hours: int) -> str:
    if len(prices) < 2:
        return "unknown"

    first = prices[0][0]
    last = prices[-1][0]
    change = ((last - first) / first) * 100
    threshold = _trend_threshold(window_hours)

    if change > threshold:
        return "bullish"
    if change < -threshold:
        return "bearish"
    return "neutral"


def analyze_multi_timeframe() -> Dict:
    with get_db_session(read_only=True) as session:
        now = datetime.now()
        short_term = (
            session.query(PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= now - timedelta(hours=1))
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )
        mid_term = (
            session.query(PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= now - timedelta(hours=6))
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )
        long_term = (
            session.query(PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= now - timedelta(hours=24))
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

    short_term = filter_current_regime(short_term, price_getter=lambda row: row[0])
    mid_term = filter_current_regime(mid_term, price_getter=lambda row: row[0])
    long_term = filter_current_regime(long_term, price_getter=lambda row: row[0])

    short = _get_trend(short_term, window_hours=1)
    mid = _get_trend(mid_term, window_hours=6)
    long = _get_trend(long_term, window_hours=24)

    return {
        "short_term": short,
        "mid_term": mid,
        "long_term": long,
        "alignment": check_trend_alignment(short, mid, long),
    }


def is_falling_knife(indicators: dict, momentum: dict, timeframe: dict) -> bool:
    macd_histogram = indicators.get("macd_histogram")

    return (
        timeframe.get("alignment") == "bearish_aligned"
        and momentum.get("trend") == "down"
        and momentum.get("acceleration", 0) <= 0
        and macd_histogram is not None
        and macd_histogram < -0.5
    )


def build_entry_context(indicators: dict, momentum: dict, timeframe: dict) -> dict:
    setup_flags = []
    confirmation_flags = []
    risk_flags = []

    typed = MarketIndicators.from_dict(indicators)
    price = typed.current_price
    bb_lower = typed.bb_lower
    ma_medium = typed.ma_medium
    macd_histogram = typed.macd_histogram

    if typed.rsi is not None:
        if typed.rsi < TradingThresholds.RSI_OVERSOLD_EXTREME:
            setup_flags.append("extreme_oversold")
        elif typed.rsi < TradingThresholds.RSI_OVERSOLD:
            setup_flags.append("oversold")
        elif typed.rsi < TradingThresholds.RSI_OVERSOLD_MILD:
            setup_flags.append("mild_oversold")

    if price is not None and bb_lower is not None and price < bb_lower:
        setup_flags.append("band_break")
    if price is not None and ma_medium is not None and price < ma_medium * 0.98:
        setup_flags.append("below_ma")

    if macd_histogram is not None:
        macd_std = typed.macd_histogram_std
        if macd_std is None or macd_std <= 0:
            macd_std = max(abs(macd_histogram), TradingThresholds.MACD_STD_FLOOR)

        stabilizing_threshold = TradingThresholds.MACD_STABILIZING_STD_MULTIPLIER * macd_std
        contracting_threshold = TradingThresholds.MACD_CONTRACTING_STD_MULTIPLIER * macd_std

        if macd_histogram >= stabilizing_threshold:
            confirmation_flags.append("macd_stabilizing")
        elif abs(macd_histogram) < contracting_threshold:
            confirmation_flags.append("macd_contracting")

    if momentum.get("acceleration", 0) > TradingThresholds.MOMENTUM_TURN_ACCELERATION:
        confirmation_flags.append("momentum_turn")
    elif (
        momentum.get("acceleration", 0) > TradingThresholds.SELLING_PRESSURE_EASING_ACCELERATION
        and abs(momentum.get("change_pct", 0)) < TradingThresholds.SELLING_PRESSURE_EASING_CHANGE_PCT
    ):
        confirmation_flags.append("selling_pressure_easing")

    if timeframe.get("alignment") != "bearish_aligned":
        confirmation_flags.append("trend_pressure_not_extreme")

    if is_falling_knife(indicators, momentum, timeframe):
        risk_flags.append("falling_knife")

    core_confirmation_flags = [
        flag
        for flag in confirmation_flags
        if flag in TradingThresholds.ENTRY_CORE_CONFIRMATION_FLAGS
    ]

    strong_entry = (
        len(setup_flags) >= TradingThresholds.ENTRY_SETUP_MIN_STRONG
        and len(confirmation_flags) >= TradingThresholds.ENTRY_CONFIRM_MIN_STRONG
        and len(core_confirmation_flags) >= TradingThresholds.ENTRY_CORE_CONFIRM_MIN
        and "falling_knife" not in risk_flags
    )
    weak_entry = (
        len(setup_flags) >= TradingThresholds.ENTRY_SETUP_MIN_WEAK
        and len(confirmation_flags) >= TradingThresholds.ENTRY_CONFIRM_MIN_WEAK
        and "falling_knife" not in risk_flags
    )

    return {
        "setup_flags": setup_flags,
        "confirmation_flags": confirmation_flags,
        "core_confirmation_flags": core_confirmation_flags,
        "risk_flags": risk_flags,
        "entry_ready": strong_entry,
        "entry_weak": weak_entry and not strong_entry,
    }
