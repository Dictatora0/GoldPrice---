import logging
import os
import shutil
from datetime import datetime
from typing import Optional

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ModuleNotFoundError:  # pragma: no cover - handled at runtime
    AsyncIOScheduler = None
    CronTrigger = None

from app.collectors import CollectorManager
from app.database import get_session
from app.models import PriceHistory, PriceSource, AnalysisSignal
from app.analyzers.signals import SignalDetector
from app.notifiers.macos import MacOSNotifier
from config import settings

logger = logging.getLogger(__name__)


class SchedulerState:
    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None


state = SchedulerState()


def save_collection(data: dict) -> Optional[int]:
    if not data:
        return None

    valid_sources = data.get("sources", {})
    invalid_sources = data.get("invalid_sources", {})

    session = get_session()
    try:
        history = PriceHistory(
            timestamp=data["timestamp"],
            price_cny_per_gram=data["price_cny_per_gram"],
            source_count=len(valid_sources),
        )
        session.add(history)
        session.flush()

        for name, price in valid_sources.items():
            session.add(
                PriceSource(
                    price_history_id=history.id,
                    source_name=name,
                    price_cny_per_gram=price,
                    is_valid=True,
                )
            )
        for name, price in invalid_sources.items():
            session.add(
                PriceSource(
                    price_history_id=history.id,
                    source_name=name,
                    price_cny_per_gram=price,
                    is_valid=False,
                )
            )

        session.commit()
        return history.id
    finally:
        session.close()


def _get_latest_signal_payload() -> Optional[dict]:
    session = get_session()
    try:
        signal = (
            session.query(AnalysisSignal)
            .filter(AnalysisSignal.notified == False)
            .order_by(AnalysisSignal.timestamp.desc())
            .first()
        )
        if not signal:
            return None
        indicators = {}
        if signal.indicators:
            try:
                import json

                indicators = json.loads(signal.indicators)
            except json.JSONDecodeError:
                indicators = {}
        return {
            "price_cny_per_gram": signal.price_cny_per_gram,
            "indicators": indicators,
        }
    finally:
        session.close()


def run_analysis(
    detector: Optional[SignalDetector] = None,
    notifier: Optional[MacOSNotifier] = None,
    enable_notify: bool = True,
) -> bool:
    detector = detector or SignalDetector()
    notifier = notifier or MacOSNotifier()

    triggered = detector.check_buy_signal()
    if not triggered:
        return False

    if not enable_notify:
        return True

    if not detector.should_notify():
        return False

    payload = None
    if hasattr(detector, "get_latest_signal"):
        try:
            payload = detector.get_latest_signal()
        except Exception:
            payload = None

    if payload is None:
        payload = _get_latest_signal_payload()

    if not payload:
        return False

    notifier.notify_buy_signal(payload["price_cny_per_gram"], payload["indicators"])
    detector.mark_notified()
    return True


def backup_database(backup_dir: Optional[str] = None) -> Optional[str]:
    if not settings.backup_enabled:
        return None

    source_path = settings.database_path
    if not os.path.exists(source_path):
        logger.warning("Database file not found for backup: %s", source_path)
        return None

    backup_root = backup_dir or os.path.join("data", "backups")
    os.makedirs(backup_root, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"gold_price_{timestamp}.db"
    dest_path = os.path.join(backup_root, filename)

    shutil.copy2(source_path, dest_path)
    logger.info("Database backup created: %s", dest_path)
    return dest_path


async def collect_job(app=None):
    manager = CollectorManager(timeout=settings.data_source_timeout)
    data = await manager.collect_all()
    if not data:
        return

    save_collection(data)
    run_analysis(enable_notify=settings.enable_notification)

    # 广播价格更新到 WebSocket 客户端
    if app and hasattr(app.state, 'ws_manager'):
        try:
            await app.state.ws_manager.broadcast({
                "type": "price_update",
                "data": {
                    "timestamp": data["timestamp"].isoformat(),
                    "price_cny_per_gram": data["price_cny_per_gram"],
                    "source_count": len(data.get("sources", {}))
                }
            })
        except Exception as e:
            logger.error(f"Failed to broadcast price update: {e}")


def start_scheduler(app=None):
    if AsyncIOScheduler is None:
        logger.error("APScheduler not installed; scheduler not started")
        return

    if state.scheduler and state.scheduler.running:
        return

    scheduler = AsyncIOScheduler()

    # 使用 functools.partial 来传递 app 参数
    from functools import partial
    scheduler.add_job(
        partial(collect_job, app),
        "interval",
        minutes=settings.collection_interval,
        id="collect_job",
        max_instances=1,
        coalesce=True,
    )

    if settings.backup_enabled:
        try:
            hour, minute = [int(x) for x in settings.backup_time.split(":")]
            scheduler.add_job(
                backup_database,
                CronTrigger(hour=hour, minute=minute),
                id="backup_job",
                max_instances=1,
                coalesce=True,
            )
        except Exception as exc:
            logger.error("Invalid backup time config: %s", exc)

    # Add log cleanup job (daily at 3 AM)
    if settings.log_to_postgres:
        try:
            from app.main import cleanup_old_logs
            scheduler.add_job(
                cleanup_old_logs,
                CronTrigger(hour=3, minute=0),
                id="log_cleanup_job",
                max_instances=1,
                coalesce=True,
            )
            logger.info("Log cleanup job scheduled for 3:00 AM daily")
        except Exception as exc:
            logger.error("Failed to schedule log cleanup job: %s", exc)

    scheduler.start()
    state.scheduler = scheduler
    logger.info("Scheduler started")


def shutdown_scheduler():
    if state.scheduler and state.scheduler.running:
        state.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    state.scheduler = None
