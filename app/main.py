import os
import logging
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.api.websocket import manager as ws_manager
from app.database import init_db
from app.scheduler import start_scheduler, shutdown_scheduler

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="GoldPrice", version="1.0.0")

    app.include_router(api_router)

    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/")
        def index():
            return FileResponse(os.path.join(static_dir, "index.html"))
    else:
        logger.warning("Static directory not found: %s", static_dir)

    @app.on_event("startup")
    def on_startup():
        init_db()
        app.state.ws_manager = ws_manager  # 存储 WebSocket 管理器到应用状态
        start_scheduler(app)

    @app.on_event("shutdown")
    def on_shutdown():
        shutdown_scheduler()

    return app


app = create_app()
