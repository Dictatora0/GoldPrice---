from datetime import datetime, timedelta
from typing import Tuple

from app.database import get_db_session
from app.models import PriceHistory
from app.cache import cache_manager
from app.monitoring.runtime_state import runtime_state
from config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

def check_database() -> Tuple[bool, str]:
    """数据库健康检查"""
    try:
        from sqlalchemy import text
        with get_db_session(read_only=True) as session:
            session.execute(text("SELECT 1"))
        return True, "Database OK"
    except Exception as e:
        logger.warning("Database health check failed: %s", e)
        return False, f"Database error: {str(e)}"


def check_redis() -> Tuple[bool, str]:
    """Redis健康检查"""
    try:
        result = cache_manager.ping()
        if result:
            return True, "Redis OK"
        return False, "Redis not responding"
    except Exception as e:
        logger.warning("Redis health check failed: %s", e)
        return False, f"Redis error: {str(e)}"


def check_data_freshness() -> Tuple[bool, str]:
    """数据新鲜度检查"""
    try:
        with get_db_session(read_only=True) as session:
            last_price = session.query(PriceHistory.timestamp)\
                .order_by(PriceHistory.timestamp.desc())\
                .first()

        if not last_price:
            return False, "No data available"

        age = datetime.now() - last_price[0]
        if age > timedelta(minutes=5):
            return False, f"Data is stale (last update: {age.total_seconds():.0f}s ago)"

        return True, f"Data is fresh (last update: {age.total_seconds():.0f}s ago)"
    except Exception as e:
        logger.warning("Data freshness check failed: %s", e)
        return False, f"Data freshness check error: {str(e)}"


def build_health_payload() -> dict:
    db_ok, db_message = check_database()
    redis_ok, redis_message = check_redis() if settings.redis_enabled else (True, "Redis disabled")
    fresh_ok, fresh_message = check_data_freshness()
    runtime = runtime_state.snapshot()

    scheduler = runtime.get("scheduler", {})
    scheduler_running = bool(scheduler.get("running"))
    scheduler_enabled = bool(scheduler.get("enabled"))
    scheduler_ok = (not scheduler_enabled) or scheduler_running

    alerts_loop = runtime.get("alerts_loop", {})
    alerts_enabled = bool(alerts_loop.get("enabled"))
    alerts_running = bool(alerts_loop.get("running"))
    alerts_ok = (not alerts_enabled) or alerts_running

    runtime_ok = scheduler_ok and alerts_ok

    return {
        "status": "ok" if db_ok and fresh_ok and redis_ok and runtime_ok else "degraded",
        "app": "ok",
        "environment": "development" if settings.debug else "production",
        "version": "2.0.0",
        "database": {"ok": db_ok, "message": db_message},
        "redis": {"ok": redis_ok, "message": redis_message, "enabled": settings.redis_enabled},
        "data": {"ok": fresh_ok, "message": fresh_message},
        "runtime": {
            "ok": runtime_ok,
            "scheduler": {
                "ok": scheduler_ok,
                "enabled": scheduler_enabled,
                "running": scheduler_running,
            },
            "alerts_loop": {
                "ok": alerts_ok,
                "enabled": alerts_enabled,
                "running": alerts_running,
            },
            "details": runtime,
        },
    }
