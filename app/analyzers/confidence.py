from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Optional, Sequence

from app.analyzers.advisor import MarketAdvisor
from app.analyzers.performance import (
    DEFAULT_BACKTEST_HORIZONS,
    calculate_forward_returns_from_series,
    calculate_signal_backtest,
    parse_horizon_days,
)
from app.database import get_db_session
from app.models import AnalysisSignal, PriceHistory
from app.signal_validation import decode_signal_indicators, is_complete_signal_payload


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_primary_horizon(performance_snapshot: dict, preferred: int = 7) -> Optional[dict]:
    stats = performance_snapshot.get("horizon_stats", [])
    if not stats:
        return None
    for item in stats:
        if int(item.get("horizon_days", 0)) == preferred:
            return item
    return stats[0]


def _degradation_status(primary_horizon: Optional[dict]) -> str:
    if not primary_horizon:
        return "insufficient_data"

    sample_count = int(primary_horizon.get("sample_count") or 0)
    win_rate = _safe_float(primary_horizon.get("win_rate_pct"))
    avg_return = _safe_float(primary_horizon.get("avg_return_pct"))

    if sample_count < 5 or win_rate is None or avg_return is None:
        return "insufficient_data"
    if win_rate >= 60 and avg_return >= 0.8:
        return "healthy"
    if win_rate >= 45 and avg_return >= 0:
        return "watch"
    return "degraded"


def _degradation_reason(primary_horizon: Optional[dict]) -> str:
    if not primary_horizon:
        return "缺少主观察窗口，暂时无法判断策略稳定性。"

    sample_count = int(primary_horizon.get("sample_count") or 0)
    horizon_days = int(primary_horizon.get("horizon_days") or 0)
    win_rate = _safe_float(primary_horizon.get("win_rate_pct"))
    avg_return = _safe_float(primary_horizon.get("avg_return_pct"))
    max_drawdown = _safe_float(primary_horizon.get("max_drawdown_pct"))

    if sample_count < 5 or win_rate is None or avg_return is None:
        return f"{horizon_days}天窗口有效样本仅 {sample_count} 条，统计显著性不足。"
    if win_rate >= 60 and avg_return >= 0.8:
        return f"{horizon_days}天窗口胜率 {win_rate:.1f}%，平均收益 {avg_return:.2f}%，策略暂时健康。"
    if win_rate >= 45 and avg_return >= 0:
        return (
            f"{horizon_days}天窗口胜率 {win_rate:.1f}%，平均收益 {avg_return:.2f}%，"
            "边际优势仍在，但已进入观察区间。"
        )
    drawdown_part = f"，最大回撤 {max_drawdown:.2f}%" if max_drawdown is not None else ""
    return (
        f"{horizon_days}天窗口胜率 {win_rate:.1f}%，平均收益 {avg_return:.2f}%{drawdown_part}，"
        "近期策略优势显著走弱。"
    )


def _build_risk_checks(advice: Optional[dict], performance_snapshot: dict) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    primary_horizon = _resolve_primary_horizon(performance_snapshot)
    status = _degradation_status(primary_horizon)

    checks.append(
        {
            "name": "策略近期表现",
            "status": "pass" if status == "healthy" else "warn" if status == "watch" else "fail",
            "detail": (
                "近期回测表现稳定"
                if status == "healthy"
                else "近期表现一般，建议降低信号权重"
                if status == "watch"
                else "近期表现偏弱，当前建议应谨慎使用"
                if status == "degraded"
                else "有效样本不足，暂无法判断策略是否退化"
            ),
        }
    )

    if advice:
        risk_flags = list(advice.get("risk_flags", []))
        checks.append(
            {
                "name": "当前风险标签",
                "status": "pass" if not risk_flags else "warn",
                "detail": "风险可控" if not risk_flags else " / ".join(risk_flags),
            }
        )
        checks.append(
            {
                "name": "入场确认状态",
                "status": "pass" if advice.get("entry_ready") else "warn",
                "detail": (
                    "已满足入场确认"
                    if advice.get("entry_ready")
                    else "入场确认不足，建议结合等待型预警使用"
                ),
            }
        )
    else:
        checks.append({"name": "当前风险标签", "status": "warn", "detail": "当前建议暂不可用"})
        checks.append({"name": "入场确认状态", "status": "warn", "detail": "当前建议暂不可用"})

    return checks


def _round_optional(value: Optional[float], digits: int = 3) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _regime_label(alignment: Optional[str], risk_flags: set[str]) -> str:
    if "falling_knife" in risk_flags:
        return "飞刀风险"
    if alignment == "bullish_aligned":
        return "多头共振"
    if alignment == "bearish_aligned":
        return "空头承压"
    if alignment == "mixed":
        return "震荡混合"
    return "未知状态"


def _extract_current_regime_context(
    current_advice: Optional[dict],
    fallback_indicators: Optional[dict],
) -> dict[str, Any]:
    if current_advice:
        alignment = (
            current_advice.get("timeframe", {}).get("alignment")
            or current_advice.get("regime")
        )
        risk_flags = set(current_advice.get("risk_flags", []))
        current_context = {
            "alignment": alignment,
            "risk_flags": risk_flags,
            "label": _regime_label(alignment, risk_flags),
            "source": "advice",
        }
        if current_context["label"] != "未知状态":
            return current_context

    if fallback_indicators:
        alignment = fallback_indicators.get("timeframe_analysis", {}).get("alignment")
        risk_flags = set(fallback_indicators.get("risk_flags", []))
        return {
            "alignment": alignment,
            "risk_flags": risk_flags,
            "label": _regime_label(alignment, risk_flags),
            "source": "signal_fallback",
        }

    return {
        "alignment": None,
        "risk_flags": set(),
        "label": None,
        "source": "unavailable",
    }


def _build_regime_breakdown(
    *,
    window_days: int,
    primary_horizon: int,
    limit: int,
    current_regime_label: Optional[str],
) -> list[dict[str, Any]]:
    window_start = datetime.now() - timedelta(days=window_days)
    with get_db_session(read_only=True) as session:
        rows = (
            session.query(
                AnalysisSignal.timestamp,
                AnalysisSignal.price_cny_per_gram,
                AnalysisSignal.indicators,
            )
            .filter(AnalysisSignal.signal_type == "buy")
            .filter(AnalysisSignal.timestamp >= window_start)
            .order_by(AnalysisSignal.timestamp.desc())
            .limit(limit)
            .all()
        )
        if not rows:
            return []

        earliest_signal_time = min(row[0] for row in rows)
        latest_signal_time = max(row[0] for row in rows)
        price_rows = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= earliest_signal_time)
            .filter(PriceHistory.timestamp <= latest_signal_time + timedelta(days=primary_horizon, hours=12))
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

    if not price_rows:
        return []

    price_timestamps = [row[0] for row in price_rows]
    price_values = [float(row[1]) for row in price_rows]
    grouped: dict[str, list[float]] = {}

    for timestamp, price_cny_per_gram, indicators_raw in rows:
        indicators = decode_signal_indicators(indicators_raw)
        if not is_complete_signal_payload(price_cny_per_gram, indicators):
            continue

        forward_returns = calculate_forward_returns_from_series(
            signal_time=timestamp,
            signal_price=float(price_cny_per_gram),
            horizons=[primary_horizon],
            price_timestamps=price_timestamps,
            price_values=price_values,
        )
        realized = forward_returns.get(primary_horizon)
        if not realized:
            continue

        alignment = indicators.get("timeframe_analysis", {}).get("alignment")
        risk_flags = set(indicators.get("risk_flags", []))
        label = _regime_label(alignment, risk_flags)
        grouped.setdefault(label, []).append(realized["return_pct"])

    breakdown: list[dict[str, Any]] = []
    for label, returns in grouped.items():
        if not returns:
            continue
        wins = sum(1 for value in returns if value > 0)
        breakdown.append(
            {
                "label": label,
                "sample_count": len(returns),
                "win_rate_pct": _round_optional(wins / len(returns) * 100),
                "avg_return_pct": _round_optional(mean(returns)),
                "is_current": label == current_regime_label,
            }
        )

    breakdown.sort(key=lambda item: item["sample_count"], reverse=True)
    return breakdown


def _find_similar_signals(
    *,
    lookback_days: int,
    horizons: Sequence[int],
    limit: int = 5,
) -> dict[str, Any]:
    window_start = datetime.now() - timedelta(days=lookback_days)
    advisor = MarketAdvisor()
    current_advice = advisor.analyze_cached()

    normalized_horizons = sorted(set(int(day) for day in horizons if int(day) > 0)) or list(
        DEFAULT_BACKTEST_HORIZONS
    )
    primary_horizon = 7 if 7 in normalized_horizons else normalized_horizons[0]

    with get_db_session(read_only=True) as session:
        rows = (
            session.query(
                AnalysisSignal.timestamp,
                AnalysisSignal.price_cny_per_gram,
                AnalysisSignal.indicators,
            )
            .filter(AnalysisSignal.signal_type == "buy")
            .filter(AnalysisSignal.timestamp >= window_start)
            .order_by(AnalysisSignal.timestamp.desc())
            .limit(200)
            .all()
        )
        if rows:
            earliest_signal_time = min(row[0] for row in rows)
            latest_signal_time = max(row[0] for row in rows)
            price_rows = (
                session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
                .filter(PriceHistory.timestamp >= earliest_signal_time)
                .filter(PriceHistory.timestamp <= latest_signal_time + timedelta(days=max(normalized_horizons), hours=12))
                .order_by(PriceHistory.timestamp.asc())
                .all()
            )
        else:
            price_rows = []

    price_timestamps = [row[0] for row in price_rows]
    price_values = [float(row[1]) for row in price_rows]

    fallback_indicators = None
    for _, price_cny_per_gram, indicators_raw in rows:
        indicators = decode_signal_indicators(indicators_raw)
        if is_complete_signal_payload(price_cny_per_gram, indicators):
            fallback_indicators = indicators
            break

    current_regime = _extract_current_regime_context(current_advice, fallback_indicators)

    contexts: list[dict[str, Any]] = []
    if current_advice:
        contexts.append(
            {
                "regime": current_advice.get("regime") or current_advice.get("timeframe", {}).get("alignment"),
                "risk_flags": set(current_advice.get("risk_flags", [])),
                "score": _safe_float(current_advice.get("score")),
            }
        )
    if fallback_indicators is not None:
        fallback_context = {
            "regime": fallback_indicators.get("timeframe_analysis", {}).get("alignment"),
            "risk_flags": set(fallback_indicators.get("risk_flags", [])),
            "score": _safe_float(fallback_indicators.get("evaluation_score")),
        }
        if fallback_context not in contexts:
            contexts.append(fallback_context)

    if not contexts:
        return {"match_count": 0, "matches": [], "summary": "当前建议和历史信号样本均不足"}

    matches: list[dict[str, Any]] = []
    for timestamp, price_cny_per_gram, indicators_raw in rows:
        indicators = decode_signal_indicators(indicators_raw)
        if not is_complete_signal_payload(price_cny_per_gram, indicators):
            continue

        signal_regime = indicators.get("timeframe_analysis", {}).get("alignment")
        signal_score = _safe_float(indicators.get("evaluation_score"))
        signal_risk_flags = set(indicators.get("risk_flags", []))
        reasons = list(indicators.get("evaluation_reasons", []))

        matched_context = None
        for context in contexts:
            regime_match = signal_regime == context["regime"]
            score_close = (
                context["score"] is not None
                and signal_score is not None
                and abs(signal_score - context["score"]) <= 12
            )
            risk_overlap = bool(context["risk_flags"].intersection(signal_risk_flags)) or (
                not context["risk_flags"] and not signal_risk_flags
            )
            if regime_match or score_close or risk_overlap:
                matched_context = {
                    "regime_match": regime_match,
                    "score_close": score_close,
                    "risk_overlap": risk_overlap,
                }
                break

        if not matched_context:
            continue

        match_flags = []
        if matched_context["regime_match"]:
            match_flags.append("regime")
        if matched_context["score_close"]:
            match_flags.append("score")
        if matched_context["risk_overlap"]:
            match_flags.append("risk")

        forward_returns = calculate_forward_returns_from_series(
            signal_time=timestamp,
            signal_price=float(price_cny_per_gram),
            horizons=normalized_horizons,
            price_timestamps=price_timestamps,
            price_values=price_values,
        )
        forward_return_payload = {
            f"{day}d": round(values["return_pct"], 3)
            for day, values in forward_returns.items()
        }

        matches.append(
            {
                "timestamp": timestamp.isoformat(),
                "price_cny_per_gram": round(float(price_cny_per_gram), 2),
                "score": signal_score,
                "alignment": signal_regime,
                "reasons": reasons[:2],
                "match_flags": match_flags,
                "forward_returns": forward_return_payload,
                "primary_horizon_return_pct": forward_return_payload.get(f"{primary_horizon}d"),
            }
        )
        if len(matches) >= limit:
            break

    summary = (
        f"找到 {len(matches)} 条近似历史信号，已附带后续收益对照。"
        if matches
        else "未找到足够接近的历史信号。"
    )
    return {"match_count": len(matches), "matches": matches, "summary": summary}


def calculate_confidence_center(
    *,
    window_days: int = 180,
    horizons: Sequence[int] = DEFAULT_BACKTEST_HORIZONS,
    limit: int = 300,
    high_score_threshold: int = 80,
) -> dict[str, Any]:
    normalized_horizons = sorted(set(int(day) for day in horizons if int(day) > 0))
    if not normalized_horizons:
        normalized_horizons = list(DEFAULT_BACKTEST_HORIZONS)

    performance_snapshot = calculate_signal_backtest(
        window_days=window_days,
        horizons=normalized_horizons,
        limit=limit,
        high_score_threshold=high_score_threshold,
    )
    primary_horizon = _resolve_primary_horizon(performance_snapshot)
    degradation_status = _degradation_status(primary_horizon)
    degradation_reason = _degradation_reason(primary_horizon)
    current_advice = MarketAdvisor().analyze_cached()
    fallback_indicators = None
    with get_db_session(read_only=True) as session:
        fallback_row = (
            session.query(AnalysisSignal.price_cny_per_gram, AnalysisSignal.indicators)
            .filter(AnalysisSignal.signal_type == "buy")
            .order_by(AnalysisSignal.timestamp.desc())
            .first()
        )
    if fallback_row:
        fallback_payload = decode_signal_indicators(fallback_row[1])
        if is_complete_signal_payload(fallback_row[0], fallback_payload):
            fallback_indicators = fallback_payload
    current_regime = _extract_current_regime_context(current_advice, fallback_indicators)
    primary_horizon_days = primary_horizon.get("horizon_days") if primary_horizon else (
        7 if 7 in normalized_horizons else normalized_horizons[0]
    )
    similar_history = _find_similar_signals(
        lookback_days=window_days,
        horizons=normalized_horizons,
    )
    regime_breakdown = _build_regime_breakdown(
        window_days=window_days,
        primary_horizon=int(primary_horizon_days),
        limit=limit,
        current_regime_label=current_regime.get("label"),
    )

    current_advice_summary = (
        f"{current_advice.get('recommendation')} / {current_advice.get('action_label')}"
        if current_advice
        else "当前建议暂不可用"
    )

    return {
        "summary": {
            "window_days": window_days,
            "signal_count": performance_snapshot.get("signal_count", 0),
            "evaluated_signal_count": performance_snapshot.get("evaluated_signal_count", 0),
            "primary_horizon_days": primary_horizon_days,
            "degradation_status": degradation_status,
            "degradation_reason": degradation_reason,
        },
        "current_advice": {
            "recommendation": current_advice.get("recommendation") if current_advice else None,
            "action_label": current_advice.get("action_label") if current_advice else None,
            "confidence": current_advice.get("confidence") if current_advice else None,
            "dominant_factor": current_advice.get("dominant_factor") if current_advice else None,
            "summary": current_advice_summary,
            "change_reason": current_advice.get("recommendation_change_reason") if current_advice else None,
            "risk_flags": current_advice.get("risk_flags", []) if current_advice else [],
        },
        "performance_snapshot": {
            "primary_horizon": primary_horizon,
            "high_score_segment": performance_snapshot.get("high_score_segment", {}),
            "horizon_stats": performance_snapshot.get("horizon_stats", []),
            "regime_breakdown": regime_breakdown,
            "current_regime": {
                "label": current_regime.get("label"),
                "alignment": current_regime.get("alignment"),
                "source": current_regime.get("source"),
            },
        },
        "risk_checks": _build_risk_checks(current_advice, performance_snapshot),
        "similar_history": similar_history,
        "generated_at": datetime.now().isoformat(),
    }


def parse_confidence_horizons(raw: str) -> list[int]:
    parsed = parse_horizon_days(raw)
    return parsed or list(DEFAULT_BACKTEST_HORIZONS)
