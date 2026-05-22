import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.logging_config import get_logger
from app.models import Base
from config import settings

logger = get_logger(__name__)

# 创建全局数据库引擎（带连接池）
os.makedirs(os.path.dirname(settings.database_path), exist_ok=True)

if not settings.database_path.endswith(".db"):
    logger.warning("Database path does not look like a SQLite file: %s", settings.database_path)

if settings.database_pool_size > 0 and settings.database_path.endswith(".db"):
    logger.warning("SQLite is being used with a connection pool; PostgreSQL is recommended for production.")

if settings.database_pool_size == 0:
    # Disable pooling for tests
    from sqlalchemy.pool import NullPool
    engine = create_engine(
        f"sqlite:///{settings.database_path}",
        connect_args={"check_same_thread": False},
        echo=settings.debug,
        poolclass=NullPool,
    )
else:
    # Use QueuePool for SQLite in production to support concurrent requests safely.
    engine = create_engine(
        f"sqlite:///{settings.database_path}",
        connect_args={"check_same_thread": False},
        echo=settings.debug,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
        pool_pre_ping=True,
    )

# 创建会话工厂
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db():
    """初始化数据库表"""
    Base.metadata.create_all(engine)


@contextmanager
def get_db_session(*, read_only: bool = False):
    """
    获取数据库会话的上下文管理器
    自动处理提交和回滚
    """
    session = SessionLocal()
    try:
        yield session
        if not read_only:
            session.commit()
        elif session.in_transaction():
            # 显式结束只读事务，尽早释放连接和锁
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope(*, read_only: bool = False):
    """Preferred database session context manager."""
    with get_db_session(read_only=read_only) as session:
        yield session


def get_session() -> Session:
    """
    获取数据库会话（向后兼容）
    注意：使用此方法需要手动管理会话的关闭
    推荐使用 get_db_session() 上下文管理器
    """
    logger.warning("get_session() is deprecated; use session_scope() instead")
    return SessionLocal()
