from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry
from typing import Dict, Optional
import time

from config import settings


class MetricsCollector:
    """Prometheus指标收集器"""

    def __init__(self):
        self.enabled = settings.prometheus_enabled
        self.registry = CollectorRegistry()

        if not self.enabled:
            return

        # 采集器指标
        self.collector_success_total = Counter(
            'gold_collector_success_total',
            'Total successful collections',
            ['source'],
            registry=self.registry
        )

        self.collector_failure_total = Counter(
            'gold_collector_failure_total',
            'Total failed collections',
            ['source'],
            registry=self.registry
        )

        self.collector_duration_seconds = Histogram(
            'gold_collector_duration_seconds',
            'Collection duration in seconds',
            ['source'],
            registry=self.registry
        )

        self.price_value = Gauge(
            'gold_price_cny_per_gram',
            'Current gold price in CNY per gram',
            registry=self.registry
        )

        # API性能指标
        self.http_requests_total = Counter(
            'gold_http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status'],
            registry=self.registry
        )

        self.http_request_duration_seconds = Histogram(
            'gold_http_request_duration_seconds',
            'HTTP request duration in seconds',
            ['method', 'endpoint'],
            registry=self.registry
        )

        # WebSocket指标
        self.websocket_connections = Gauge(
            'gold_websocket_connections',
            'Active WebSocket connections',
            registry=self.registry
        )

        self.websocket_messages_total = Counter(
            'gold_websocket_messages_total',
            'Total WebSocket messages',
            ['type'],
            registry=self.registry
        )

        # Redis缓存指标
        self.cache_hits_total = Counter(
            'gold_cache_hits_total',
            'Cache hits',
            ['key_prefix'],
            registry=self.registry
        )

        self.cache_misses_total = Counter(
            'gold_cache_misses_total',
            'Cache misses',
            ['key_prefix'],
            registry=self.registry
        )

        self.redis_connections = Gauge(
            'gold_redis_connections',
            'Active Redis connections',
            registry=self.registry
        )

        # 系统资源指标
        self.system_cpu_percent = Gauge(
            'gold_system_cpu_percent',
            'CPU usage percentage',
            registry=self.registry
        )

        self.system_memory_bytes = Gauge(
            'gold_system_memory_bytes',
            'Memory usage in bytes',
            ['type'],
            registry=self.registry
        )

        self.system_disk_bytes = Gauge(
            'gold_system_disk_bytes',
            'Disk usage in bytes',
            ['path', 'type'],
            registry=self.registry
        )

    def record_collection_success(self, source: str, duration: float):
        """记录采集成功"""
        if not self.enabled:
            return
        self.collector_success_total.labels(source=source).inc()
        self.collector_duration_seconds.labels(source=source).observe(duration)

    def record_collection_failure(self, source: str):
        """记录采集失败"""
        if not self.enabled:
            return
        self.collector_failure_total.labels(source=source).inc()

    def update_price(self, price: float):
        """更新价格"""
        if not self.enabled:
            return
        self.price_value.set(price)

    def record_http_request(self, method: str, endpoint: str, status: int, duration: float):
        """记录HTTP请求"""
        if not self.enabled:
            return
        self.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=str(status)
        ).inc()
        self.http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)

    def update_websocket_connections(self, count: int):
        """更新WebSocket连接数"""
        if not self.enabled:
            return
        self.websocket_connections.set(count)

    def record_websocket_message(self, message_type: str):
        """记录WebSocket消息"""
        if not self.enabled:
            return
        self.websocket_messages_total.labels(type=message_type).inc()

    def record_cache_hit(self, key_prefix: str):
        """记录缓存命中"""
        if not self.enabled:
            return
        self.cache_hits_total.labels(key_prefix=key_prefix).inc()

    def record_cache_miss(self, key_prefix: str):
        """记录缓存未命中"""
        if not self.enabled:
            return
        self.cache_misses_total.labels(key_prefix=key_prefix).inc()

    def update_system_metrics(self):
        """更新系统资源指标"""
        if not self.enabled:
            return

        try:
            import psutil

            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            self.system_cpu_percent.set(cpu_percent)

            # 内存使用
            memory = psutil.virtual_memory()
            self.system_memory_bytes.labels(type='used').set(memory.used)
            self.system_memory_bytes.labels(type='available').set(memory.available)

            # 磁盘使用
            disk = psutil.disk_usage('/')
            self.system_disk_bytes.labels(path='/', type='used').set(disk.used)
            self.system_disk_bytes.labels(path='/', type='free').set(disk.free)
        except Exception:
            pass


# 全局指标收集器实例
metrics_collector = MetricsCollector()


class MetricsMiddleware:
    """FastAPI中间件,用于记录HTTP请求指标"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.time() - start_time
            method = scope["method"]
            path = scope["path"]

            # 简化路径(移除ID等动态部分)
            endpoint = self._simplify_path(path)

            metrics_collector.record_http_request(
                method=method,
                endpoint=endpoint,
                status=status_code,
                duration=duration
            )

    def _simplify_path(self, path: str) -> str:
        """简化路径,移除动态部分"""
        parts = path.split('/')
        simplified = []
        for part in parts:
            if part.isdigit() or len(part) == 32:  # ID或UUID
                simplified.append('{id}')
            else:
                simplified.append(part)
        return '/'.join(simplified)
