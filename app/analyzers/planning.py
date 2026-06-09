from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Optional

import numpy as np

from app.analyzers.advisor import MarketAdvisor
from app.analyzers.performance import calculate_support_resistance
from app.database import get_db_session
from app.models import PriceHistory
from app.price_series import load_price_series


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


def _forecast_confidence(sample_count: int, *, basis_interval: str) -> dict[str, Any]:
    if sample_count < 30:
        level = "insufficient"
        reason = "日线样本少于30条，预测只适合作为方向观察。"
    elif sample_count < 90:
        level = "low"
        reason = "日线样本不足90条，概率和区间可信度偏低。"
    elif sample_count < 180:
        level = "medium"
        reason = "日线样本达到中等规模，可用于短期情景参考。"
    else:
        level = "high"
        reason = "日线样本较充足，预测区间相对稳定。"
    return {
        "level": level,
        "sample_count": sample_count,
        "basis_interval": basis_interval,
        "reason": reason,
    }


def _build_execution_gate() -> dict[str, Any]:
    try:
        advice = MarketAdvisor().analyze_cached()
    except Exception as exc:
        return {
            "status": "unavailable",
            "message": f"当前建议不可用，入场计划仅作为价格计算参考。原因：{exc}",
            "recommendation": None,
            "entry_ready": False,
            "risk_flags": [],
        }

    if not advice:
        return {
            "status": "unavailable",
            "message": "当前建议不可用，入场计划仅作为价格计算参考。",
            "recommendation": None,
            "entry_ready": False,
            "risk_flags": [],
        }

    recommendation = advice.get("recommendation")
    risk_flags = list(advice.get("risk_flags", []))
    entry_ready = bool(advice.get("entry_ready"))
    if "falling_knife" in risk_flags or recommendation in {"不推荐", "强烈不推荐"}:
        status = "blocked"
        message = "当前建议不满足入场条件，分批计划仅用于预案，不建议立即执行。"
    elif recommendation in {"强烈推荐买入", "推荐买入"} and entry_ready:
        status = "ready"
        message = "当前建议与入场确认匹配，可按计划小仓分批执行。"
    else:
        status = "watch"
        message = "当前仍偏观察，建议先设置预警，等待确认信号后再执行分批计划。"

    return {
        "status": status,
        "message": message,
        "recommendation": recommendation,
        "entry_ready": entry_ready,
        "risk_flags": risk_flags,
    }


def _build_conditional_triggers(
    *,
    current_price: Optional[float],
    execution_gate: dict[str, Any],
    nearest_support: Optional[dict[str, Any]],
    nearest_resistance: Optional[dict[str, Any]],
) -> dict[str, Any]:
    gate_status = execution_gate.get("status")
    conditions: list[dict[str, Any]] = []
    if current_price is None:
        return {
            "mode": "conditional",
            "status": "unavailable",
            "next_action": "暂无价格数据，先等待采集恢复。",
            "conditions": [],
        }

    support_price = _safe_float((nearest_support or {}).get("price"))
    resistance_price = _safe_float((nearest_resistance or {}).get("price"))
    if support_price and support_price < current_price:
        support_distance_pct = (current_price - support_price) / current_price * 100
        conditions.append(
            {
                "type": "pullback_to_support",
                "label": "回踩支撑",
                "target_price": _round_optional(support_price),
                "distance_pct": _round_optional(support_distance_pct, 2),
                "status": "met" if support_distance_pct <= 0.8 else "waiting",
                "description": f"价格回踩到 {support_price:.2f} 附近且不跌破支撑。",
            }
        )
    else:
        conditions.append(
            {
                "type": "pullback_to_support",
                "label": "等待支撑位",
                "target_price": None,
                "distance_pct": None,
                "status": "waiting",
                "description": "当前窗口尚未识别出可用支撑位，先等待关键位形成。",
            }
        )

    conditions.append(
        {
            "type": "entry_confirmation",
            "label": "入场确认",
            "target_price": None,
            "distance_pct": None,
            "status": "met" if execution_gate.get("entry_ready") else "waiting",
            "description": "买入建议、动量和风险检查需要同时满足。",
        }
    )

    if resistance_price and resistance_price > current_price:
        conditions.append(
            {
                "type": "risk_reward",
                "label": "盈亏比检查",
                "target_price": _round_optional(resistance_price),
                "distance_pct": _round_optional((resistance_price - current_price) / current_price * 100, 2),
                "status": "met",
                "description": "上方阻力仍留有空间，计划需要维持正向盈亏比。",
            }
        )

    if gate_status == "blocked":
        status = "blocked"
        next_action = "当前不满足入场条件，只保留预案；先等待风险解除。"
    elif gate_status == "ready" and all(item["status"] == "met" for item in conditions):
        status = "armed"
        next_action = "条件已满足，可按第一批小仓执行，并严格使用止损。"
    else:
        status = "waiting"
        next_action = "条件未全部满足，建议设置预警而不是立即买入。"

    return {
        "mode": "conditional",
        "status": status,
        "next_action": next_action,
        "conditions": conditions,
    }


def _load_prices(
    *,
    lookback_days: int,
    limit: int = 5000,
    interval: str = "raw",
) -> list[tuple[datetime, float]]:
    series = load_price_series(
        lookback_days=lookback_days,
        interval=interval,
        limit=limit,
        apply_regime_filter=True,
    )
    return [(point.timestamp, point.price) for point in series.points]


def calculate_multi_timeframe(
    *,
    windows: list[int] | tuple[int, ...] = (1, 7, 30),
    lookback_days: int = 180,
) -> dict[str, Any]:
    prices = _load_prices(lookback_days=lookback_days, interval="raw")
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
    basis_interval = "1d"
    prices = _load_prices(lookback_days=lookback_days, interval=basis_interval)
    if len(prices) < 3:
        return {
            "lookback_days": lookback_days,
            "horizon_days": horizon_days,
            "basis_interval": basis_interval,
            "sample_count": len(prices),
            "confidence": _forecast_confidence(len(prices), basis_interval=basis_interval),
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
            "basis_interval": basis_interval,
            "sample_count": len(close_prices),
            "confidence": _forecast_confidence(len(close_prices), basis_interval=basis_interval),
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
        "basis_interval": basis_interval,
        "sample_count": len(close_prices),
        "confidence": _forecast_confidence(len(close_prices), basis_interval=basis_interval),
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
            "execution_gate": {
                "status": "unavailable",
                "message": "暂无价格数据，无法判断入场条件。",
                "recommendation": None,
                "entry_ready": False,
                "risk_flags": [],
            },
            "conditional_triggers": {
                "mode": "conditional",
                "status": "unavailable",
                "next_action": "暂无价格数据，先等待采集恢复。",
                "conditions": [],
            },
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
    execution_gate = _build_execution_gate()
    batches = max(1, min(10, int(batches)))
    step_pct = max(0.2, min(20.0, float(step_pct)))
    target_profit_pct = max(0.5, min(40.0, float(target_profit_pct)))

    level_data = calculate_support_resistance(window_days=180, pivot_window=5, max_levels=3)
    nearest_support = (level_data or {}).get("nearest_support")
    nearest_resistance = (level_data or {}).get("nearest_resistance")
    conditional_triggers = _build_conditional_triggers(
        current_price=current_price,
        execution_gate=execution_gate,
        nearest_support=nearest_support,
        nearest_resistance=nearest_resistance,
    )

    batch_plan: list[dict[str, Any]] = []
    per_batch_budget = None
    if budget_cny is not None and budget_cny > 0:
        per_batch_budget = float(budget_cny) / batches

    for idx in range(batches):
        price = current_price * ((1 - step_pct / 100) ** idx)
        row_status = "ready" if conditional_triggers["status"] == "armed" and idx == 0 else "waiting"
        if conditional_triggers["status"] == "blocked":
            row_status = "blocked"
        row = {
            "batch": idx + 1,
            "buy_price": round(price, 3),
            "status": row_status,
            "trigger_condition": (
                "条件满足后执行首批小仓。"
                if idx == 0
                else f"首批成交后，价格再回落 {step_pct:.1f}% 附近再执行第 {idx + 1} 批。"
            ),
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
        "execution_gate": execution_gate,
        "conditional_triggers": conditional_triggers,
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
