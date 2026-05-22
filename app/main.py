import os
import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from datetime import datetime, timedelta

from app.api import router as api_router, v1_router
from app.api.websocket import manager as ws_manager
from app.database import init_db
from app.scheduler import start_scheduler, shutdown_scheduler
from app.logging_config import setup_logging, get_logger
from app.monitoring import metrics_collector, MetricsMiddleware, alert_manager
from app.monitoring.health import build_health_payload
from app.monitoring.runtime_state import runtime_state
from app.cache import cache_manager, build_cache_key, warm_cache
from config import settings

logger = get_logger(__name__)


async def cancel_background_task(task: asyncio.Task, task_name: str):
    """Cancel and await a background task safely."""
    if not task or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    logger.info("%s stopped", task_name)


async def collect_system_metrics():
    """Background task to collect system metrics every 30 seconds."""
    runtime_state.mark_loop_running("metrics_loop", True)
    while True:
        try:
            runtime_state.mark_loop_iteration_started("metrics_loop")
            metrics_collector.update_system_metrics()
            runtime_state.mark_loop_iteration_success("metrics_loop")
            await asyncio.sleep(30)
        except Exception as e:
            runtime_state.mark_loop_iteration_failure("metrics_loop", str(e))
            logger.error("System metrics collection error: %s", e)
            await asyncio.sleep(30)


async def evaluate_alerts():
    """Background task to evaluate alert rules every 60 seconds."""
    runtime_state.mark_loop_running("alerts_loop", True)
    while True:
        try:
            runtime_state.mark_loop_iteration_started("alerts_loop")
            alert_manager.evaluate_rules()
            runtime_state.mark_loop_iteration_success("alerts_loop")
            await asyncio.sleep(60)
        except Exception as e:
            runtime_state.mark_loop_iteration_failure("alerts_loop", str(e))
            logger.error("Alert evaluation error: %s", e)
            await asyncio.sleep(60)



def cleanup_old_logs():
    """Background task to cleanup old logs from PostgreSQL."""
    if not settings.log_to_postgres:
        return

    try:
        from app.log_models import LogEntry, get_log_session
        session = get_log_session()
        if not session:
            logger.warning("Unable to connect to log database for cleanup")
            return

        cutoff_date = datetime.now() - timedelta(days=settings.log_retention_days)
        deleted = session.query(LogEntry).filter(
            LogEntry.timestamp < cutoff_date
        ).delete()
        session.commit()
        session.close()

        if deleted > 0:
            logger.info(
                "Cleaned up %s old log entries older than %s days",
                deleted,
                settings.log_retention_days,
            )
    except Exception as e:
        logger.error(f"Log cleanup error: {e}")


def asset_version(path: str) -> str:
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"


def render_index_html(static_dir: str) -> str:
    index_path = os.path.join(static_dir, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    replacements = {
        "/static/css/style.css": f"/static/css/style.css?v={asset_version(os.path.join(static_dir, 'css', 'style.css'))}",
        "/static/js/websocket.js": f"/static/js/websocket.js?v={asset_version(os.path.join(static_dir, 'js', 'websocket.js'))}",
        "/static/js/candlestick.js": f"/static/js/candlestick.js?v={asset_version(os.path.join(static_dir, 'js', 'candlestick.js'))}",
        "/static/js/chart.js": f"/static/js/chart.js?v={asset_version(os.path.join(static_dir, 'js', 'chart.js'))}",
    }

    for original, versioned in replacements.items():
        html = html.replace(original, versioned)

    return html


def prewarm_core_cache() -> dict:
    entries = [
        (
            build_cache_key("price", "latest"),
            {"status": "pending"},
            settings.cache_price_ttl,
        ),
        (
            build_cache_key("history", "core", "30d"),
            {"items": [], "meta": {"prewarmed": True}},
            settings.cache_history_ttl,
        ),
        (
            build_cache_key("indicator", "core", "latest"),
            {"status": "pending"},
            settings.cache_indicators_ttl,
        ),
    ]
    return warm_cache(entries)


def create_app() -> FastAPI:
    # 初始化日志系统
    setup_logging()

    app = FastAPI(title="GoldPrice", version="2.0.0")

    # 添加Prometheus指标中间件
    if settings.prometheus_enabled:
        app.add_middleware(MetricsMiddleware)

    app.include_router(api_router)
    app.include_router(v1_router)

    # Prometheus指标端点
    if settings.prometheus_enabled:
        @app.get("/metrics")
        def metrics():
            return Response(
                generate_latest(metrics_collector.registry),
                media_type=CONTENT_TYPE_LATEST
            )

    # 健康检查端点
    @app.get("/healthcheck")
    def healthcheck():
        return build_health_payload()

    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/")
        def index():
            return HTMLResponse(
                content=render_index_html(static_dir),
                headers={"Cache-Control": "no-store"},
            )
    else:
        logger.warning("Static directory not found: %s", static_dir)

    @app.on_event("startup")
    async def on_startup():
        logger.info("Starting GoldPrice application")
        runtime_state.mark_app_started()
        runtime_state.set_loop_enabled("alerts_loop", True)
        runtime_state.set_loop_enabled("metrics_loop", settings.prometheus_enabled)
        init_db()
        app.state.ws_manager = ws_manager
        app.state.cache_manager = cache_manager
        app.state.metrics_collector = metrics_collector
        app.state.cache_warmup = prewarm_core_cache()
        start_scheduler(app)
        # Start system metrics collection background task
        if settings.prometheus_enabled:
            app.state.metrics_task = asyncio.create_task(collect_system_metrics())
            logger.info("System metrics collection started")
        # Start alert evaluation background task
        app.state.alerts_task = asyncio.create_task(evaluate_alerts())
        logger.info("Alert evaluation started")
        logger.info("Application started successfully")

    @app.on_event("shutdown")
    async def on_shutdown():
        logger.info("Shutting down application")
        await cancel_background_task(getattr(app.state, "alerts_task", None), "Alert evaluation")
        await cancel_background_task(getattr(app.state, "metrics_task", None), "System metrics")
        runtime_state.mark_loop_running("alerts_loop", False)
        runtime_state.mark_loop_running("metrics_loop", False)
        shutdown_scheduler()
        cache_manager.close()
        logger.info("Application shutdown complete")

    return app


app = create_app()
