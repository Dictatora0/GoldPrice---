import sys
import logging
from pathlib import Path
from loguru import logger
import structlog

from config import settings


def setup_logging():
    """配置日志系统"""

    # 创建日志目录
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # 移除默认的loguru handler
    logger.remove()

    # 添加控制台输出
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
    )

    # 添加INFO日志文件
    logger.add(
        "logs/info.log",
        rotation="00:00",
        retention="30 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function} - {message}",
        enqueue=True,
        backtrace=False,
        diagnose=False
    )

    # 添加ERROR日志文件
    logger.add(
        "logs/error.log",
        rotation="10 MB",
        retention="90 days",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
        enqueue=True,
        backtrace=True,
        diagnose=True
    )

    # 添加DEBUG日志文件
    if settings.debug:
        logger.add(
            "logs/debug.log",
            rotation="1 day",
            retention="7 days",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
            enqueue=True
        )

    # 添加PostgreSQL日志处理器
    if settings.log_to_postgres:
        try:
            from app.log_models import PostgreSQLLogHandler, init_log_db
            init_log_db()
            postgres_handler = PostgreSQLLogHandler()
            postgres_handler.setLevel(logging.INFO)
            logging.root.addHandler(postgres_handler)
            logger.info("PostgreSQL logging handler initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize PostgreSQL logging: {e}")

    # 配置structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logger.info("Logging system initialized")


def get_logger(name: str):
    """获取logger实例"""
    return logger.bind(name=name)
