import os
import shutil
import statistics
from datetime import datetime
from typing import Optional

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ModuleNotFoundError:  # pragma: no cover - handled at runtime
    AsyncIOScheduler = None
    CronTrigger = None

from app.collectors import CollectorManager
from app.database import get_session, get_db_session
from app.models import PriceHistory, PriceSource, AnalysisSignal
from app.analyzers.signals import SignalDetector
from app.notifiers.macos import MacOSNotifier
from app.logging_config import get_logger
from app.price_regime import filter_current_regime
from app.signal_validation import decode_signal_indicators, is_complete_signal_payload
from app.monitoring.runtime_state import runtime_state
from config import settings

logger = get_logger(__name__)


class SchedulerState:
    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None


state = SchedulerState()


def _get_recent_regime_reference_prices(session) -> tuple[list[float], Optional[datetime]]:
    rows = (
        session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
        .order_by(PriceHistory.timestamp.desc())
        .limit(settings.price_guard_reference_window)
        .all()
    )
    if not rows:
        return [], None

    latest_timestamp = rows[0][0]
    prices = [price for _, price in reversed(rows)]
    if not prices:
        return [], latest_timestamp
    return filter_current_regime(prices, price_getter=lambda price: price), latest_timestamp


def _is_collection_price_suspicious(session, price_cny_per_gram: float) -> tuple[bool, dict]:
    reference_prices, latest_reference_timestamp = _get_recent_regime_reference_prices(session)
    if latest_reference_timestamp is not None:
        reference_age_hours = (
            datetime.now() - latest_reference_timestamp
        ).total_seconds() / 3600.0
        if reference_age_hours > settings.price_guard_reference_max_age_hours:
            logger.info(
                "Skip price guard because reference data is stale (%.2fh > %sh)",
                reference_age_hours,
                settings.price_guard_reference_max_age_hours,
            )
            return False, {
                "reason": "stale_reference",
                "reference_age_hours": round(reference_age_hours, 2),
            }

    if len(reference_prices) < settings.price_guard_min_reference_points:
        return False, {}

    reference_median = statistics.median(reference_prices)
    if reference_median <= 0:
        return False, {}

    deviation_ratio = abs(price_cny_per_gram - reference_median) / reference_median
    suspicious = deviation_ratio > settings.price_guard_relative_deviation_threshold

    return suspicious, {
        "reference_median": round(reference_median, 2),
        "deviation_ratio": deviation_ratio,
        "reference_points": len(reference_prices),
    }


def save_collection(data: dict) -> Optional[int]:
    if not data:
        return None

    valid_sources = data.get("sources", {})
    invalid_sources = data.get("invalid_sources", {})

    session = get_session()
    try:
        suspicious, guard_context = _is_collection_price_suspicious(
            session,
            data["price_cny_per_gram"],
        )
        if suspicious:
            logger.warning(
                "Reject suspicious collection price %.2f (median %.2f, deviation %.2f%%, points %d)",
                data["price_cny_per_gram"],
                guard_context["reference_median"],
                guard_context["deviation_ratio"] * 100,
                guard_context["reference_points"],
            )
            return None

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
    with get_db_session(read_only=True) as session:
        signal = (
            session.query(AnalysisSignal.price_cny_per_gram, AnalysisSignal.indicators)
            .filter(AnalysisSignal.notified.is_(False))
            .order_by(AnalysisSignal.timestamp.desc())
            .first()
        )
        if not signal:
            return None
        price_cny_per_gram, indicators_raw = signal
        indicators = {}
        if indicators_raw:
            try:
                import json

                indicators = json.loads(indicators_raw)
            except json.JSONDecodeError:
                indicators = {}
        return {
            "price_cny_per_gram": price_cny_per_gram,
            "indicators": indicators,
        }


def cleanup_backfill_batch(
    *,
    created_after: datetime,
    created_before: datetime,
    dry_run: bool = False,
) -> dict:
    orphan_history_ids = []
    invalid_signal_ids = []

    with get_db_session(read_only=dry_run) as session:
        orphan_history_ids = [
            history_id
            for (history_id,) in (
                session.query(PriceHistory.id)
                .outerjoin(PriceSource, PriceSource.price_history_id == PriceHistory.id)
                .filter(PriceHistory.created_at >= created_after)
                .filter(PriceHistory.created_at <= created_before)
                .filter(PriceSource.id.is_(None))
                .all()
            )
        ]

        for signal_id, price_cny_per_gram, indicators_raw in (
            session.query(
                AnalysisSignal.id,
                AnalysisSignal.price_cny_per_gram,
                AnalysisSignal.indicators,
            )
            .filter(AnalysisSignal.created_at >= created_after)
            .filter(AnalysisSignal.created_at <= created_before)
            .all()
        ):
            indicators = decode_signal_indicators(indicators_raw)
            if not is_complete_signal_payload(price_cny_per_gram, indicators):
                invalid_signal_ids.append(signal_id)

        if not dry_run:
            if orphan_history_ids:
                session.query(PriceHistory).filter(
                    PriceHistory.id.in_(orphan_history_ids)
                ).delete(synchronize_session=False)

            if invalid_signal_ids:
                session.query(AnalysisSignal).filter(
                    AnalysisSignal.id.in_(invalid_signal_ids)
                ).delete(synchronize_session=False)

    deleted_history = len(orphan_history_ids)
    deleted_signals = len(invalid_signal_ids)
    action = "preview" if dry_run else "cleanup"
    logger.info(
        "Backfill %s complete: deleted_history=%s deleted_signals=%s",
        action,
        deleted_history,
        deleted_signals,
    )
    return {
        "deleted_history": deleted_history,
        "deleted_signals": deleted_signals,
    }


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
    runtime_state.mark_collection_started()
    manager = CollectorManager(timeout=settings.data_source_timeout)
    try:
        data = await manager.collect_all()
        if not data:
            runtime_state.mark_collection_failure("collector returned empty data")
            return

        history_id = save_collection(data)
        if history_id is None:
            reason = "collection rejected by price guard"
            runtime_state.mark_collection_rejected(reason)
            logger.warning("Skip analysis and broadcast because %s", reason)
            return

        run_analysis(enable_notify=settings.enable_notification)
        runtime_state.mark_collection_success()

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
    except Exception as exc:
        runtime_state.mark_collection_failure(str(exc))
        logger.exception("collect_job failed")
        raise


def start_scheduler(app=None):
    if AsyncIOScheduler is None:
        message = "APScheduler not installed; scheduler not started"
        logger.error(message)
        runtime_state.set_scheduler_state(enabled=False, running=False, error=message)
        return

    if state.scheduler and state.scheduler.running:
        runtime_state.set_scheduler_state(enabled=True, running=True)
        return

    scheduler = AsyncIOScheduler()

    # 使用 functools.partial 来传递 app 参数
    from functools import partial
    scheduler.add_job(
        partial(collect_job, app),
        "interval",
        seconds=settings.collection_interval,
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
    runtime_state.set_scheduler_state(enabled=True, running=True)
    logger.info("Scheduler started")


def shutdown_scheduler():
    if state.scheduler and state.scheduler.running:
        state.scheduler.shutdown(wait=False)
        runtime_state.set_scheduler_state(enabled=True, running=False)
        logger.info("Scheduler stopped")
    else:
        runtime_state.set_scheduler_state(enabled=AsyncIOScheduler is not None, running=False)
    state.scheduler = None
