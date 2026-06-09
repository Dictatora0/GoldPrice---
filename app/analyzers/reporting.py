from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.analyzers.advisor import MarketAdvisor
from app.analyzers.position import get_position_state
from app.database import get_db_session
from app.models import PriceHistory, PriceSource
from app.source_quality import (
    build_source_entry,
    build_source_health_map,
    determine_primary_source,
    summarize_source_quality,
)


def _round_optional(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _build_next_week_focus(advice: dict[str, Any] | None, source_quality: dict[str, Any], price: dict[str, Any]) -> list[str]:
    focus: list[str] = []
    if source_quality.get("confidence_level") == "low":
        focus.append("优先观察主源是否恢复稳定，低可信数据下减少操作频率。")
    if advice:
        sell_advice = advice.get("sell_advice") or {}
        if sell_advice.get("action") in {"reduce", "take_profit", "stop_loss", "trim_to_target"}:
            focus.append(sell_advice.get("reason") or "持仓已触发减仓/风控条件，优先处理仓位。")
        elif advice.get("entry_ready"):
            focus.append("入场确认较强，关注回踩支撑后的第一批执行机会。")
        else:
            focus.append("当前仍需等待入场确认，不要只因价格回落就立即执行。")
    change_pct = price.get("change_pct")
    if change_pct is not None and abs(float(change_pct)) >= 3:
        focus.append("本周波动较大，下周优先检查支撑/阻力是否重新定价。")
    if not focus:
        focus.append("继续跟踪价格、主源状态和入场触发条件。")
    return focus[:4]


def build_weekly_report(*, days: int = 7) -> dict[str, Any]:
    days = max(3, min(30, int(days)))
    start_time = datetime.now() - timedelta(days=days)
    with get_db_session(read_only=True) as session:
        price_rows = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= start_time)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )
        latest_history = (
            session.query(PriceHistory.id, PriceHistory.timestamp)
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )
        source_rows = []
        health_rows = []
        if latest_history:
            source_rows = (
                session.query(
                    PriceSource.source_name,
                    PriceSource.price_cny_per_gram,
                    PriceSource.is_valid,
                )
                .filter(PriceSource.price_history_id == latest_history.id)
                .all()
            )
            health_rows = (
                session.query(PriceSource.source_name, PriceSource.is_valid)
                .order_by(PriceSource.created_at.desc())
                .limit(200)
                .all()
            )

    start_price = float(price_rows[0][1]) if price_rows else None
    end_price = float(price_rows[-1][1]) if price_rows else None
    change_pct = (
        ((end_price - start_price) / start_price) * 100
        if start_price and end_price is not None and start_price > 0
        else None
    )
    price_payload = {
        "start_price": _round_optional(start_price),
        "end_price": _round_optional(end_price),
        "change_pct": _round_optional(change_pct, 3),
        "sample_count": len(price_rows),
    }

    health_map = build_source_health_map(health_rows)
    sources = [
        build_source_entry(
            source_name=source_name,
            price_cny_per_gram=source_price,
            is_valid=is_valid,
            health=health_map.get(source_name),
        )
        for source_name, source_price, is_valid in source_rows
    ]
    source_quality = summarize_source_quality(sources)
    primary_source = determine_primary_source(sources)

    advice = MarketAdvisor().analyze_cached()
    advice_payload = {
        "recommendation": advice.get("recommendation") if advice else None,
        "action_label": advice.get("action_label") if advice else None,
        "confidence": advice.get("confidence") if advice else None,
        "sell_advice": advice.get("sell_advice") if advice else None,
    }
    position = get_position_state()

    return {
        "period_days": days,
        "price": price_payload,
        "advice": advice_payload,
        "source_quality": {
            **source_quality,
            "primary_source": primary_source,
        },
        "position": position,
        "next_week_focus": _build_next_week_focus(advice, source_quality, price_payload),
        "generated_at": datetime.now().isoformat(),
    }
