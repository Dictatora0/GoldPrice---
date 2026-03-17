from fastapi import APIRouter

from app.api.price import router as price_router
from app.api.analysis import router as analysis_router
from app.api.health import router as health_router
from app.api.websocket import router as websocket_router
from app.api.logs import router as logs_router

router = APIRouter()
router.include_router(price_router)
router.include_router(analysis_router)
router.include_router(health_router)
router.include_router(websocket_router)
router.include_router(logs_router)
