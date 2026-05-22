from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.api.errors import error_response
from app.database import get_db_session
from app.models import CustomAlertRule, NotificationDeliveryLog
from app.monitoring.custom_alerts import (
    SUPPORTED_RULE_TYPES,
    serialize_channels,
    validate_rule_payload,
    _safe_load_channels,
)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _serialize_rule(rule: CustomAlertRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "threshold": rule.threshold,
        "channels": _safe_load_channels(rule.channels),
        "enabled": bool(rule.enabled),
        "cooldown_minutes": int(rule.cooldown_minutes),
        "last_triggered_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def _serialize_delivery_log(row: NotificationDeliveryLog) -> dict:
    return {
        "id": row.id,
        "rule_name": row.rule_name,
        "channel": row.channel,
        "level": row.level,
        "title": row.title,
        "message": row.message,
        "status": row.status,
        "attempt": int(row.attempt),
        "max_attempts": int(row.max_attempts),
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get(
    "",
    summary="List custom alert rules",
    description="Return all custom alert rules for threshold-based notifications.",
)
def list_alert_rules(enabled_only: bool = Query(False)):
    with get_db_session(read_only=True) as session:
        query = session.query(CustomAlertRule).order_by(CustomAlertRule.id.asc())
        if enabled_only:
            query = query.filter(CustomAlertRule.enabled.is_(True))
        rows = query.all()
        items = [_serialize_rule(row) for row in rows]
    return {
        "items": items,
        "supported_rule_types": sorted(SUPPORTED_RULE_TYPES),
    }


@router.post(
    "",
    summary="Create custom alert rule",
    description="Create a threshold-based custom alert rule.",
)
def create_alert_rule(
    name: str = Query(..., min_length=1, max_length=120),
    rule_type: str = Query(..., description="price_above/price_below/rsi_above/rsi_below/daily_change_abs_gte"),
    threshold: float = Query(...),
    channels: str = Query("system", description="Comma-separated channels: system,webhook,email,wechat"),
    cooldown_minutes: int = Query(60, ge=1, le=1440),
    enabled: bool = Query(True),
):
    channel_list = [item.strip() for item in channels.split(",") if item.strip()]
    ok, reason = validate_rule_payload(
        rule_type=rule_type,
        threshold=threshold,
        cooldown_minutes=cooldown_minutes,
        channels=channel_list,
    )
    if not ok:
        return error_response(400, "INVALID_ALERT_RULE", reason, reason)

    with get_db_session() as session:
        rule = CustomAlertRule(
            name=name.strip(),
            rule_type=rule_type,
            threshold=float(threshold),
            channels=serialize_channels(channel_list),
            cooldown_minutes=cooldown_minutes,
            enabled=enabled,
        )
        session.add(rule)
        session.flush()
        session.refresh(rule)
        payload = _serialize_rule(rule)
    return {"data": payload}


@router.patch(
    "/{rule_id}",
    summary="Update custom alert rule",
    description="Patch custom alert rule fields.",
)
def update_alert_rule(
    rule_id: int,
    name: Optional[str] = Query(None, min_length=1, max_length=120),
    threshold: Optional[float] = Query(None),
    channels: Optional[str] = Query(None, description="Comma-separated channels"),
    cooldown_minutes: Optional[int] = Query(None, ge=1, le=1440),
    enabled: Optional[bool] = Query(None),
):
    with get_db_session() as session:
        rule = session.query(CustomAlertRule).filter(CustomAlertRule.id == rule_id).first()
        if not rule:
            return error_response(404, "ALERT_RULE_NOT_FOUND", "Alert rule not found", "Alert rule not found")

        next_name = rule.name if name is None else name.strip()
        next_threshold = float(rule.threshold if threshold is None else threshold)
        next_channels_list = _safe_load_channels(rule.channels)
        if channels is not None:
            next_channels_list = [item.strip() for item in channels.split(",") if item.strip()]
        next_cooldown = int(rule.cooldown_minutes if cooldown_minutes is None else cooldown_minutes)
        next_enabled = bool(rule.enabled if enabled is None else enabled)

        ok, reason = validate_rule_payload(
            rule_type=rule.rule_type,
            threshold=next_threshold,
            cooldown_minutes=next_cooldown,
            channels=next_channels_list,
        )
        if not ok:
            return error_response(400, "INVALID_ALERT_RULE", reason, reason)

        rule.name = next_name
        rule.threshold = next_threshold
        rule.channels = serialize_channels(next_channels_list)
        rule.cooldown_minutes = next_cooldown
        rule.enabled = next_enabled
        session.flush()
        session.refresh(rule)
        payload = _serialize_rule(rule)

    return {"data": payload}


@router.delete(
    "/{rule_id}",
    summary="Delete custom alert rule",
    description="Delete an existing custom alert rule.",
)
def delete_alert_rule(rule_id: int):
    with get_db_session() as session:
        rule = session.query(CustomAlertRule).filter(CustomAlertRule.id == rule_id).first()
        if not rule:
            return error_response(404, "ALERT_RULE_NOT_FOUND", "Alert rule not found", "Alert rule not found")
        session.delete(rule)
    return {"success": True}


@router.get(
    "/deliveries",
    summary="List notification delivery logs",
    description="Return channel delivery attempts with status and retry information.",
)
def list_delivery_logs(
    channel: Optional[str] = Query(None, description="Filter by channel, e.g. system/email/wechat/webhook"),
    status: Optional[str] = Query(None, description="Filter by status: success/failed"),
    limit: int = Query(100, ge=1, le=500),
):
    with get_db_session(read_only=True) as session:
        query = session.query(NotificationDeliveryLog).order_by(NotificationDeliveryLog.created_at.desc())
        if channel:
            query = query.filter(NotificationDeliveryLog.channel == channel.strip().lower())
        if status:
            query = query.filter(NotificationDeliveryLog.status == status.strip().lower())
        rows = query.limit(limit).all()
        items = [_serialize_delivery_log(row) for row in rows]
    return {"items": items, "limit": limit}
