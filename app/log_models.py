import logging
from sqlalchemy import Column, Integer, String, DateTime, Text, Index, create_engine
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from typing import Optional

from config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

LogBase = declarative_base()


class LogEntry(LogBase):
    """日志条目表"""
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True, default=datetime.now)
    level = Column(String(10), nullable=False, index=True)
    logger = Column(String(100), nullable=False, index=True)
    event = Column(String(100), nullable=False, index=True)
    message = Column(Text, nullable=False)
    context = Column(JSON, nullable=True)
    request_id = Column(String(50), nullable=True, index=True)

    __table_args__ = (
        Index('idx_timestamp_level', 'timestamp', 'level'),
        Index('idx_event_timestamp', 'event', 'timestamp'),
    )


def get_log_engine():
    """获取日志数据库引擎"""
    if not settings.log_to_postgres:
        return None

    try:
        database_url = f"postgresql://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        engine = create_engine(database_url, pool_pre_ping=True)
        return engine
    except Exception as e:
        logger.warning("Failed to connect to PostgreSQL for logging: %s", e)
        return None


def init_log_db():
    """初始化日志数据库"""
    engine = get_log_engine()
    if engine:
        try:
            LogBase.metadata.create_all(engine)
            logger.info("Log database initialized")
        except Exception as e:
            logger.warning("Failed to initialize log database: %s", e)


def get_log_session():
    """获取日志数据库会话"""
    engine = get_log_engine()
    if not engine:
        return None

    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


class PostgreSQLLogHandler(logging.Handler):
    """PostgreSQL日志处理器"""

    def __init__(self):
        super().__init__()
        self.session_factory = get_log_session

    def emit(self, record: logging.LogRecord):
        """写入日志到PostgreSQL"""
        if not settings.log_to_postgres:
            return

        try:
            session = self.session_factory()
            if not session:
                return

            log_entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created),
                level=record.levelname,
                logger=record.name,
                event=getattr(record, 'event', 'unknown'),
                message=record.getMessage(),
                context=getattr(record, 'context', None),
                request_id=getattr(record, 'request_id', None)
            )

            session.add(log_entry)
            session.commit()
            session.close()
        except Exception:
            logger.exception("Failed to write log entry to PostgreSQL")
