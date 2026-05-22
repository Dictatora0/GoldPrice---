from datetime import datetime

from fastapi import APIRouter

from app.database import get_db_session
from app.models import PriceHistory
from app.monitoring.health import build_health_payload
from app.logging_config import get_logger

router = APIRouter(prefix="/api", tags=["health"])
logger = get_logger(__name__)


@router.get(
    "/health",
    summary="Health check",
    description="Return application, database, Redis, environment and version health status.",
)
def health_check():
    payload = build_health_payload()
    with get_db_session(read_only=True) as session:
        latest = (
            session.query(PriceHistory.timestamp)
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )
    payload["last_collection"] = latest[0].isoformat() if latest else None
    payload["success"] = payload["status"] == "ok"
    payload["db"] = "ok" if payload["database"]["ok"] else "error"
    return payload
