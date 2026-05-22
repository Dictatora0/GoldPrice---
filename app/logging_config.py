import logging
import sys
from pathlib import Path

from config import settings


def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s - %(message)s"
    )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    info_file = logging.FileHandler("logs/info.log")
    info_file.setLevel(logging.INFO)
    info_file.setFormatter(formatter)
    root.addHandler(info_file)

    error_file = logging.FileHandler("logs/error.log")
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(formatter)
    root.addHandler(error_file)

    if settings.debug:
        debug_file = logging.FileHandler("logs/debug.log")
        debug_file.setLevel(logging.DEBUG)
        debug_file.setFormatter(formatter)
        root.addHandler(debug_file)

    if settings.log_to_postgres:
        try:
            from app.log_models import PostgreSQLLogHandler, init_log_db

            init_log_db()
            postgres_handler = PostgreSQLLogHandler()
            postgres_handler.setLevel(logging.INFO)
            root.addHandler(postgres_handler)
            root.info("PostgreSQL logging handler initialized")
        except Exception as exc:
            root.warning("Failed to initialize PostgreSQL logging: %s", exc)

    root.info("Logging system initialized")


def get_logger(name: str):
    return logging.getLogger(name)
