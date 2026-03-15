from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.models import Base
from config import settings
import os


def get_engine():
    """创建数据库引擎"""
    os.makedirs(os.path.dirname(settings.database_path), exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.database_path}", echo=settings.debug)
    return engine


def init_db():
    """初始化数据库表"""
    engine = get_engine()
    Base.metadata.create_all(engine)


def get_session() -> Session:
    """获取数据库会话"""
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()
