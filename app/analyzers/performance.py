from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Dict, Iterable, Optional, Sequence

from app.database import get_db_session
from app.logging_config import get_logger
from app.models import AnalysisSignal, PriceHistory
from app.signal_validation import decode_signal_indicators

logger = get_logger(__name__)

DEFAULT_BACKTEST_HORIZONS = (3, 7, 30)


def parse_horizon_days(raw: str, *, max_horizon: int = 365) -> list[int]:
    horizons: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError:
            continue
        if 1 <= value <= max_horizon:
            horizons.append(value)
    return sorted(set(horizons))


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


def _pearson_correlation(pairs: Iterable[tuple[float, float]]) -> Optional[float]:
    materialized = [(x, y) for x, y in pairs]
    if len(materialized) < 2:
        return None

    xs = [x for x, _ in materialized]
    ys = [y for _, y in materialized]

    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in materialized)
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    denominator = (variance_x * variance_y) ** 0.5

    if denominator == 0:
        return None

    return numerator / denominator


def calculate_signal_backtest(
    *,
    window_days: int = 180,
    horizons: Sequence[int] = DEFAULT_BACKTEST_HORIZONS,
    limit: int = 300,
    high_score_threshold: int = 80,
) -> Dict[str, Any]:
    normalized_horizons = sorted(set(int(day) for day in horizons if int(day) > 0))
    if not normalized_horizons:
        normalized_horizons = list(DEFAULT_BACKTEST_HORIZONS)

    with get_db_session(read_only=True) as session:
        start_window = datetime.now() - timedelta(days=window_days)
        signals = (
            session.query(
                AnalysisSignal.id,
                AnalysisSignal.timestamp,
                AnalysisSignal.price_cny_per_gram,
                AnalysisSignal.indicators,
            )
            .filter(AnalysisSignal.signal_type == "buy")
            .filter(AnalysisSignal.timestamp >= start_window)
            .order_by(AnalysisSignal.timestamp.desc())
            .limit(limit)
            .all()
        )

        if not signals:
            return {
                "window_days": window_days,
                "horizons": normalized_horizons,
                "signal_count": 0,
                "evaluated_signal_count": 0,
                "horizon_stats": [],
                "high_score_segment": {
                    "threshold": high_score_threshold,
                    "horizon_days": 7 if 7 in normalized_horizons else normalized_horizons[0],
                    "sample_count": 0,
                    "win_rate_pct": None,
                    "avg_return_pct": None,
                },
                "generated_at": datetime.now().isoformat(),
            }

        signals = list(reversed(signals))
        first_signal_time = signals[0][1]
        last_signal_time = signals[-1][1]
        max_horizon = max(normalized_horizons)
        price_end = last_signal_time + timedelta(days=max_horizon, hours=12)

        price_rows = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= first_signal_time)
            .filter(PriceHistory.timestamp <= price_end)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

    if not price_rows:
        logger.warning("Backtest skipped: no price rows in computed window")
        return {
            "window_days": window_days,
            "horizons": normalized_horizons,
            "signal_count": len(signals),
            "evaluated_signal_count": 0,
            "horizon_stats": [],
            "high_score_segment": {
                "threshold": high_score_threshold,
                "horizon_days": 7 if 7 in normalized_horizons else normalized_horizons[0],
                "sample_count": 0,
                "win_rate_pct": None,
                "avg_return_pct": None,
            },
            "generated_at": datetime.now().isoformat(),
        }

    price_timestamps = [row[0] for row in price_rows]
    price_values = [float(row[1]) for row in price_rows]

    horizon_samples: dict[int, list[dict[str, float]]] = defaultdict(list)
    evaluated_signal_ids: set[int] = set()

    for signal_id, signal_time, signal_price_raw, indicators_raw in signals:
        signal_price = _safe_float(signal_price_raw)
        if signal_price is None or signal_price <= 0:
            continue

        indicator_payload = decode_signal_indicators(indicators_raw)
        signal_score = _safe_float(indicator_payload.get("evaluation_score"))

        start_idx = bisect_left(price_timestamps, signal_time)
        if start_idx >= len(price_values):
            continue

        for horizon_days in normalized_horizons:
            target_time = signal_time + timedelta(days=horizon_days)
            target_idx = bisect_left(price_timestamps, target_time)
            if target_idx >= len(price_values):
                continue

            future_price = price_values[target_idx]
            if future_price <= 0:
                continue

            interval_prices = price_values[start_idx : target_idx + 1]
            if not interval_prices:
                continue

            signal_return_pct = (future_price - signal_price) / signal_price * 100
            trough_price = min(interval_prices)
            drawdown_pct = (trough_price - signal_price) / signal_price * 100

            horizon_samples[horizon_days].append(
                {
                    "return_pct": signal_return_pct,
                    "drawdown_pct": drawdown_pct,
                    "score": signal_score if signal_score is not None else float("nan"),
                }
            )
            evaluated_signal_ids.add(signal_id)

    horizon_stats: list[dict[str, Any]] = []
    for horizon_days in normalized_horizons:
        samples = horizon_samples.get(horizon_days, [])
        if not samples:
            horizon_stats.append(
                {
                    "horizon_days": horizon_days,
                    "sample_count": 0,
                    "win_rate_pct": None,
                    "avg_return_pct": None,
                    "best_return_pct": None,
                    "worst_return_pct": None,
                    "max_drawdown_pct": None,
                    "score_return_correlation": None,
                }
            )
            continue

        returns = [sample["return_pct"] for sample in samples]
        drawdowns = [sample["drawdown_pct"] for sample in samples]
        wins = sum(1 for value in returns if value > 0)
        valid_pairs = [
            (sample["score"], sample["return_pct"])
            for sample in samples
            if sample["score"] == sample["score"]  # NaN check
        ]
        correlation = _pearson_correlation(valid_pairs)

        horizon_stats.append(
            {
                "horizon_days": horizon_days,
                "sample_count": len(samples),
                "win_rate_pct": _round_optional(wins / len(samples) * 100),
                "avg_return_pct": _round_optional(mean(returns)),
                "best_return_pct": _round_optional(max(returns)),
                "worst_return_pct": _round_optional(min(returns)),
                "max_drawdown_pct": _round_optional(min(drawdowns)),
                "score_return_correlation": _round_optional(correlation, 4),
            }
        )

    primary_horizon = 7 if 7 in normalized_horizons else normalized_horizons[0]
    primary_samples = horizon_samples.get(primary_horizon, [])
    high_score_samples = [
        sample
        for sample in primary_samples
        if sample["score"] == sample["score"] and sample["score"] >= high_score_threshold
    ]

    if high_score_samples:
        high_wins = sum(1 for sample in high_score_samples if sample["return_pct"] > 0)
        high_score_segment = {
            "threshold": high_score_threshold,
            "horizon_days": primary_horizon,
            "sample_count": len(high_score_samples),
            "win_rate_pct": _round_optional(high_wins / len(high_score_samples) * 100),
            "avg_return_pct": _round_optional(
                mean(sample["return_pct"] for sample in high_score_samples)
            ),
        }
    else:
        high_score_segment = {
            "threshold": high_score_threshold,
            "horizon_days": primary_horizon,
            "sample_count": 0,
            "win_rate_pct": None,
            "avg_return_pct": None,
        }

    return {
        "window_days": window_days,
        "horizons": normalized_horizons,
        "signal_count": len(signals),
        "evaluated_signal_count": len(evaluated_signal_ids),
        "horizon_stats": horizon_stats,
        "high_score_segment": high_score_segment,
        "generated_at": datetime.now().isoformat(),
    }


def _cluster_levels(
    candidates: list[tuple[float, datetime]],
    *,
    tolerance_pct: float,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    sorted_candidates = sorted(candidates, key=lambda row: row[0])
    clusters: list[list[tuple[float, datetime]]] = []
    current_cluster: list[tuple[float, datetime]] = [sorted_candidates[0]]

    for price, touched_at in sorted_candidates[1:]:
        center_price = sum(item[0] for item in current_cluster) / len(current_cluster)
        if center_price > 0 and abs(price - center_price) / center_price <= tolerance_pct:
            current_cluster.append((price, touched_at))
        else:
            clusters.append(current_cluster)
            current_cluster = [(price, touched_at)]
    clusters.append(current_cluster)

    levels: list[dict[str, Any]] = []
    for cluster in clusters:
        prices = [item[0] for item in cluster]
        touched_times = [item[1] for item in cluster]
        levels.append(
            {
                "price": round(sum(prices) / len(prices), 2),
                "strength": len(cluster),
                "last_touched": max(touched_times).isoformat(),
            }
        )

    return levels


def _round_step(price: float) -> int:
    if price < 300:
        return 5
    if price < 800:
        return 10
    if price < 1200:
        return 20
    return 50


def calculate_support_resistance(
    *,
    window_days: int = 180,
    pivot_window: int = 5,
    max_levels: int = 4,
    cluster_tolerance_pct: float = 0.004,
) -> Dict[str, Any]:
    with get_db_session(read_only=True) as session:
        start_window = datetime.now() - timedelta(days=window_days)
        price_rows = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= start_window)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

    if not price_rows:
        return {
            "window_days": window_days,
            "current_price": None,
            "supports": [],
            "resistances": [],
            "nearest_support": None,
            "nearest_resistance": None,
            "round_levels": [],
            "round_level_step": None,
            "plot_lines": [],
            "generated_at": datetime.now().isoformat(),
        }

    prices = [float(row[1]) for row in price_rows]
    timestamps = [row[0] for row in price_rows]
    current_price = prices[-1]

    support_candidates: list[tuple[float, datetime]] = []
    resistance_candidates: list[tuple[float, datetime]] = []

    start_idx = max(1, pivot_window)
    end_idx = len(prices) - pivot_window
    for idx in range(start_idx, end_idx):
        center_price = prices[idx]
        neighborhood = prices[idx - pivot_window : idx + pivot_window + 1]

        is_swing_low = all(center_price <= value for value in neighborhood) and any(
            center_price < value for value in neighborhood
        )
        is_swing_high = all(center_price >= value for value in neighborhood) and any(
            center_price > value for value in neighborhood
        )

        if is_swing_low:
            support_candidates.append((center_price, timestamps[idx]))
        if is_swing_high:
            resistance_candidates.append((center_price, timestamps[idx]))

    supports = _cluster_levels(support_candidates, tolerance_pct=cluster_tolerance_pct)
    resistances = _cluster_levels(resistance_candidates, tolerance_pct=cluster_tolerance_pct)

    supports_below = [level for level in supports if level["price"] <= current_price]
    resistances_above = [level for level in resistances if level["price"] >= current_price]

    supports_below.sort(key=lambda level: (abs(current_price - level["price"]), -level["strength"]))
    resistances_above.sort(key=lambda level: (abs(level["price"] - current_price), -level["strength"]))

    selected_supports = supports_below[:max_levels]
    selected_resistances = resistances_above[:max_levels]

    nearest_support = selected_supports[0] if selected_supports else None
    nearest_resistance = selected_resistances[0] if selected_resistances else None

    if nearest_support:
        nearest_support = dict(nearest_support)
        nearest_support["distance_pct"] = _round_optional(
            (current_price - nearest_support["price"]) / current_price * 100
        )
    if nearest_resistance:
        nearest_resistance = dict(nearest_resistance)
        nearest_resistance["distance_pct"] = _round_optional(
            (nearest_resistance["price"] - current_price) / current_price * 100
        )

    level_step = _round_step(current_price)
    anchor = round(current_price / level_step) * level_step
    round_levels = [round(anchor + offset * level_step, 2) for offset in range(-3, 4) if anchor + offset * level_step > 0]

    plot_lines: list[dict[str, Any]] = []
    for idx, level in enumerate(selected_supports[:2], start=1):
        plot_lines.append(
            {"label": f"S{idx}", "price": level["price"], "kind": "support"}
        )
    for idx, level in enumerate(selected_resistances[:2], start=1):
        plot_lines.append(
            {"label": f"R{idx}", "price": level["price"], "kind": "resistance"}
        )

    nearest_round = min(round_levels, key=lambda value: abs(value - current_price)) if round_levels else None
    if nearest_round is not None:
        plot_lines.append({"label": "Round", "price": nearest_round, "kind": "round"})

    return {
        "window_days": window_days,
        "current_price": round(current_price, 2),
        "supports": selected_supports,
        "resistances": selected_resistances,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "round_levels": round_levels,
        "round_level_step": level_step,
        "plot_lines": plot_lines,
        "generated_at": datetime.now().isoformat(),
    }
