import os
import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from datetime import datetime, timedelta

from app.api import router as api_router
from app.api.websocket import manager as ws_manager
from app.database import init_db
from app.scheduler import start_scheduler, shutdown_scheduler
from app.logging_config import setup_logging, get_logger
from app.monitoring import metrics_collector, MetricsMiddleware, health_check, alert_manager
from app.cache import cache_manager
from config import settings

logger = get_logger(__name__)


async def cancel_background_task(task: asyncio.Task, task_name: str):
    """Cancel and await a background task safely."""
    if not task or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    logger.info(f"{task_name} stopped")


async def collect_system_metrics():
    """Background task to collect system metrics every 30 seconds."""
    while True:
        try:
            metrics_collector.update_system_metrics()
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"System metrics collection error: {e}")
            await asyncio.sleep(30)


async def evaluate_alerts():
    """Background task to evaluate alert rules every 60 seconds."""
    while True:
        try:
            alert_manager.evaluate_rules()
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Alert evaluation error: {e}")
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
            logger.info(f"Cleaned up {deleted} old log entries older than {settings.log_retention_days} days")
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


def create_app() -> FastAPI:
    # 初始化日志系统
    setup_logging()

    app = FastAPI(title="GoldPrice", version="2.0.0")

    # 添加Prometheus指标中间件
    if settings.prometheus_enabled:
        app.add_middleware(MetricsMiddleware)

    app.include_router(api_router)

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
        return health_check.run()

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
        init_db()
        app.state.ws_manager = ws_manager
        app.state.cache_manager = cache_manager
        app.state.metrics_collector = metrics_collector
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
        shutdown_scheduler()
        cache_manager.close()
        logger.info("Application shutdown complete")

    return app


app = create_app()
