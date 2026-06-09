from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.database import get_db_session
from app.models import PositionState


def _round_optional(value: Optional[float], digits: int = 3) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _safe_float(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def serialize_position_state(row: Optional[PositionState]) -> dict[str, Any]:
    if row is None:
        return {
            "has_position": False,
            "quantity_gram": 0.0,
            "avg_cost_price": None,
            "target_quantity_gram": None,
            "notes": None,
            "updated_at": None,
        }

    quantity = float(row.quantity_gram or 0)
    return {
        "has_position": quantity > 0,
        "quantity_gram": _round_optional(quantity),
        "avg_cost_price": _round_optional(row.avg_cost_price),
        "target_quantity_gram": _round_optional(row.target_quantity_gram),
        "notes": row.notes,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_position_state() -> dict[str, Any]:
    with get_db_session(read_only=True) as session:
        row = session.query(PositionState).order_by(PositionState.updated_at.desc()).first()
        return serialize_position_state(row)


def save_position_state(
    *,
    quantity_gram: float,
    avg_cost_price: Optional[float],
    target_quantity_gram: Optional[float] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    quantity = max(0.0, float(quantity_gram or 0))
    avg_cost = None if avg_cost_price is None else max(0.0, float(avg_cost_price))
    target_quantity = (
        None if target_quantity_gram is None else max(0.0, float(target_quantity_gram))
    )

    with get_db_session() as session:
        row = session.query(PositionState).order_by(PositionState.updated_at.desc()).first()
        if row is None:
            row = PositionState()
            session.add(row)
        row.quantity_gram = quantity
        row.avg_cost_price = avg_cost if quantity > 0 else None
        row.target_quantity_gram = target_quantity
        row.notes = notes
        row.updated_at = datetime.now()
        session.flush()
        return serialize_position_state(row)


def build_position_advice(
    *,
    current_price: Optional[float],
    avg_cost_price: Optional[float],
    quantity_gram: Optional[float],
    recommendation: str,
    indicators: dict[str, Any],
    target_quantity_gram: Optional[float] = None,
) -> dict[str, Any]:
    quantity = _safe_float(quantity_gram) or 0.0
    current = _safe_float(current_price)
    avg_cost = _safe_float(avg_cost_price)
    target_quantity = _safe_float(target_quantity_gram)

    if quantity <= 0:
        return {
            "has_position": False,
            "action": "no_position",
            "action_label": "无持仓",
            "suggested_sell_pct": 0,
            "unrealized_pnl_cny": None,
            "unrealized_pnl_pct": None,
            "reason": "当前未记录持仓，卖出/减仓建议暂不适用。",
        }

    if current is None or avg_cost is None or avg_cost <= 0:
        return {
            "has_position": True,
            "action": "hold",
            "action_label": "继续持有",
            "suggested_sell_pct": 0,
            "unrealized_pnl_cny": None,
            "unrealized_pnl_pct": None,
            "reason": "持仓成本或当前价格不足，先只展示持仓状态，不生成卖出建议。",
        }

    pnl_per_gram = current - avg_cost
    pnl_cny = pnl_per_gram * quantity
    pnl_pct = (pnl_per_gram / avg_cost) * 100
    rsi = _safe_float(indicators.get("rsi"))
    bb_upper = _safe_float(indicators.get("bb_upper"))
    suggested_sell_pct = 0
    action = "hold"
    action_label = "继续持有"
    reason = "当前未触发明确卖出条件，继续按原计划持有并跟踪风险。"

    if target_quantity is not None and target_quantity >= 0 and quantity > target_quantity:
        suggested_sell_pct = max(5, min(100, round(((quantity - target_quantity) / quantity) * 100)))
        action = "trim_to_target"
        action_label = "降至目标仓位"
        reason = f"当前持仓 {quantity:.3f}g 高于目标 {target_quantity:.3f}g，可按计划降仓。"
    elif pnl_pct <= -5:
        suggested_sell_pct = 25
        action = "stop_loss"
        action_label = "风险止损"
        reason = f"浮亏 {abs(pnl_pct):.2f}%，已接近风险控制区，建议先减仓降低回撤。"
    elif pnl_pct >= 8 and rsi is not None and rsi >= 72:
        suggested_sell_pct = 30
        action = "reduce"
        action_label = "分批减仓"
        reason = f"浮盈 {pnl_pct:.2f}%，RSI {rsi:.1f} 偏热，适合先兑现部分收益。"
    elif pnl_pct >= 12:
        suggested_sell_pct = 25
        action = "take_profit"
        action_label = "止盈一部分"
        reason = f"浮盈 {pnl_pct:.2f}%，可分批止盈，保留底仓继续跟踪趋势。"
    elif bb_upper is not None and current >= bb_upper and pnl_pct > 3:
        suggested_sell_pct = 20
        action = "reduce"
        action_label = "逢高减仓"
        reason = "价格接近或突破布林上轨且已有浮盈，适合降低追高风险。"
    elif recommendation in {"强烈不推荐", "不推荐"} and pnl_pct > 0:
        suggested_sell_pct = 15
        action = "reduce"
        action_label = "降低风险"
        reason = "当前综合建议偏谨慎且持仓已有浮盈，可先减小风险暴露。"

    return {
        "has_position": True,
        "action": action,
        "action_label": action_label,
        "suggested_sell_pct": int(suggested_sell_pct),
        "unrealized_pnl_cny": _round_optional(pnl_cny, 2),
        "unrealized_pnl_pct": _round_optional(pnl_pct, 3),
        "reason": reason,
    }


def build_current_position_advice(
    *,
    current_price: Optional[float],
    recommendation: str,
    indicators: dict[str, Any],
) -> dict[str, Any]:
    position = get_position_state()
    sell_advice = build_position_advice(
        current_price=current_price,
        avg_cost_price=position.get("avg_cost_price"),
        quantity_gram=position.get("quantity_gram"),
        target_quantity_gram=position.get("target_quantity_gram"),
        recommendation=recommendation,
        indicators=indicators,
    )
    return {"position": position, "sell_advice": sell_advice}
