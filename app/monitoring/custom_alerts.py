from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from app.analyzers.indicators import IndicatorCalculator
from app.database import get_db_session
from app.logging_config import get_logger
from app.models import CustomAlertRule, PriceHistory

logger = get_logger(__name__)

ALERT_TYPE_PRICE_ABOVE = "price_above"
ALERT_TYPE_PRICE_BELOW = "price_below"
ALERT_TYPE_RSI_ABOVE = "rsi_above"
ALERT_TYPE_RSI_BELOW = "rsi_below"
ALERT_TYPE_DAILY_CHANGE_ABS_GTE = "daily_change_abs_gte"

SUPPORTED_RULE_TYPES = {
    ALERT_TYPE_PRICE_ABOVE,
    ALERT_TYPE_PRICE_BELOW,
    ALERT_TYPE_RSI_ABOVE,
    ALERT_TYPE_RSI_BELOW,
    ALERT_TYPE_DAILY_CHANGE_ABS_GTE,
}


@dataclass
class CustomAlertEvaluation:
    triggered: bool
    message: str
    metric_value: Optional[float]
    context: dict[str, Any]


def _safe_load_channels(raw: Any) -> list[str]:
    if isinstance(raw, list):
        parsed = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
    else:
        parsed = []

    normalized = []
    for item in parsed:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
    return sorted(set(normalized)) or ["system"]


def serialize_channels(channels: Iterable[str]) -> str:
    normalized = sorted({channel.strip() for channel in channels if isinstance(channel, str) and channel.strip()})
    if not normalized:
        normalized = ["system"]
    return json.dumps(normalized, ensure_ascii=False)


def validate_rule_payload(
    *,
    rule_type: str,
    threshold: float,
    cooldown_minutes: int,
    channels: Iterable[str],
) -> tuple[bool, str]:
    if rule_type not in SUPPORTED_RULE_TYPES:
        return False, f"Unsupported rule_type: {rule_type}"

    if cooldown_minutes < 1 or cooldown_minutes > 24 * 60:
        return False, "cooldown_minutes must be between 1 and 1440"

    if not list(channels):
        return False, "channels is required"

    if rule_type in {ALERT_TYPE_RSI_ABOVE, ALERT_TYPE_RSI_BELOW} and not (0 <= threshold <= 100):
        return False, "RSI threshold must be between 0 and 100"

    if rule_type == ALERT_TYPE_DAILY_CHANGE_ABS_GTE and threshold <= 0:
        return False, "Daily change threshold must be > 0"

    return True, ""


def _get_latest_price() -> Optional[tuple[datetime, float]]:
    with get_db_session(read_only=True) as session:
        row = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )
    if not row:
        return None
    timestamp, price = row
    return timestamp, float(price)


def _get_daily_change_pct() -> Optional[float]:
    latest = _get_latest_price()
    if not latest:
        return None

    latest_ts, latest_price = latest
    one_day_ago = latest_ts - timedelta(days=1)

    with get_db_session(read_only=True) as session:
        historical = (
            session.query(PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp <= one_day_ago)
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )

    if not historical:
        return None
    base_price = float(historical[0])
    if base_price <= 0:
        return None
    return (latest_price - base_price) / base_price * 100


def evaluate_custom_rule(rule: CustomAlertRule, indicators: Optional[dict[str, Any]] = None) -> CustomAlertEvaluation:
    latest = _get_latest_price()
    if not latest:
        return CustomAlertEvaluation(
            triggered=False,
            message="价格数据不足，跳过自定义预警评估",
            metric_value=None,
            context={},
        )

    latest_ts, latest_price = latest
    threshold = float(rule.threshold)
    context: dict[str, Any] = {"timestamp": latest_ts.isoformat()}

    if rule.rule_type == ALERT_TYPE_PRICE_ABOVE:
        triggered = latest_price >= threshold
        context["price"] = latest_price
        return CustomAlertEvaluation(
            triggered=triggered,
            metric_value=latest_price,
            context=context,
            message=f"价格触发上破阈值: ¥{latest_price:.2f} >= ¥{threshold:.2f}",
        )

    if rule.rule_type == ALERT_TYPE_PRICE_BELOW:
        triggered = latest_price <= threshold
        context["price"] = latest_price
        return CustomAlertEvaluation(
            triggered=triggered,
            metric_value=latest_price,
            context=context,
            message=f"价格触发下破阈值: ¥{latest_price:.2f} <= ¥{threshold:.2f}",
        )

    indicators_payload = indicators or IndicatorCalculator().calculate_all_cached() or {}
    rsi = indicators_payload.get("rsi")
    if rsi is not None:
        rsi = float(rsi)

    if rule.rule_type == ALERT_TYPE_RSI_ABOVE:
        if rsi is None:
            return CustomAlertEvaluation(
                triggered=False,
                metric_value=None,
                context=context,
                message="RSI 数据不足，跳过",
            )
        context["rsi"] = rsi
        triggered = rsi >= threshold
        return CustomAlertEvaluation(
            triggered=triggered,
            metric_value=rsi,
            context=context,
            message=f"RSI 触发超买阈值: {rsi:.2f} >= {threshold:.2f}",
        )

    if rule.rule_type == ALERT_TYPE_RSI_BELOW:
        if rsi is None:
            return CustomAlertEvaluation(
                triggered=False,
                metric_value=None,
                context=context,
                message="RSI 数据不足，跳过",
            )
        context["rsi"] = rsi
        triggered = rsi <= threshold
        return CustomAlertEvaluation(
            triggered=triggered,
            metric_value=rsi,
            context=context,
            message=f"RSI 触发超卖阈值: {rsi:.2f} <= {threshold:.2f}",
        )

    if rule.rule_type == ALERT_TYPE_DAILY_CHANGE_ABS_GTE:
        daily_change = _get_daily_change_pct()
        if daily_change is None:
            return CustomAlertEvaluation(
                triggered=False,
                metric_value=None,
                context=context,
                message="24小时涨跌幅数据不足，跳过",
            )
        daily_change = float(daily_change)
        context["daily_change_pct"] = daily_change
        triggered = abs(daily_change) >= threshold
        return CustomAlertEvaluation(
            triggered=triggered,
            metric_value=daily_change,
            context=context,
            message=f"24小时涨跌幅触发阈值: {daily_change:+.2f}% (阈值 {threshold:.2f}%)",
        )

    return CustomAlertEvaluation(
        triggered=False,
        metric_value=None,
        context=context,
        message=f"Unsupported rule type: {rule.rule_type}",
    )


def should_trigger_with_cooldown(rule: CustomAlertRule, now: datetime) -> bool:
    if not rule.enabled:
        return False
    if rule.last_triggered_at is None:
        return True
    cooldown_minutes = max(1, int(rule.cooldown_minutes or 1))
    return now - rule.last_triggered_at >= timedelta(minutes=cooldown_minutes)
