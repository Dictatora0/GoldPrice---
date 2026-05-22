from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Optional

import numpy as np

from app.analyzers.performance import calculate_support_resistance
from app.database import get_db_session
from app.models import PriceHistory


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_optional(value: Optional[float], digits: int = 3) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _std(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    arr = np.array(values, dtype=float)
    return float(arr.std(ddof=1))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _load_prices(*, lookback_days: int, limit: int = 5000) -> list[tuple[datetime, float]]:
    start_time = datetime.now() - timedelta(days=lookback_days)
    with get_db_session(read_only=True) as session:
        rows = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= start_time)
            .order_by(PriceHistory.timestamp.asc())
            .limit(limit)
            .all()
        )
    return [(ts, float(price)) for ts, price in rows if _safe_float(price) and float(price) > 0]


def calculate_multi_timeframe(
    *,
    windows: list[int] | tuple[int, ...] = (1, 7, 30),
    lookback_days: int = 180,
) -> dict[str, Any]:
    prices = _load_prices(lookback_days=lookback_days)
    if len(prices) < 2:
        return {
            "lookback_days": lookback_days,
            "windows": list(windows),
            "alignment": "insufficient_data",
            "alignment_score": None,
            "frames": [],
            "summary": "历史样本不足，暂时无法判断多周期共振。",
            "generated_at": datetime.now().isoformat(),
        }

    now = prices[-1][0]
    last_price = prices[-1][1]
    frames: list[dict[str, Any]] = []

    for window in sorted(set(int(w) for w in windows if int(w) >= 1)):
        cutoff = now - timedelta(days=window)
        frame_prices = [price for ts, price in prices if ts >= cutoff]
        if len(frame_prices) < 2:
            frames.append(
                {
                    "window_days": window,
                    "sample_count": len(frame_prices),
                    "return_pct": None,
                    "trend": "unknown",
                    "volatility_pct": None,
                    "distance_from_latest_pct": None,
                }
            )
            continue

        first = frame_prices[0]
        change_pct = (frame_prices[-1] - first) / first * 100 if first > 0 else None
        returns = []
        for i in range(1, len(frame_prices)):
            prev = frame_prices[i - 1]
            curr = frame_prices[i]
            if prev > 0:
                returns.append((curr - prev) / prev * 100)
        vol_pct = _std(returns)

        threshold = 0.25 * math.sqrt(window)
        trend = "neutral"
        if change_pct is not None:
            if change_pct > threshold:
                trend = "bullish"
            elif change_pct < -threshold:
                trend = "bearish"

        mean_price = mean(frame_prices)
        distance_from_latest_pct = (
            (last_price - mean_price) / mean_price * 100 if mean_price > 0 else None
        )

        frames.append(
            {
                "window_days": window,
                "sample_count": len(frame_prices),
                "return_pct": _round_optional(change_pct),
                "trend": trend,
                "volatility_pct": _round_optional(vol_pct),
                "distance_from_latest_pct": _round_optional(distance_from_latest_pct),
            }
        )

    bullish_count = sum(1 for item in frames if item["trend"] == "bullish")
    bearish_count = sum(1 for item in frames if item["trend"] == "bearish")
    known_count = sum(1 for item in frames if item["trend"] in {"bullish", "bearish", "neutral"})
    alignment_score = None if known_count == 0 else (bullish_count - bearish_count) / known_count

    if bullish_count >= 2:
        alignment = "bullish_aligned"
        summary = "多周期偏多共振，可优先在回撤中寻找低风险入场。"
    elif bearish_count >= 2:
        alignment = "bearish_aligned"
        summary = "多周期偏空共振，宜控制仓位并等待趋势止跌确认。"
    else:
        alignment = "mixed"
        summary = "多周期分歧，适合先观察关键位突破再执行。"

    return {
        "lookback_days": lookback_days,
        "windows": [item["window_days"] for item in frames],
        "alignment": alignment,
        "alignment_score": _round_optional(alignment_score, 4),
        "frames": frames,
        "summary": summary,
        "generated_at": datetime.now().isoformat(),
    }


def calculate_price_forecast(
    *,
    lookback_days: int = 180,
    horizon_days: int = 7,
    confidence_z: float = 1.645,
    simulation_paths: int = 400,
) -> dict[str, Any]:
    prices = _load_prices(lookback_days=lookback_days)
    if len(prices) < 3:
        return {
            "lookback_days": lookback_days,
            "horizon_days": horizon_days,
            "sample_count": len(prices),
            "current_price": None,
            "expected_price": None,
            "expected_change_pct": None,
            "forecast_range": {"lower": None, "upper": None, "confidence_level": "90%"},
            "probability_up_pct": None,
            "scenario": {
                "days_to_gain_5pct": None,
                "days_to_drop_5pct": None,
                "p10": None,
                "p50": None,
                "p90": None,
            },
            "generated_at": datetime.now().isoformat(),
        }

    close_prices = [row[1] for row in prices]
    current = close_prices[-1]

    log_returns: list[float] = []
    for i in range(1, len(close_prices)):
        prev = close_prices[i - 1]
        curr = close_prices[i]
        if prev > 0 and curr > 0:
            log_returns.append(math.log(curr / prev))

    if len(log_returns) < 2:
        return {
            "lookback_days": lookback_days,
            "horizon_days": horizon_days,
            "sample_count": len(close_prices),
            "current_price": round(current, 3),
            "expected_price": round(current, 3),
            "expected_change_pct": 0.0,
            "forecast_range": {"lower": round(current, 3), "upper": round(current, 3), "confidence_level": "90%"},
            "probability_up_pct": 50.0,
            "scenario": {
                "days_to_gain_5pct": None,
                "days_to_drop_5pct": None,
                "p10": round(current, 3),
                "p50": round(current, 3),
                "p90": round(current, 3),
            },
            "generated_at": datetime.now().isoformat(),
        }

    mu = float(np.mean(log_returns))
    sigma = float(np.std(log_returns, ddof=1))
    horizon = max(1, int(horizon_days))

    expected_log = mu * horizon
    expected_price = current * math.exp(expected_log)
    expected_change_pct = (expected_price - current) / current * 100

    spread = confidence_z * sigma * math.sqrt(horizon)
    lower = current * math.exp(expected_log - spread)
    upper = current * math.exp(expected_log + spread)

    if sigma > 0:
        z = (0.0 - expected_log) / (sigma * math.sqrt(horizon))
        probability_up_pct = (1.0 - _normal_cdf(z)) * 100
    else:
        probability_up_pct = 100.0 if expected_log > 0 else 0.0 if expected_log < 0 else 50.0

    days_to_gain_5pct = None
    if mu > 0:
        days_to_gain_5pct = math.log(1.05) / mu

    days_to_drop_5pct = None
    if mu < 0:
        days_to_drop_5pct = math.log(0.95) / mu

    rng = np.random.default_rng(42)
    scenario_p10 = scenario_p50 = scenario_p90 = None
    if simulation_paths > 0 and sigma >= 0:
        simulated_logs = rng.normal(
            loc=expected_log,
            scale=sigma * math.sqrt(horizon),
            size=min(3000, max(100, int(simulation_paths))),
        )
        simulated_prices = current * np.exp(simulated_logs)
        scenario_p10 = float(np.percentile(simulated_prices, 10))
        scenario_p50 = float(np.percentile(simulated_prices, 50))
        scenario_p90 = float(np.percentile(simulated_prices, 90))

    return {
        "lookback_days": lookback_days,
        "horizon_days": horizon,
        "sample_count": len(close_prices),
        "current_price": _round_optional(current),
        "expected_price": _round_optional(expected_price),
        "expected_change_pct": _round_optional(expected_change_pct),
        "forecast_range": {
            "lower": _round_optional(lower),
            "upper": _round_optional(upper),
            "confidence_level": "90%",
        },
        "probability_up_pct": _round_optional(probability_up_pct, 2),
        "scenario": {
            "days_to_gain_5pct": _round_optional(days_to_gain_5pct, 1),
            "days_to_drop_5pct": _round_optional(days_to_drop_5pct, 1),
            "p10": _round_optional(scenario_p10),
            "p50": _round_optional(scenario_p50),
            "p90": _round_optional(scenario_p90),
        },
        "generated_at": datetime.now().isoformat(),
    }


def calculate_entry_plan(
    *,
    budget_cny: Optional[float] = None,
    batches: int = 3,
    step_pct: float = 2.0,
    target_profit_pct: float = 5.0,
) -> dict[str, Any]:
    with get_db_session(read_only=True) as session:
        latest = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )

    if not latest:
        return {
            "current_price": None,
            "batches": batches,
            "step_pct": step_pct,
            "target_profit_pct": target_profit_pct,
            "plan": [],
            "summary": {
                "avg_entry_price": None,
                "stop_loss_price": None,
                "target_price": None,
                "risk_pct": None,
                "reward_pct": None,
                "risk_reward_ratio": None,
            },
            "generated_at": datetime.now().isoformat(),
        }

    current_price = float(latest[1])
    batches = max(1, min(10, int(batches)))
    step_pct = max(0.2, min(20.0, float(step_pct)))
    target_profit_pct = max(0.5, min(40.0, float(target_profit_pct)))

    level_data = calculate_support_resistance(window_days=180, pivot_window=5, max_levels=3)
    nearest_support = (level_data or {}).get("nearest_support")
    nearest_resistance = (level_data or {}).get("nearest_resistance")

    batch_plan: list[dict[str, Any]] = []
    per_batch_budget = None
    if budget_cny is not None and budget_cny > 0:
        per_batch_budget = float(budget_cny) / batches

    for idx in range(batches):
        price = current_price * ((1 - step_pct / 100) ** idx)
        row = {
            "batch": idx + 1,
            "buy_price": round(price, 3),
        }
        if per_batch_budget is not None:
            qty_gram = per_batch_budget / price if price > 0 else None
            row["budget_cny"] = _round_optional(per_batch_budget, 2)
            row["quantity_gram"] = _round_optional(qty_gram, 3)
        batch_plan.append(row)

    avg_entry_price = mean(item["buy_price"] for item in batch_plan) if batch_plan else current_price

    if nearest_support and nearest_support.get("price"):
        stop_loss_price = float(nearest_support["price"]) * 0.995
    else:
        stop_loss_price = current_price * (1 - max(2.5, step_pct * 1.2) / 100)

    if nearest_resistance and nearest_resistance.get("price"):
        resistance_price = float(nearest_resistance["price"])
        target_price = resistance_price if resistance_price > avg_entry_price else avg_entry_price * (1 + target_profit_pct / 100)
    else:
        target_price = avg_entry_price * (1 + target_profit_pct / 100)

    risk_pct = (avg_entry_price - stop_loss_price) / avg_entry_price * 100 if avg_entry_price > 0 else None
    reward_pct = (target_price - avg_entry_price) / avg_entry_price * 100 if avg_entry_price > 0 else None
    risk_reward_ratio = None
    if risk_pct and risk_pct > 0 and reward_pct is not None:
        risk_reward_ratio = reward_pct / risk_pct

    return {
        "current_price": _round_optional(current_price),
        "batches": batches,
        "step_pct": _round_optional(step_pct, 2),
        "target_profit_pct": _round_optional(target_profit_pct, 2),
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "plan": batch_plan,
        "summary": {
            "avg_entry_price": _round_optional(avg_entry_price),
            "stop_loss_price": _round_optional(stop_loss_price),
            "target_price": _round_optional(target_price),
            "risk_pct": _round_optional(risk_pct, 2),
            "reward_pct": _round_optional(reward_pct, 2),
            "risk_reward_ratio": _round_optional(risk_reward_ratio, 2),
        },
        "generated_at": datetime.now().isoformat(),
    }
