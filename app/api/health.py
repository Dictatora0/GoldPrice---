from datetime import datetime

from fastapi import APIRouter

from app.database import get_session
from app.models import PriceHistory

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check():
    session = get_session()
    try:
        latest = (
            session.query(PriceHistory)
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )
        return {
            "status": "ok",
            "db": "ok",
            "last_collection": latest.timestamp.isoformat() if latest else None,
        }
    finally:
        session.close()
