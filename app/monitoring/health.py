from healthcheck import HealthCheck
from datetime import datetime, timedelta
from typing import Tuple

from app.database import get_session
from app.models import PriceHistory
from app.cache import cache_manager


def check_database() -> Tuple[bool, str]:
    """数据库健康检查"""
    try:
        from sqlalchemy import text
        session = get_session()
        session.execute(text("SELECT 1"))
        session.close()
        return True, "Database OK"
    except Exception as e:
        return False, f"Database error: {str(e)}"


def check_redis() -> Tuple[bool, str]:
    """Redis健康检查"""
    try:
        import asyncio
        result = asyncio.run(cache_manager.ping())
        if result:
            return True, "Redis OK"
        return False, "Redis not responding"
    except Exception as e:
        return False, f"Redis error: {str(e)}"


def check_data_freshness() -> Tuple[bool, str]:
    """数据新鲜度检查"""
    try:
        session = get_session()
        last_price = session.query(PriceHistory)\
            .order_by(PriceHistory.timestamp.desc())\
            .first()
        session.close()

        if not last_price:
            return False, "No data available"

        age = datetime.now() - last_price.timestamp
        if age > timedelta(minutes=5):
            return False, f"Data is stale (last update: {age.total_seconds():.0f}s ago)"

        return True, f"Data is fresh (last update: {age.total_seconds():.0f}s ago)"
    except Exception as e:
        return False, f"Data freshness check error: {str(e)}"


# 创建健康检查实例
health_check = HealthCheck()
health_check.add_check(check_database)
health_check.add_check(check_redis)
health_check.add_check(check_data_freshness)
