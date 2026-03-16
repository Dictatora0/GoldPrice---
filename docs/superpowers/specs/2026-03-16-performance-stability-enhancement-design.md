# Performance and Stability Enhancement Implementation Design

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the gold price monitoring system with comprehensive performance optimization and stability improvements through layered integration of caching, database pooling, monitoring, logging, and alerting.

**Architecture:** Layered approach building from database foundation up through caching, metrics, logging, and alerts. Each layer provides services to layers above while maintaining independence and testability.

**Tech Stack:** SQLAlchemy connection pooling, Redis caching, Prometheus metrics, PostgreSQL logging, Apprise alerts, structlog/loguru

---

## Architecture Overview

The enhancement follows a layered architecture where each layer provides services to the layer above:

```
┌─────────────────────────────────────────┐
│   Application Layer (API, WebSocket)   │
├─────────────────────────────────────────┤
│  Business Logic (Analyzers, Signals)   │
├─────────────────────────────────────────┤
│    Observability (Metrics, Alerts)     │
├─────────────────────────────────────────┤
│      Caching Layer (Redis)             │
├─────────────────────────────────────────┤
│   Data Layer (SQLAlchemy + Pooling)    │
├─────────────────────────────────────────┤
│  Persistence (SQLite + PostgreSQL)      │
└─────────────────────────────────────────┘
```

### Key Principles

- Each layer is independent and testable
- Lower layers don't depend on upper layers
- Caching is transparent to business logic (decorator-based)
- Metrics collection is non-blocking and doesn't affect performance
- Logging is asynchronous to avoid I/O bottlenecks

### Integration Points

- Database pooling replaces current engine creation in `app/database.py`
- Cache decorators wrap expensive methods in analyzers
- Metrics middleware intercepts all HTTP requests
- PostgreSQL handler captures structured logs
- Alert rules trigger based on metric thresholds

## Layer 1: Database Connection Pooling

### Current State
`app/database.py` creates a new engine on every `get_session()` call, which is inefficient and doesn't reuse connections.

### Enhancement Design

**Global engine with connection pooling:**
```python
engine = create_engine(
    f"sqlite:///{settings.database_path}",
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    pool_recycle=settings.database_pool_recycle,
    pool_pre_ping=True  # Health check before using connection
)
```

**Session factory:**
```python
SessionLocal = sessionmaker(bind=engine)
```

**Context manager for safe usage:**
```python
@contextmanager
def get_db_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

### Configuration
- `DATABASE_POOL_SIZE=10` - Base pool size
- `DATABASE_MAX_OVERFLOW=20` - Additional connections under load
- `DATABASE_POOL_TIMEOUT=30` - Wait time for available connection
- `DATABASE_POOL_RECYCLE=3600` - Recycle connections after 1 hour

### Benefits
- Reuses connections instead of creating new ones
- Handles connection failures gracefully with `pool_pre_ping`
- Prevents connection leaks with context manager
- Configurable pool sizing for different workloads

## Layer 2: Cache Integration

### Target Components
- `IndicatorCalculator.calculate_all()` - expensive technical indicator calculations
- `SignalDetector._evaluate_buy_signal_enhanced()` - complex scoring logic
- `MarketAdvisor.analyze()` - comprehensive market analysis
- API endpoints for price history and candlestick data

### Caching Strategy

**Aggressive caching with appropriate TTLs:**
```python
# Indicators cache (2 min TTL - balance freshness vs performance)
@cache_result(key_prefix="indicators", ttl=settings.cache_indicators_ttl)
async def calculate_all_cached(self) -> dict:
    return self.calculate_all()

# Price history cache (5 min TTL - historical data changes slowly)
@cache_result(key_prefix="history", ttl=settings.cache_history_ttl)
async def get_price_history_cached(days: int) -> list:
    # Query database

# Current price cache (2 min TTL - real-time but can tolerate slight delay)
@cache_result(key_prefix="price", ttl=settings.cache_price_ttl)
async def get_current_price_cached() -> dict:
    # Query latest price
```

### Cache Invalidation
- Automatic TTL-based expiration
- Manual invalidation on new price data collection
- Pattern-based invalidation (e.g., clear all "indicators:*" keys)

### Fallback Behavior
- If Redis is unavailable, functions execute normally without caching
- No errors thrown - graceful degradation
- Cache manager already handles this in `app/cache.py`

### Integration Approach
- Add async wrapper methods to existing classes
- Keep synchronous methods for backward compatibility
- Update API endpoints to use cached versions
- Add cache hit/miss metrics

## Layer 3: Metrics Instrumentation

### Instrumentation Points

**1. Data Collection Layer:**
- Wrap each collector's `fetch()` method to record success/failure/duration
- Track price updates and data source availability
- Monitor collection intervals and delays

**2. Analysis Layer:**
- Instrument indicator calculation time
- Track signal detection frequency and scores
- Monitor advisor analysis performance

**3. API Layer:**
- Use existing `MetricsMiddleware` for HTTP requests
- Add WebSocket connection tracking (connect/disconnect events)
- Track message send/receive rates

**4. Cache Layer:**
- Record cache hit/miss ratios per key prefix
- Monitor Redis connection pool usage
- Track cache operation latency

**5. System Resources:**
- Periodic collection (every 30s) of CPU, memory, disk usage
- Database connection pool metrics
- Active session counts

### Metrics Endpoint
```python
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

@app.get("/metrics")
async def metrics():
    return Response(
        generate_latest(metrics_collector.registry),
        media_type=CONTENT_TYPE_LATEST
    )
```

### Integration Pattern
```python
# Example: Instrument collector
def fetch(self):
    start_time = time.time()
    try:
        result = self._fetch_impl()
        duration = time.time() - start_time
        metrics_collector.record_collection_success(
            source=self.name,
            duration=duration
        )
        return result
    except Exception as e:
        metrics_collector.record_collection_failure(source=self.name)
        raise
```

### Dashboard Queries
- Collection success rate: `rate(gold_collector_success_total[5m])`
- API latency p95: `histogram_quantile(0.95, gold_http_request_duration_seconds)`
- Cache hit rate: `gold_cache_hits_total / (gold_cache_hits_total + gold_cache_misses_total)`

## Layer 4: PostgreSQL Logging

### Architecture
- Dual logging: file-based (loguru) + database (PostgreSQL)
- Structured logs stored in PostgreSQL for querying and analysis
- Async log writing to avoid blocking application
- Web-based log viewer for searching and filtering

### Database Schema
```python
# app/log_models.py
class LogEntry(Base):
    __tablename__ = 'logs'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    level = Column(String(10), index=True)
    logger_name = Column(String(100), index=True)
    function_name = Column(String(100))
    line_number = Column(Integer)
    message = Column(Text)
    exception = Column(Text, nullable=True)
    context = Column(JSON, nullable=True)  # Structured context data

    # Indexes for common queries
    __table_args__ = (
        Index('idx_timestamp_level', 'timestamp', 'level'),
        Index('idx_logger_timestamp', 'logger_name', 'timestamp'),
    )
```

### PostgreSQL Handler
```python
class PostgreSQLHandler(logging.Handler):
    def __init__(self, connection_string):
        super().__init__()
        self.engine = create_engine(connection_string)
        self.Session = sessionmaker(bind=self.engine)

    def emit(self, record):
        # Async write to avoid blocking
        asyncio.create_task(self._write_log(record))

    async def _write_log(self, record):
        # Write log entry to PostgreSQL
```

### Log Retention
- Automatic cleanup of logs older than `settings.log_retention_days`
- Scheduled task runs daily at 3 AM
- Keeps error logs longer than info logs (configurable)

### Web Log Viewer API
```python
# New endpoints in app/api/logs.py
GET /api/logs?level=ERROR&start=2026-03-15&end=2026-03-16&limit=100
GET /api/logs/stats  # Aggregated statistics
GET /api/logs/search?q=collector+failure
```

### Configuration
- `LOG_TO_POSTGRES=true` enables PostgreSQL logging
- Falls back to file-only if PostgreSQL unavailable
- Connection pooling for log database separate from main database

## Layer 5: Alert Rules Integration

### Alert Triggering Logic
- Alerts triggered by metric thresholds and system events
- Cooldown period prevents alert spam (30 min default)
- Multiple notification channels (macOS, Webhook, Slack)

### Alert Rules Implementation

**1. Collector Failure Alert:**
```python
# Trigger when failure rate > 50% over 5 minutes
if (failures / (successes + failures)) > 0.5:
    alert_manager.send_alert(
        rule_name="collector_failure",
        level="critical",
        title="Data Collection Failing",
        message=f"Collector failure rate: {failure_rate:.1%}"
    )
```

**2. Price Spike Alert:**
```python
# Trigger on >5% price change in 1 hour
if abs(price_change_pct) > 5.0:
    alert_manager.send_alert(
        rule_name="price_spike",
        level="warning",
        title="Abnormal Price Movement",
        message=f"Price changed {price_change_pct:+.2f}% in 1 hour"
    )
```

**3. Redis Down Alert:**
```python
# Trigger when Redis health check fails
if not await cache_manager.ping():
    alert_manager.send_alert(
        rule_name="redis_down",
        level="critical",
        title="Redis Connection Failed",
        message="Cache layer unavailable, performance degraded"
    )
```

**4. High Memory Alert:**
```python
# Trigger when memory usage > 80%
if memory_percent > 80:
    alert_manager.send_alert(
        rule_name="high_memory",
        level="warning",
        title="High Memory Usage",
        message=f"Memory usage: {memory_percent:.1f}%"
    )
```

**5. WebSocket Connection Limit Alert:**
```python
# Trigger when connections > 90 (limit is 100)
if active_connections > 90:
    alert_manager.send_alert(
        rule_name="too_many_connections",
        level="warning",
        title="WebSocket Connections Near Limit",
        message=f"Active connections: {active_connections}/100"
    )
```

### Alert Monitoring Task
- Background task runs every 60 seconds
- Checks all alert conditions
- Respects cooldown periods
- Logs all alert events

### Integration Points
- Metrics collector provides data for threshold checks
- Health check endpoints trigger availability alerts
- Scheduler runs periodic alert evaluation
- Alert history stored in database for analysis

## Component Integration & Data Flow

### Request Flow (API call)
```
User Request → MetricsMiddleware (start timer)
           → Cache Check (Redis)
           → [Cache Hit] Return cached data
           → [Cache Miss] Query Database (pooled connection)
           → Calculate/Analyze (business logic)
           → Store in Cache
           → Record Metrics (duration, status)
           → Return Response
           → Log to PostgreSQL (async)
```

### Data Collection Flow
```
Scheduler Trigger → Collector.fetch()
                 → Record Metrics (start)
                 → Fetch from Source
                 → [Success] Save to DB, Update Metrics, Invalidate Cache
                 → [Failure] Record Failure Metric, Check Alert Threshold
                 → Log Event (file + PostgreSQL)
```

### Alert Evaluation Flow
```
Background Task (60s) → Query Metrics
                      → Evaluate Alert Rules
                      → [Threshold Exceeded] Check Cooldown
                      → [Can Alert] Send via Apprise
                      → Record Alert Event
                      → Log Alert
```

### WebSocket Update Flow
```
New Price Data → Invalidate Cache
              → Update Metrics (price gauge)
              → Broadcast to WebSocket Clients
              → Record Message Metric
              → Update Connection Count Metric
```

### Error Handling
- Redis failure: Graceful degradation, direct DB access
- PostgreSQL logging failure: Continue with file logging
- Metrics collection failure: Log error, continue operation
- Alert delivery failure: Log failure, retry on next cycle

### Startup Sequence
1. Initialize database engine with pooling
2. Initialize Redis connection
3. Initialize PostgreSQL logging (if enabled)
4. Initialize metrics collector
5. Initialize alert manager
6. Start background tasks (metrics, alerts, cleanup)
7. Start FastAPI application

## Testing Strategy

### Unit Tests
- Database pooling: connection reuse, pool exhaustion, reconnection
- Cache decorators: hit/miss behavior, TTL expiration, Redis unavailable
- Metrics collection: counter increments, histogram observations, gauge updates
- Alert rules: threshold detection, cooldown logic, multi-channel delivery
- PostgreSQL logging: log entry creation, retention cleanup, query performance

### Integration Tests
- End-to-end API calls with caching and metrics
- Collector execution with metrics and alerts
- WebSocket connections with connection tracking
- Cache invalidation on data updates
- Alert triggering from real metric thresholds

### Performance Tests
- Database connection pool under load (concurrent queries)
- Cache hit rate measurement (before/after optimization)
- API response time improvement (with/without cache)
- Metrics collection overhead (should be <1ms per operation)
- PostgreSQL logging throughput (async writes)

### Test Fixtures
- Mock Redis for cache tests
- In-memory SQLite for database tests
- Mock PostgreSQL for logging tests
- Mock Apprise for alert tests
- Test metrics registry (isolated from production)

### Success Criteria
- All existing 54 tests continue to pass
- New tests achieve >80% coverage of new code
- Performance tests show measurable improvement
- No memory leaks under sustained load
- Graceful degradation when dependencies fail

## Deployment & Configuration

### Environment Variables
```bash
# Database Pooling
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=3600

# Redis Cache
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_MAX_CONNECTIONS=50
CACHE_INDICATORS_TTL=120
CACHE_PRICE_TTL=120
CACHE_HISTORY_TTL=300

# PostgreSQL Logging
LOG_TO_POSTGRES=true
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=goldprice_logs
POSTGRES_USER=goldprice
POSTGRES_PASSWORD=your_password
LOG_RETENTION_DAYS=30

# Prometheus Metrics
PROMETHEUS_ENABLED=true
PROMETHEUS_PORT=9090
METRICS_COLLECTION_INTERVAL=30

# Alerts
ALERT_WEBHOOK_URL=https://your-webhook.com/alerts
ALERT_SLACK_WEBHOOK=your-slack-webhook-token
ALERT_COOLDOWN_MINUTES=30
```

### Docker Compose Enhancement
```yaml
services:
  app:
    # existing config
    depends_on:
      - redis
      - postgres
    environment:
      - REDIS_HOST=redis
      - POSTGRES_HOST=postgres

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: goldprice_logs
      POSTGRES_USER: goldprice
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  redis_data:
  postgres_data:
```

### Migration Path
1. Deploy Redis and PostgreSQL containers
2. Update application with new database pooling
3. Enable caching (can be toggled off if issues)
4. Enable metrics collection
5. Enable PostgreSQL logging
6. Configure alert rules
7. Monitor for 24 hours before full rollout

### Rollback Plan
- Set `REDIS_ENABLED=false` to disable caching
- Set `LOG_TO_POSTGRES=false` to disable PostgreSQL logging
- Set `PROMETHEUS_ENABLED=false` to disable metrics
- All features degrade gracefully to previous behavior

### Monitoring Dashboard
- Grafana dashboard for Prometheus metrics
- Log viewer web interface for PostgreSQL logs
- Health check endpoint shows all component status

## Performance Expectations

### Before Enhancement
- API response time: 200-500ms (uncached)
- Database queries: 50-100ms per query
- Indicator calculation: 100-200ms
- Memory usage: ~100MB baseline
- No visibility into performance bottlenecks

### After Enhancement
- API response time: 10-50ms (cached), 200-500ms (cache miss)
- Database queries: 20-50ms (pooled connections)
- Indicator calculation: 10-20ms (cached), 100-200ms (fresh)
- Cache hit rate: 70-90% for typical usage
- Memory usage: ~150MB baseline (Redis client + connection pools)
- Full observability via Prometheus metrics

### Expected Improvements
- 80-90% reduction in API latency for cached requests
- 50% reduction in database query time (connection pooling)
- 90% reduction in repeated calculations (caching)
- Zero downtime for Redis/PostgreSQL failures (graceful degradation)
- Alert response time: <2 minutes from issue to notification

### Resource Requirements
- Redis: ~50MB RAM for cache data
- PostgreSQL: ~100MB RAM + disk for logs
- Additional CPU: <5% overhead for metrics collection
- Network: Minimal (local connections)

### Scalability
- Current: Handles ~10 concurrent users
- Enhanced: Handles ~100 concurrent users
- Bottleneck shifts from database to business logic
- Can scale horizontally with shared Redis/PostgreSQL

## Risk Assessment & Mitigation

### Technical Risks

**1. Redis Dependency**
- Risk: Redis failure breaks caching layer
- Mitigation: Graceful degradation built into `CacheManager`, application continues without cache
- Impact: Performance degradation but no functionality loss

**2. PostgreSQL Logging Overhead**
- Risk: High log volume impacts database performance
- Mitigation: Async logging, separate database, configurable retention, can disable via config
- Impact: Minimal - logging is non-blocking

**3. Connection Pool Exhaustion**
- Risk: All connections in use, requests timeout
- Mitigation: Configurable pool size and overflow, connection recycling, pool_pre_ping health checks
- Impact: Requests may wait up to 30s (configurable timeout)

**4. Metrics Collection Overhead**
- Risk: Metrics slow down application
- Mitigation: Lightweight counters/gauges, can disable via config, no blocking operations
- Impact: <1ms per operation, negligible

**5. Cache Invalidation Bugs**
- Risk: Stale data served from cache
- Mitigation: Conservative TTLs (2-5 min), manual invalidation on updates, cache keys include parameters
- Impact: Users may see slightly outdated data for up to 5 minutes

### Operational Risks

**1. Alert Fatigue**
- Risk: Too many alerts, important ones missed
- Mitigation: 30-minute cooldown, severity levels, configurable thresholds
- Impact: May miss rapid successive failures

**2. Log Storage Growth**
- Risk: PostgreSQL disk fills up
- Mitigation: Automatic retention cleanup (30 days), configurable retention, monitoring disk usage
- Impact: Old logs deleted, need external archival for long-term storage

**3. Configuration Complexity**
- Risk: Misconfiguration causes issues
- Mitigation: Sensible defaults, validation on startup, graceful degradation, comprehensive documentation
- Impact: May need tuning for specific workloads

### Migration Risks

**1. Breaking Changes**
- Risk: New code breaks existing functionality
- Mitigation: Backward compatibility maintained, existing tests must pass, feature flags for new components
- Impact: Minimal - all enhancements are additive

**2. Deployment Complexity**
- Risk: Redis/PostgreSQL setup issues
- Mitigation: Docker Compose for easy setup, optional features (can run without), clear documentation
- Impact: Initial setup takes 10-15 minutes

## File Structure & Changes

### New Files
```
app/
├── database.py (MODIFY - add connection pooling)
├── cache.py (EXISTS - no changes needed)
├── monitoring/
│   ├── metrics.py (EXISTS - minor enhancements)
│   ├── alerts.py (EXISTS - add alert evaluation task)
│   └── health.py (MODIFY - add component health checks)
├── logging_config.py (MODIFY - add PostgreSQL handler)
├── log_models.py (CREATE - PostgreSQL log schema)
└── api/
    ├── logs.py (CREATE - log viewer API)
    └── health.py (MODIFY - enhanced health checks)

app/analyzers/
├── indicators.py (MODIFY - add cache decorators)
├── signals.py (MODIFY - add cache decorators)
└── advisor.py (MODIFY - add cache decorators)

app/collectors/
└── base.py (MODIFY - add metrics instrumentation)

tests/
├── test_database_pooling.py (CREATE)
├── test_cache_integration.py (CREATE)
├── test_metrics.py (CREATE)
├── test_alerts.py (CREATE)
└── test_postgres_logging.py (CREATE)

docker-compose.yml (MODIFY - add Redis and PostgreSQL)
requirements.txt (EXISTS - all dependencies already present)
.env.example (MODIFY - add new configuration options)
README.md (MODIFY - update with new features)
```

### Estimated Changes
- 8 files modified
- 3 files created
- 5 new test files
- ~800 lines of new code
- ~200 lines of modifications

### Critical Files
1. `app/database.py` - Foundation for all database access
2. `app/analyzers/indicators.py` - Most expensive calculations
3. `app/monitoring/alerts.py` - Alert evaluation logic
4. `app/logging_config.py` - Dual logging setup

### Dependencies (already in requirements.txt)
- redis==4.6.0
- prometheus-client==0.19.0
- py-healthcheck==1.10.0
- apprise==1.7.1
- structlog==24.1.0
- loguru==0.7.2
- psycopg2-binary==2.9.9
- psutil==5.9.8

## Implementation Approach

### Phase 1: Foundation (Database Pooling)
- Modify `app/database.py` with connection pooling
- Add context manager for session handling
- Update all database access to use new pattern
- Test connection reuse and pool behavior

### Phase 2: Performance (Caching)
- Add async cache wrappers to analyzers
- Update API endpoints to use cached methods
- Implement cache invalidation on data updates
- Add cache metrics (hit/miss tracking)

### Phase 3: Observability (Metrics)
- Instrument collectors with success/failure/duration metrics
- Add metrics middleware to FastAPI app
- Implement system resource monitoring task
- Create Prometheus metrics endpoint

### Phase 4: Persistence (PostgreSQL Logging)
- Create log models and database schema
- Implement PostgreSQL logging handler
- Add log retention cleanup task
- Create log viewer API endpoints

### Phase 5: Reliability (Alerts)
- Implement alert evaluation background task
- Configure alert rules and thresholds
- Test alert delivery and cooldown logic
- Document alert configuration

### Phase 6: Integration & Testing
- Run full test suite (existing + new tests)
- Performance testing and benchmarking
- Load testing with concurrent requests
- Documentation updates

## Success Metrics

### Performance Metrics
- API response time reduced by 80-90% for cached requests
- Database query time reduced by 50%
- Cache hit rate >70%
- Metrics collection overhead <1ms

### Reliability Metrics
- Zero downtime during Redis/PostgreSQL failures
- Alert delivery within 2 minutes of threshold breach
- All 54 existing tests pass
- New tests achieve >80% coverage

### Operational Metrics
- Deployment time <15 minutes
- Configuration complexity manageable
- Clear rollback path available
- Comprehensive monitoring in place

---

**Design Status:** Complete and ready for implementation
**Next Step:** Create detailed implementation plan with step-by-step tasks
