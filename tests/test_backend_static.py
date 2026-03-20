from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PY = ROOT / "app" / "database.py"
PRICE_API_PY = ROOT / "app" / "api" / "price.py"
ANALYSIS_API_PY = ROOT / "app" / "api" / "analysis.py"
INDICATORS_PY = ROOT / "app" / "analyzers" / "indicators.py"
ADVISOR_PY = ROOT / "app" / "analyzers" / "advisor.py"
SIGNALS_PY = ROOT / "app" / "analyzers" / "signals.py"
HEALTH_PY = ROOT / "app" / "monitoring" / "health.py"
ALERTS_PY = ROOT / "app" / "monitoring" / "alerts.py"
MAIN_PY = ROOT / "app" / "main.py"
SCHEDULER_PY = ROOT / "app" / "scheduler.py"


def test_database_session_supports_read_only_mode():
    content = DB_PY.read_text(encoding="utf-8")

    assert "def get_db_session(*, read_only: bool = False):" in content
    assert "if not read_only:" in content


def test_database_engine_uses_concurrent_safe_pooling():
    content = DB_PY.read_text(encoding="utf-8")

    assert "StaticPool" not in content
    assert "pool_pre_ping=True" in content


def test_hot_paths_use_read_only_sessions():
    price_api = PRICE_API_PY.read_text(encoding="utf-8")
    analysis_api = ANALYSIS_API_PY.read_text(encoding="utf-8")
    indicators = INDICATORS_PY.read_text(encoding="utf-8")
    signals = SIGNALS_PY.read_text(encoding="utf-8")
    advisor = ADVISOR_PY.read_text(encoding="utf-8")

    assert "with get_db_session(read_only=True) as session:" in price_api
    assert "with get_db_session(read_only=True) as session:" in indicators
    assert "with get_db_session(read_only=True) as session:" in signals
    assert "with get_db_session(read_only=True) as session:" in advisor
    assert "with get_db_session(read_only=True) as session:" in analysis_api


def test_analysis_cache_uses_valid_timestamp_source_and_json_payload():
    advisor = ADVISOR_PY.read_text(encoding="utf-8")
    signals = SIGNALS_PY.read_text(encoding="utf-8")
    indicators = INDICATORS_PY.read_text(encoding="utf-8")

    assert "PriceSource.timestamp" not in advisor
    assert "PriceSource.timestamp" not in signals
    assert "PriceHistory.timestamp" in advisor
    assert "PriceHistory.timestamp" in signals

    assert "json.loads(cached)" in advisor
    assert "json.loads(cached)" in signals
    assert "json.loads(cached)" in indicators
    assert "json.dumps(result, default=str)" in advisor
    assert "json.dumps(result, default=str)" in signals
    assert "json.dumps(result, default=str)" in indicators


def test_health_and_alerts_do_not_misuse_asyncio_run_for_sync_ping():
    health = HEALTH_PY.read_text(encoding="utf-8")
    alerts = ALERTS_PY.read_text(encoding="utf-8")

    assert "asyncio.run(cache_manager.ping())" not in health
    assert "asyncio.run(cache_manager.ping())" not in alerts
    assert "cache_manager.ping()" in health
    assert "cache_manager.ping()" in alerts


def test_main_shutdown_cleans_up_background_tasks():
    main = MAIN_PY.read_text(encoding="utf-8")

    assert "cancel_background_task" in main
    assert "task.cancel()" in main
    assert "await asyncio.gather(task, return_exceptions=True)" in main


def test_scheduler_uses_second_level_collection_interval():
    scheduler = SCHEDULER_PY.read_text(encoding="utf-8")

    assert "seconds=settings.collection_interval" in scheduler
    assert "minutes=settings.collection_interval" not in scheduler
