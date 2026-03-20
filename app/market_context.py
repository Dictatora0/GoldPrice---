from datetime import datetime, timedelta
from typing import Dict

from app.database import get_db_session
from app.models import PriceHistory
from app.price_regime import filter_current_regime


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

    if change_pct > 0.1:
        trend = "up"
    elif change_pct < -0.1:
        trend = "down"
    else:
        trend = "flat"

    mid = len(price_values) // 2
    first_half_change = (price_values[mid] - price_values[0]) / price_values[0]
    second_half_change = (price_values[-1] - price_values[mid]) / price_values[mid]
    acceleration = second_half_change - first_half_change

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


def _get_trend(prices) -> str:
    if len(prices) < 2:
        return "unknown"

    first = prices[0][0]
    last = prices[-1][0]
    change = ((last - first) / first) * 100

    if change > 0.5:
        return "bullish"
    if change < -0.5:
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

    short = _get_trend(short_term)
    mid = _get_trend(mid_term)
    long = _get_trend(long_term)

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

    price = indicators.get("current_price")
    rsi = indicators.get("rsi")
    bb_lower = indicators.get("bb_lower")
    ma_medium = indicators.get("ma_medium")
    macd_histogram = indicators.get("macd_histogram")

    if rsi is not None and rsi < 35:
        setup_flags.append("oversold")
    if price is not None and bb_lower is not None and price < bb_lower:
        setup_flags.append("band_break")
    if price is not None and ma_medium is not None and price < ma_medium * 0.98:
        setup_flags.append("below_ma")

    if macd_histogram is not None:
        if macd_histogram >= -0.12:
            confirmation_flags.append("macd_stabilizing")
        elif abs(macd_histogram) < 0.3:
            confirmation_flags.append("macd_contracting")

    if momentum.get("acceleration", 0) > 0:
        confirmation_flags.append("momentum_turn")
    elif momentum.get("acceleration", 0) > -0.002 and abs(momentum.get("change_pct", 0)) < 0.6:
        confirmation_flags.append("selling_pressure_easing")

    if timeframe.get("alignment") != "bearish_aligned":
        confirmation_flags.append("trend_pressure_not_extreme")

    if is_falling_knife(indicators, momentum, timeframe):
        risk_flags.append("falling_knife")

    core_confirmation_flags = [
        flag
        for flag in confirmation_flags
        if flag in {"macd_stabilizing", "macd_contracting", "momentum_turn"}
    ]

    entry_ready = (
        len(setup_flags) >= 2
        and len(confirmation_flags) >= 2
        and len(core_confirmation_flags) >= 1
        and "falling_knife" not in risk_flags
    )

    return {
        "setup_flags": setup_flags,
        "confirmation_flags": confirmation_flags,
        "core_confirmation_flags": core_confirmation_flags,
        "risk_flags": risk_flags,
        "entry_ready": entry_ready,
    }
