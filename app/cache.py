import json
import hashlib
from typing import Optional, Any, Callable
from functools import wraps
from datetime import datetime

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None

from config import settings


class CacheManager:
    """Redis缓存管理器"""

    def __init__(self):
        self.enabled = settings.redis_enabled and REDIS_AVAILABLE
        self.client: Optional[aioredis.Redis] = None

        if self.enabled:
            try:
                self.client = aioredis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    db=settings.redis_db,
                    password=settings.redis_password,
                    max_connections=settings.redis_max_connections,
                    decode_responses=True
                )
            except Exception as e:
                print(f"Redis connection failed: {e}, falling back to no cache")
                self.enabled = False

    async def get(self, key: str) -> Optional[str]:
        """获取缓存"""
        if not self.enabled or not self.client:
            return None

        try:
            return await self.client.get(key)
        except Exception:
            return None

    async def set(self, key: str, value: str, ttl: int) -> bool:
        """设置缓存"""
        if not self.enabled or not self.client:
            return False

        try:
            await self.client.setex(key, ttl, value)
            return True
        except Exception:
            return False

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        if not self.enabled or not self.client:
            return False

        try:
            await self.client.delete(key)
            return True
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        if not self.enabled or not self.client:
            return False

        try:
            return await self.client.exists(key) > 0
        except Exception:
            return False

    async def ping(self) -> bool:
        """检查Redis连接"""
        if not self.enabled or not self.client:
            return False

        try:
            return await self.client.ping()
        except Exception:
            return False

    async def close(self):
        """关闭连接"""
        if self.client:
            await self.client.close()


# 全局缓存管理器实例
cache_manager = CacheManager()


def hash_args(*args, **kwargs) -> str:
    """生成参数哈希"""
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_str = ":".join(key_parts)
    return hashlib.md5(key_str.encode()).hexdigest()[:16]


def cache_result(key_prefix: str, ttl: int):
    """缓存装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            args_hash = hash_args(*args, **kwargs)
            cache_key = f"gold:{key_prefix}:{args_hash}"

            # 尝试从缓存获取
            cached = await cache_manager.get(cache_key)
            if cached:
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass

            # 缓存未命中,执行函数
            result = await func(*args, **kwargs)

            # 写入缓存
            try:
                await cache_manager.set(
                    cache_key,
                    json.dumps(result, default=str),
                    ttl
                )
            except Exception:
                pass

            return result
        return wrapper
    return decorator


async def invalidate_cache(key_pattern: str):
    """清除缓存"""
    if not cache_manager.enabled or not cache_manager.client:
        return

    try:
        # 使用SCAN而不是KEYS避免阻塞
        cursor = 0
        while True:
            cursor, keys = await cache_manager.client.scan(
                cursor,
                match=f"gold:{key_pattern}*",
                count=100
            )
            if keys:
                await cache_manager.client.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        pass
