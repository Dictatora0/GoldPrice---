from typing import Dict, Optional

from app.analyzers.probability_model import predict_upside_probability
from app.market_indicators import MarketIndicators
from app.market_context import analyze_multi_timeframe, build_entry_context, get_price_momentum, is_falling_knife
from app.trading_thresholds import TradingThresholds


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _to_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _derive_regime(
    entry_ready: bool,
    entry_weak: bool,
    setup_flags: list[str],
    risk_flags: list[str],
    momentum: Dict,
    timeframe: Dict,
) -> str:
    if "falling_knife" in risk_flags:
        return "risk_off_falling_knife"

    if entry_ready:
        return "confirmed_reversal"

    if entry_weak:
        return "tentative_reversal"

    if len(setup_flags) >= 2:
        return "reversal_watch"

    if timeframe.get("alignment") == "bullish_aligned" and momentum.get("trend") == "up":
        return "trend_following_up"

    return "neutral_chop"


def evaluate_decision_core(
    indicators: Dict,
    *,
    momentum: Optional[Dict] = None,
    timeframe: Optional[Dict] = None,
) -> Dict:
    """
    统一决策内核：
    - 输出入场确认、市场状态(regime)
    - 输出概率与期望收益（bp）
    - 输出建议仓位占比（%）
    """
    safe_indicators = indicators or {}
    momentum_context = momentum or get_price_momentum(30)
    timeframe_context = timeframe or analyze_multi_timeframe()
    preset_entry_context = safe_indicators.get("_entry_context")
    if isinstance(preset_entry_context, dict):
        entry_context = {
            "setup_flags": list(preset_entry_context.get("setup_flags", [])),
            "confirmation_flags": list(preset_entry_context.get("confirmation_flags", [])),
            "risk_flags": list(preset_entry_context.get("risk_flags", [])),
            "entry_ready": bool(preset_entry_context.get("entry_ready", False)),
            "entry_weak": bool(preset_entry_context.get("entry_weak", False)),
            "core_confirmation_flags": list(preset_entry_context.get("core_confirmation_flags", [])),
        }
        if not entry_context["core_confirmation_flags"]:
            entry_context["core_confirmation_flags"] = [
                flag
                for flag in entry_context["confirmation_flags"]
                if flag in TradingThresholds.ENTRY_CORE_CONFIRMATION_FLAGS
            ]
    else:
        entry_context = build_entry_context(safe_indicators, momentum_context, timeframe_context)

    setup_flags = list(entry_context.get("setup_flags", []))
    confirmation_flags = list(entry_context.get("confirmation_flags", []))
    risk_flags = list(entry_context.get("risk_flags", []))
    entry_ready = bool(entry_context.get("entry_ready", False))
    entry_weak = bool(entry_context.get("entry_weak", False))

    if "falling_knife" not in risk_flags and is_falling_knife(
        safe_indicators,
        momentum_context,
        timeframe_context,
    ):
        risk_flags.append("falling_knife")

    regime = _derive_regime(
        entry_ready,
        entry_weak,
        setup_flags,
        risk_flags,
        momentum_context,
        timeframe_context,
    )

    typed = MarketIndicators.from_dict(safe_indicators)
    rsi = typed.rsi
    macd_histogram = typed.macd_histogram
    volatility = typed.volatility or 2.0

    upside_probability = 0.50
    upside_probability += 0.05 * min(len(setup_flags), 3)
    upside_probability += 0.07 * min(len(confirmation_flags), 3)

    if entry_ready:
        upside_probability += 0.08
    elif entry_weak:
        upside_probability += 0.04

    if momentum_context.get("trend") == "up":
        upside_probability += 0.04
    elif momentum_context.get("trend") == "down":
        upside_probability -= 0.04

    alignment = timeframe_context.get("alignment")
    if alignment == "bullish_aligned":
        upside_probability += 0.04
    elif alignment == "bearish_aligned":
        upside_probability -= 0.06

    if rsi is not None:
        if rsi < 25:
            upside_probability += 0.05
        elif rsi > 70:
            upside_probability -= 0.08

    if macd_histogram is not None:
        if macd_histogram > 0:
            upside_probability += 0.05
        elif macd_histogram < -0.5:
            upside_probability -= 0.08

    if "falling_knife" in risk_flags:
        upside_probability -= 0.22

    heuristic_probability = round(_clamp(upside_probability, 0.05, 0.95), 4)
    probability_input = {
        "setup_flags": setup_flags,
        "confirmation_flags": confirmation_flags,
        "entry_ready": entry_ready,
        "risk_flags": risk_flags,
        "rsi": rsi,
        "macd_histogram": macd_histogram,
        "volatility": volatility,
        "momentum": momentum_context,
        "timeframe_analysis": timeframe_context,
    }
    model_probability, probability_source, probability_samples, probability_horizon_days = predict_upside_probability(
        probability_input,
        heuristic_probability,
    )
    upside_probability = round(_clamp(model_probability, 0.05, 0.95), 4)

    upside_bp = 18 + 6 * len(confirmation_flags) + 4 * len(setup_flags) + (8 if entry_ready else 0)
    downside_bp = 16 + volatility * 8 + (10 if "falling_knife" in risk_flags else 0)

    expected_return_bp = round(
        upside_probability * upside_bp - (1 - upside_probability) * downside_bp,
        2,
    )
    downside_risk_bp = round((1 - upside_probability) * downside_bp, 2)

    if "falling_knife" in risk_flags:
        suggested_position_pct = 0.0
    elif entry_ready and expected_return_bp > 0:
        suggested_position_pct = round(_clamp(6 + expected_return_bp * 0.18, 8.0, 35.0), 2)
    elif (entry_weak or len(setup_flags) >= 2) and expected_return_bp > 0:
        suggested_position_pct = round(_clamp(4 + expected_return_bp * 0.10, 5.0, 15.0), 2)
    else:
        suggested_position_pct = 0.0

    return {
        "entry_ready": entry_ready,
        "entry_weak": entry_weak,
        "setup_flags": setup_flags,
        "confirmation_flags": confirmation_flags,
        "risk_flags": risk_flags,
        "regime": regime,
        "upside_probability": upside_probability,
        "heuristic_upside_probability": heuristic_probability,
        "probability_source": probability_source,
        "probability_samples": probability_samples,
        "probability_horizon_days": probability_horizon_days,
        "downside_risk_bp": downside_risk_bp,
        "expected_return_bp": expected_return_bp,
        "suggested_position_pct": float(suggested_position_pct),
        "momentum": momentum_context,
        "timeframe": timeframe_context,
        "entry_context": entry_context,
    }
