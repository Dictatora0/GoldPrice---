# 黄金价格监控系统 - 性能和稳定性增强设计文档

**日期:** 2026-03-16
**项目:** GoldPrice - 性能和稳定性增强
**版本:** v2.0.0

## 1. 概述

本次增强将在现有黄金价格监控系统基础上添加企业级性能和稳定性功能:

1. **Redis缓存层** - 完整缓存方案,支持高并发访问
2. **数据库查询优化** - 索引优化、连接池管理、查询优化
3. **监控和告警系统** - Prometheus指标、健康检查、多渠道告警
4. **日志分析和可视化** - 结构化日志、PostgreSQL存储、Web查看器

## 2. Redis缓存层设计

### 2.1 技术选型

- **redis-py** - Python Redis客户端
- **redis-om** - Redis对象映射,简化数据模型定义
- **Redis Pub/Sub** - 实时通知机制

### 2.2 缓存键设计

```
gold:price:current                      # Hash - 当前价格
gold:price:history:{days}               # String(JSON) - 历史价格
gold:indicators:current                 # Hash - 技术指标
gold:advice:current                     # String(JSON) - 智能建议
gold:candlestick:{days}:{interval}      # String(JSON) - K线数据
gold:ws:sessions                        # Set - WebSocket会话
gold:ws:stats                           # Hash - 连接统计
gold:metrics:collector                  # Hash - 采集器指标
gold:metrics:api                        # Hash - API指标
```

### 2.3 缓存策略

**TTL配置:**
- 最新价格: 120秒(2分钟,与采集间隔一致)
- 技术指标: 120秒
- 历史查询: 300秒(5分钟)
- K线数据: 300秒
- 智能建议: 120秒

**缓存模式:**
- Cache-Aside模式(先查缓存,未命中查数据库)
- 写入时同步更新缓存
- 使用装饰器简化缓存逻辑

### 2.4 Redis对象模型

```python
from redis_om import HashModel, Field
from datetime import datetime

class CachedPrice(HashModel):
    timestamp: datetime
    price_cny_per_gram: float
    source_count: int

    class Meta:
        global_key_prefix = "gold"
        model_key_prefix = "price"

class CachedIndicators(HashModel):
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    bollinger_upper: float
    bollinger_lower: float
    bollinger_middle: float
    ma_short: float
    ma_medium: float
    ma_long: float

    class Meta:
        global_key_prefix = "gold"
        model_key_prefix = "indicators"
```

### 2.5 缓存装饰器

```python
def cache_result(key_prefix: str, ttl: int):
    """缓存装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{hash_args(args, kwargs)}"

            # 尝试从缓存获取
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

            # 缓存未命中,执行函数
            result = await func(*args, **kwargs)

            # 写入缓存
            await redis_client.setex(
                cache_key,
                ttl,
                json.dumps(result, default=str)
            )

            return result
        return wrapper
    return decorator
```

## 3. 数据库查询优化

### 3.1 索引优化

**新增索引:**

```python
# price_history表 - 复合索引
Index('idx_timestamp_price', 'timestamp', 'price_cny_per_gram')

# price_sources表 - 优化JOIN
Index('idx_price_history_source', 'price_history_id', 'source_name')

# analysis_signals表 - 优化未通知信号查询
Index('idx_notified_timestamp', 'notified', 'timestamp')
```

### 3.2 查询优化

**游标分页:**
```python
def get_price_history_cursor(last_id: int = None, limit: int = 100):
    """使用游标分页,避免OFFSET性能问题"""
    query = session.query(PriceHistory)
    if last_id:
        query = query.filter(PriceHistory.id > last_id)
    return query.order_by(PriceHistory.id).limit(limit).all()
```

**预加载关联:**
```python
from sqlalchemy.orm import joinedload

# 避免N+1查询
prices = session.query(PriceHistory)\
    .options(joinedload(PriceHistory.sources))\
    .filter(PriceHistory.timestamp >= start_date)\
    .all()
```

### 3.3 连接池配置

```python
# 配置参数
database_pool_size: int = 10
database_max_overflow: int = 20
database_pool_timeout: int = 30
database_pool_recycle: int = 3600

# 应用到引擎
engine = create_engine(
    database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    pool_recycle=settings.database_pool_recycle
)
```

## 4. 监控和告警系统

### 4.1 Prometheus指标

**采集器指标:**
```python
collector_success_total = Counter(
    'gold_collector_success_total',
    'Total successful collections',
    ['source']
)

collector_failure_total = Counter(
    'gold_collector_failure_total',
    'Total failed collections',
    ['source']
)

collector_duration_seconds = Histogram(
    'gold_collector_duration_seconds',
    'Collection duration',
    ['source']
)

price_value = Gauge(
    'gold_price_cny_per_gram',
    'Current gold price'
)
```

**API性能指标:**
```python
http_requests_total = Counter(
    'gold_http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

http_request_duration_seconds = Histogram(
    'gold_http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint']
)

websocket_connections = Gauge(
    'gold_websocket_connections',
    'Active WebSocket connections'
)

websocket_messages_total = Counter(
    'gold_websocket_messages_total',
    'Total WebSocket messages',
    ['type']
)
```

**Redis性能指标:**
```python
cache_hits_total = Counter(
    'gold_cache_hits_total',
    'Cache hits',
    ['key_prefix']
)

cache_misses_total = Counter(
    'gold_cache_misses_total',
    'Cache misses',
    ['key_prefix']
)

redis_connections = Gauge(
    'gold_redis_connections',
    'Active Redis connections'
)
```

**系统资源指标:**
```python
system_cpu_percent = Gauge(
    'gold_system_cpu_percent',
    'CPU usage percentage'
)

system_memory_bytes = Gauge(
    'gold_system_memory_bytes',
    'Memory usage',
    ['type']  # used, available
)

system_disk_bytes = Gauge(
    'gold_system_disk_bytes',
    'Disk usage',
    ['path', 'type']  # used, free
)
```

### 4.2 健康检查

```python
from healthcheck import HealthCheck

health = HealthCheck()

def check_database():
    """数据库健康检查"""
    try:
        session = get_session()
        session.execute("SELECT 1")
        session.close()
        return True, "Database OK"
    except Exception as e:
        return False, f"Database error: {str(e)}"

def check_redis():
    """Redis健康检查"""
    try:
        redis_client.ping()
        return True, "Redis OK"
    except Exception as e:
        return False, f"Redis error: {str(e)}"

def check_data_freshness():
    """数据新鲜度检查"""
    last_collection = get_last_collection_time()
    if datetime.now() - last_collection > timedelta(minutes=5):
        return False, "Data is stale"
    return True, "Data is fresh"

health.add_check(check_database)
health.add_check(check_redis)
health.add_check(check_data_freshness)
```

### 4.3 告警规则

```python
ALERT_RULES = {
    "collector_failure": {
        "condition": "failure_rate > 0.5 in last 10 minutes",
        "level": "critical",
        "message": "数据采集失败率超过50%",
        "channels": ["macos", "webhook"]
    },
    "price_spike": {
        "condition": "price_change > 5% in 10 minutes",
        "level": "warning",
        "message": "价格异常波动超过5%",
        "channels": ["macos"]
    },
    "redis_down": {
        "condition": "redis_ping_failed",
        "level": "critical",
        "message": "Redis连接失败",
        "channels": ["macos", "webhook"]
    },
    "high_memory": {
        "condition": "memory_usage > 80%",
        "level": "warning",
        "message": "内存使用超过80%",
        "channels": ["webhook"]
    },
    "too_many_connections": {
        "condition": "websocket_connections > 90",
        "level": "warning",
        "message": "WebSocket连接数接近上限",
        "channels": ["webhook"]
    }
}
```

### 4.4 Apprise多渠道告警

```python
import apprise

class AlertManager:
    def __init__(self):
        self.apprise = apprise.Apprise()

        # macOS通知
        if settings.macos_notification_enabled:
            self.apprise.add('macos://')

        # Webhook
        if settings.alert_webhook_url:
            self.apprise.add(settings.alert_webhook_url)

        # Slack
        if settings.alert_slack_webhook:
            self.apprise.add(f'slack://{settings.alert_slack_webhook}')

    def send_alert(self, level: str, title: str, message: str):
        """发送告警"""
        self.apprise.notify(
            title=f"[{level.upper()}] {title}",
            body=message
        )
```

## 5. 日志系统设计

### 5.1 结构化日志

**Structlog + Loguru组合:**

```python
import structlog
from loguru import logger

# Structlog配置
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
```

**日志格式:**
```json
{
    "timestamp": "2026-03-16T12:30:45.123456Z",
    "level": "info",
    "logger": "app.collectors.sina",
    "event": "price_collected",
    "price": 1118.55,
    "source": "sina",
    "duration_ms": 234,
    "request_id": "abc123"
}
```

### 5.2 日志分级存储

```python
# Loguru配置
logger.add(
    "logs/info.log",
    rotation="00:00",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    enqueue=True
)

logger.add(
    "logs/error.log",
    rotation="10 MB",
    retention="90 days",
    level="ERROR",
    backtrace=True,
    diagnose=True
)

logger.add(
    "logs/debug.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG"
)
```

### 5.3 PostgreSQL日志存储

**日志表结构:**
```python
class LogEntry(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    level = Column(String(10), nullable=False, index=True)
    logger = Column(String(100), nullable=False, index=True)
    event = Column(String(100), nullable=False, index=True)
    message = Column(Text, nullable=False)
    context = Column(JSON)
    request_id = Column(String(50), index=True)

    __table_args__ = (
        Index('idx_timestamp_level', 'timestamp', 'level'),
        Index('idx_event_timestamp', 'event', 'timestamp'),
    )
```

### 5.4 Web日志查看器

**API端点:**
- `GET /api/logs/search` - 搜索日志
- `GET /api/logs/stats` - 日志统计
- `GET /api/logs/timeline` - 事件时间线
- `WebSocket /ws/logs` - 实时日志推送

**查询参数:**
- level: 日志级别
- logger: 日志来源
- event: 事件类型
- start_time/end_time: 时间范围
- limit/offset: 分页

**统计指标:**
- 错误趋势(按小时)
- 请求量统计
- 响应时间分布
- Top错误类型

## 6. 部署配置

### 6.1 新增依赖

```
redis==5.0.1
redis-om==0.2.1
prometheus-client==0.19.0
py-healthcheck==1.10
apprise==1.7.1
structlog==24.1.0
loguru==0.7.2
psycopg2-binary==2.9.9
psutil==5.9.8
```

### 6.2 配置参数

```python
# Redis配置
redis_enabled: bool = True
redis_host: str = "localhost"
redis_port: int = 6379
redis_db: int = 0
redis_password: Optional[str] = None
redis_max_connections: int = 50

# PostgreSQL配置
postgres_host: str = "localhost"
postgres_port: int = 5432
postgres_db: str = "goldprice_logs"
postgres_user: str = "goldprice"
postgres_password: str = ""

# 缓存配置
cache_price_ttl: int = 120
cache_indicators_ttl: int = 120
cache_history_ttl: int = 300
cache_candlestick_ttl: int = 300

# 监控配置
prometheus_enabled: bool = True
prometheus_port: int = 9090
metrics_collection_interval: int = 30

# 告警配置
alert_webhook_url: Optional[str] = None
alert_slack_webhook: Optional[str] = None
alert_cooldown_minutes: int = 30

# 日志配置
log_level: str = "INFO"
log_to_postgres: bool = True
log_retention_days: int = 30
```

### 6.3 Docker Compose

```yaml
version: '3.8'

services:
  goldprice:
    build: .
    ports:
      - "8000:8000"
      - "9090:9090"
    environment:
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres
    depends_on:
      - redis
      - postgres
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_DB=goldprice_logs
      - POSTGRES_USER=goldprice
      - POSTGRES_PASSWORD=changeme
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  redis_data:
  postgres_data:
```

## 7. 实施计划

### 7.1 Phase 1: Redis缓存层(4小时)
1. 安装Redis依赖
2. 实现缓存管理器
3. 定义Redis对象模型
4. 实现缓存装饰器
5. 集成到API端点
6. 编写单元测试

### 7.2 Phase 2: 数据库优化(2小时)
1. 添加数据库索引
2. 优化查询语句
3. 配置连接池
4. 性能测试

### 7.3 Phase 3: 监控系统(3小时)
1. 集成Prometheus客户端
2. 定义指标收集器
3. 实现健康检查
4. 配置Apprise告警
5. 实现告警规则引擎

### 7.4 Phase 4: 日志系统(3小时)
1. 配置Structlog和Loguru
2. 创建PostgreSQL日志表
3. 实现日志Handler
4. 开发Web日志查看器
5. 实现实时日志推送

### 7.5 Phase 5: 集成测试(2小时)
1. 端到端测试
2. 性能测试
3. 压力测试
4. 文档更新

**总计:** 约14小时

## 8. 测试策略

### 8.1 单元测试
- Redis缓存操作测试
- 数据库查询优化测试
- 指标收集测试
- 告警规则测试
- 日志写入测试

### 8.2 集成测试
- 缓存命中率测试
- 数据库性能测试
- 监控指标准确性测试
- 告警触发测试
- 日志查询测试

### 8.3 性能测试
- 并发请求测试(100+ QPS)
- WebSocket连接测试(100个并发)
- 缓存性能测试
- 数据库查询性能测试

## 9. 风险和注意事项

### 9.1 部署复杂度
- 需要额外的Redis和PostgreSQL服务
- 建议使用Docker Compose简化部署
- 提供详细的部署文档

### 9.2 数据迁移
- PostgreSQL日志表需要初始化
- 现有SQLite数据无需迁移
- 提供数据库初始化脚本

### 9.3 向后兼容
- Redis可选,未启用时降级到无缓存模式
- PostgreSQL日志可选,未启用时仅文件日志
- 保持现有API接口不变

### 9.4 性能影响
- Redis缓存会显著提升性能
- PostgreSQL日志写入异步处理,不影响主流程
- Prometheus指标收集开销极小

## 10. 成功指标

- API响应时间降低50%以上
- 缓存命中率达到80%以上
- 系统可支持100+ QPS
- 告警响应时间 < 1分钟
- 日志查询响应时间 < 2秒

## 11. 未来优化

1. **Grafana仪表板** - 可视化Prometheus指标
2. **分布式追踪** - OpenTelemetry集成
3. **自动扩展** - Kubernetes部署
4. **高可用** - Redis Sentinel/Cluster
5. **数据归档** - 历史数据自动归档

---

**设计完成日期:** 2026-03-16
**审核状态:** 待审核
