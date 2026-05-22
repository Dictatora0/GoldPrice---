import json
import hashlib
import asyncio
from typing import Optional, Callable
from functools import wraps
from app.logging_config import get_logger

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

from config import settings

logger = get_logger(__name__)

KEY_PREFIX = "gold"


def build_cache_key(category: str, *parts: str) -> str:
    return ":".join((KEY_PREFIX, category, *parts))


def get_json_cache(key: str) -> Optional[object]:
    cached = cache_manager.get(key)
    if cached is None:
        return None
    try:
        return json.loads(cached)
    except json.JSONDecodeError:
        logger.warning("Failed to decode cached JSON for %s", key, exc_info=True)
        return None


def set_json_cache(key: str, payload: object, ttl: int) -> bool:
    try:
        return cache_manager.set(key, json.dumps(payload, default=str), ttl)
    except Exception:
        logger.exception("Failed to serialize cache payload for %s", key)
        return False


def warm_cache(entries: list[tuple[str, object, int]]) -> dict:
    warmed = 0
    failed = 0
    for key, payload, ttl in entries:
        if set_json_cache(key, payload, ttl):
            warmed += 1
        else:
            failed += 1
    logger.info("Cache warmup completed: warmed=%s failed=%s", warmed, failed)
    return {"warmed": warmed, "failed": failed}


class CacheManager:
    """Redis缓存管理器"""

    def __init__(self):
        self.enabled = settings.redis_enabled and REDIS_AVAILABLE
        self.client: Optional[redis.Redis] = None
        self.cache_hits = 0
        self.cache_misses = 0

        if self.enabled:
            try:
                self.client = redis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    db=settings.redis_db,
                    password=settings.redis_password,
                    max_connections=settings.redis_max_connections,
                    decode_responses=True
                )
            except Exception as e:
                logger.warning("Redis connection failed, falling back to no cache: %s", e)
                self.enabled = False

    def get(self, key: str) -> Optional[str]:
        """获取缓存"""
        try:
            from app.monitoring.metrics import metrics_collector
        except Exception:
            metrics_collector = None

        if not self.enabled or not self.client:
            self.cache_misses += 1
            return None

        try:
            result = self.client.get(key)
            key_prefix = key.split(':')[1] if key.count(':') >= 2 else key.split(':')[0]

            if result is not None:
                self.cache_hits += 1
                if metrics_collector:
                    metrics_collector.record_cache_hit(key_prefix=key_prefix)
            else:
                self.cache_misses += 1
                if metrics_collector:
                    metrics_collector.record_cache_miss(key_prefix=key_prefix)
            return result
        except Exception:
            self.cache_misses += 1
            key_prefix = key.split(':')[1] if key.count(':') >= 2 else key.split(':')[0]
            logger.warning("Cache get failed for key %s", key, exc_info=True)
            if metrics_collector:
                metrics_collector.record_cache_miss(key_prefix=key_prefix)
            return None

    def set(self, key: str, value: str, ttl: int) -> bool:
        """设置缓存"""
        if not self.enabled or not self.client:
            return False

        try:
            self.client.setex(key, ttl, value)
            return True
        except Exception:
            logger.warning("Cache set failed for key %s", key, exc_info=True)
            return False

    def delete(self, key: str) -> bool:
        """删除缓存"""
        if not self.enabled or not self.client:
            return False

        try:
            self.client.delete(key)
            return True
        except Exception:
            logger.warning("Cache delete failed for key %s", key, exc_info=True)
            return False

    def delete_pattern(self, pattern: str, *, count: int = 100) -> bool:
        """删除匹配模式的缓存键"""
        if not self.enabled or not self.client:
            return False

        if not pattern.startswith(f"{KEY_PREFIX}:"):
            logger.warning("Cache delete pattern outside namespace: %s", pattern)
            return False

        try:
            cursor = 0
            while True:
                cursor, keys = self.client.scan(
                    cursor,
                    match=pattern,
                    count=count
                )
                if keys:
                    self.client.delete(*keys)
                if cursor == 0:
                    break
            return True
        except Exception:
            logger.exception("Cache delete pattern failed for %s", pattern)
            return False

    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        if not self.enabled or not self.client:
            return False

        try:
            return self.client.exists(key) > 0
        except Exception:
            logger.warning("Cache exists failed for key %s", key, exc_info=True)
            return False

    def ping(self) -> bool:
        """检查Redis连接"""
        if not self.enabled or not self.client:
            return False

        try:
            return self.client.ping()
        except Exception:
            logger.warning("Cache ping failed", exc_info=True)
            return False

    def close(self):
        """关闭连接"""
        if self.client:
            self.client.close()

    def reset(self):
        self.cache_hits = 0
        self.cache_misses = 0

    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = self.cache_hits / total_requests if total_requests > 0 else 0.0

        return {
            'hits': self.cache_hits,
            'misses': self.cache_misses,
            'total_requests': total_requests,
            'hit_rate': hit_rate
        }


# 全局缓存管理器实例
cache_manager = CacheManager()


def hash_args(*args, **kwargs) -> str:
    """生成参数哈希"""
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_str = ":".join(key_parts)
    return hashlib.md5(key_str.encode()).hexdigest()[:16]


def cache_result(key_prefix: str, ttl: int):
    """缓存装饰器 - 支持同步和异步函数"""
    def decorator(func: Callable):
        is_async = asyncio.iscoroutinefunction(func)

        if is_async:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                # 生成缓存键
                args_hash = hash_args(*args, **kwargs)
                cache_key = build_cache_key(key_prefix, args_hash)

                # 尝试从缓存获取
                cached = cache_manager.get(cache_key)
                if cached is not None:
                    try:
                        return json.loads(cached)
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode cached value for %s", cache_key, exc_info=True)

                # 缓存未命中,执行函数
                result = await func(*args, **kwargs)

                # 写入缓存
                try:
                    cache_manager.set(cache_key, json.dumps(result, default=str), ttl)
                except Exception:
                    logger.warning("Cache write failed for {}", cache_key, exc_info=True)

                return result
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                # 生成缓存键
                args_hash = hash_args(*args, **kwargs)
                cache_key = build_cache_key(key_prefix, args_hash)

                # 尝试从缓存获取
                cached = cache_manager.get(cache_key)
                if cached is not None:
                    try:
                        return json.loads(cached)
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode cached value for %s", cache_key, exc_info=True)

                # 缓存未命中,执行函数
                result = func(*args, **kwargs)

                # 写入缓存
                try:
                    cache_manager.set(cache_key, json.dumps(result, default=str), ttl)
                except Exception:
                    logger.warning("Cache write failed for {}", cache_key, exc_info=True)

                return result
            return sync_wrapper
    return decorator


def invalidate_cache(key_pattern: str):
    """清除缓存"""
    if not cache_manager.enabled or not cache_manager.client:
        return

    try:
        if not key_pattern.startswith(f"{KEY_PREFIX}:"):
            key_pattern = f"{KEY_PREFIX}:{key_pattern}"
        # 使用SCAN而不是KEYS避免阻塞
        cursor = 0
        while True:
            cursor, keys = cache_manager.client.scan(
                cursor,
                match=f"{key_pattern}*",
                count=100
            )
            if keys:
                cache_manager.client.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        logger.exception("Cache invalidation failed for %s", key_pattern)
