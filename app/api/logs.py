"""API endpoints for log viewing and management."""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy import func, desc

from app.log_models import LogEntry, get_log_session
from config import settings

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def get_logs(
    level: Optional[str] = Query(None, description="Filter by log level"),
    logger: Optional[str] = Query(None, description="Filter by logger name"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp"),
    end_time: Optional[datetime] = Query(None, description="End timestamp"),
    limit: int = Query(100, ge=1, le=1000, description="Number of logs to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """Get logs with optional filtering."""
    if not settings.log_to_postgres:
        raise HTTPException(status_code=503, detail="PostgreSQL logging is not enabled")

    session = get_log_session()
    if not session:
        raise HTTPException(status_code=503, detail="Unable to connect to log database")

    try:
        query = session.query(LogEntry)

        # Apply filters
        if level:
            query = query.filter(LogEntry.level == level.upper())
        if logger:
            query = query.filter(LogEntry.logger.like(f"%{logger}%"))
        if start_time:
            query = query.filter(LogEntry.timestamp >= start_time)
        if end_time:
            query = query.filter(LogEntry.timestamp <= end_time)

        # Get total count
        total = query.count()

        # Apply pagination and ordering
        logs = query.order_by(desc(LogEntry.timestamp)).offset(offset).limit(limit).all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "logs": [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.isoformat(),
                    "level": log.level,
                    "logger": log.logger,
                    "event": log.event,
                    "message": log.message,
                    "context": log.context,
                    "request_id": log.request_id
                }
                for log in logs
            ]
        }
    finally:
        session.close()


@router.get("/stats")
async def get_log_stats(
    hours: int = Query(24, ge=1, le=168, description="Number of hours to analyze")
):
    """Get log statistics for the specified time period."""
    if not settings.log_to_postgres:
        raise HTTPException(status_code=503, detail="PostgreSQL logging is not enabled")

    session = get_log_session()
    if not session:
        raise HTTPException(status_code=503, detail="Unable to connect to log database")

    try:
        start_time = datetime.now() - timedelta(hours=hours)

        # Count by level
        level_stats = session.query(
            LogEntry.level,
            func.count(LogEntry.id).label('count')
        ).filter(
            LogEntry.timestamp >= start_time
        ).group_by(LogEntry.level).all()

        # Count by logger
        logger_stats = session.query(
            LogEntry.logger,
            func.count(LogEntry.id).label('count')
        ).filter(
            LogEntry.timestamp >= start_time
        ).group_by(LogEntry.logger).order_by(desc('count')).limit(10).all()

        # Count by event
        event_stats = session.query(
            LogEntry.event,
            func.count(LogEntry.id).label('count')
        ).filter(
            LogEntry.timestamp >= start_time
        ).group_by(LogEntry.event).order_by(desc('count')).limit(10).all()

        # Total count
        total = session.query(func.count(LogEntry.id)).filter(
            LogEntry.timestamp >= start_time
        ).scalar()

        return {
            "period_hours": hours,
            "start_time": start_time.isoformat(),
            "total_logs": total,
            "by_level": {stat.level: stat.count for stat in level_stats},
            "top_loggers": [{"logger": stat.logger, "count": stat.count} for stat in logger_stats],
            "top_events": [{"event": stat.event, "count": stat.count} for stat in event_stats]
        }
    finally:
        session.close()


@router.get("/search")
async def search_logs(
    query: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(100, ge=1, le=1000, description="Number of results to return")
):
    """Search logs by message content."""
    if not settings.log_to_postgres:
        raise HTTPException(status_code=503, detail="PostgreSQL logging is not enabled")

    session = get_log_session()
    if not session:
        raise HTTPException(status_code=503, detail="Unable to connect to log database")

    try:
        logs = session.query(LogEntry).filter(
            LogEntry.message.like(f"%{query}%")
        ).order_by(desc(LogEntry.timestamp)).limit(limit).all()

        return {
            "query": query,
            "count": len(logs),
            "logs": [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.isoformat(),
                    "level": log.level,
                    "logger": log.logger,
                    "event": log.event,
                    "message": log.message,
                    "context": log.context,
                    "request_id": log.request_id
                }
                for log in logs
            ]
        }
    finally:
        session.close()
