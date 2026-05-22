# GoldPrice Hardening Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix confirmed security, stability, testing, and deployment issues in GoldPrice without changing core product behavior or public API compatibility.

**Architecture:** Keep the current FastAPI + SQLAlchemy + Redis shape, but tighten boundaries around config, database sessions, cache keys, logging, and health checks. Prefer additive compatibility shims over rewrites so old routes and callers still work while tests and startup checks become stricter.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, SQLite/PostgreSQL, Redis, pytest, Docker.

---

### Task 1: Secure Configuration and Environment Defaults

**Files:**
- Modify: `config.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

```python
from pydantic import ValidationError
from config import Settings

def test_postgres_password_is_required_when_postgres_enabled(monkeypatch):
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("LOG_TO_POSTGRES", "true")
    try:
        Settings()
        assert False, "expected validation error"
    except ValidationError:
        assert True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: fail because `POSTGRES_PASSWORD` is still silently defaulted.

- [ ] **Step 3: Write minimal implementation**

```python
from pydantic import Field, field_validator, model_validator

class Settings(BaseSettings):
    postgres_password: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def validate_secrets(self):
        if self.log_to_postgres and not self.postgres_password:
            raise ValueError("POSTGRES_PASSWORD is required when LOG_TO_POSTGRES is enabled")
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py .env.example docker-compose.yml README.md tests/test_config.py
git commit -m "fix: harden configuration defaults"
```

### Task 2: Database Session Scope and Test Fixture Fixes

**Files:**
- Modify: `app/database.py`
- Modify: `app/monitoring/health.py`
- Modify: `app/monitoring/alerts.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_database_pooling.py`
- Modify: `tests/test_scheduler.py`
- Modify: `tests/test_candlestick.py`

- [ ] **Step 1: Write the failing test**

```python
from app.database import session_scope

def test_session_scope_commits_and_closes():
    with session_scope() as session:
        assert session.is_active
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_pooling.py -v`
Expected: fail because `session_scope` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
@contextmanager
def session_scope(*, read_only: bool = False):
    session = SessionLocal()
    try:
        yield session
        if not read_only:
            session.commit()
        elif session.in_transaction():
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_database_pooling.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/database.py app/monitoring/health.py app/monitoring/alerts.py tests/conftest.py tests/test_database_pooling.py tests/test_scheduler.py tests/test_candlestick.py
git commit -m "fix: consolidate database session handling"
```

### Task 3: Cache Namespaces, Reset Hooks, and Safe Invalidation

**Files:**
- Modify: `app/cache.py`
- Modify: `app/api/price.py`
- Modify: `app/analyzers/indicators.py`
- Modify: `app/analyzers/signals.py`
- Modify: `app/analyzers/advisor.py`
- Modify: `app/collectors/base.py`
- Modify: `tests/test_cache_integration.py`
- Add: `tests/test_cache_keys.py`

- [ ] **Step 1: Write the failing test**

```python
from app.cache import build_cache_key, CacheManager

def test_cache_key_namespace():
    assert build_cache_key("price", "latest") == "gold:price:latest"
    cache = CacheManager()
    cache.reset()
    assert cache.get_stats()["hits"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cache_keys.py -v`
Expected: fail because key builders/reset hooks do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def build_cache_key(category: str, *parts: str) -> str:
    return "gold:" + ":".join((category, *parts))

class CacheManager:
    def reset(self):
        self.cache_hits = 0
        self.cache_misses = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cache_keys.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/cache.py app/api/price.py app/analyzers/indicators.py app/analyzers/signals.py app/analyzers/advisor.py app/collectors/base.py tests/test_cache_integration.py tests/test_cache_keys.py
git commit -m "fix: normalize cache keys and invalidation"
```

### Task 4: API Compatibility, Error Shape, and Health Endpoint

**Files:**
- Modify: `app/api/__init__.py`
- Modify: `app/api/health.py`
- Modify: `app/api/price.py`
- Modify: `app/api/analysis.py`
- Modify: `app/main.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_health_response_contains_app_db_and_redis():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py -v`
Expected: fail because unified error shape and richer health payload are missing.

- [ ] **Step 3: Write minimal implementation**

```python
def api_error(code: str, message: str, detail=None):
    return {"success": False, "error": {"code": code, "message": message, "detail": detail}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/__init__.py app/api/health.py app/api/price.py app/api/analysis.py app/main.py tests/test_api.py
git commit -m "fix: improve api compatibility and health reporting"
```

### Task 5: Docker and Dependency Audit

**Files:**
- Modify: `Dockerfile`
- Add: `.dockerignore`
- Modify: `requirements.txt`
- Add: `requirements-dev.txt`
- Modify: `README.md`
- Add: `Makefile`

- [ ] **Step 1: Write the failing test**

```bash
docker build .
```

- [ ] **Step 2: Run test to verify it fails**

Expected: current image still uses Python 3.10 and lacks hardening.

- [ ] **Step 3: Write minimal implementation**

```dockerfile
FROM python:3.12-slim AS builder
...
FROM python:3.12-slim
USER appuser
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker build .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore requirements.txt requirements-dev.txt README.md Makefile
git commit -m "fix: harden docker image and add dependency audit"
```

### Task 6: Tests, Docs, and ADRs

**Files:**
- Add: `tests/test_config.py`
- Add: `tests/test_cache_keys.py`
- Add: `docs/adr/0001-sqlite-postgres.md`
- Add: `docs/adr/0002-cache-namespaces.md`
- Add: `docs/adr/0003-env-config.md`
- Add: `docs/adr/0004-logging.md`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

```bash
python -m pytest
```

- [ ] **Step 2: Run test to verify it fails**

Expected: before fixes, pytest fails due to missing fixtures and bad imports.

- [ ] **Step 3: Write minimal implementation**

```md
ADR template:
- Background
- Decision
- Consequences
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_config.py tests/test_cache_keys.py docs/adr README.md
git commit -m "docs: add adr and test coverage for hardening"
```
