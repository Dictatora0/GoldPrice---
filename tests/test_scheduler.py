from datetime import datetime, timedelta
import json
import os
import shutil
import statistics

from app.database import init_db, get_session
from app.models import PriceHistory, PriceSource, AnalysisSignal
from app.scheduler import (
    save_collection,
    run_analysis,
    backup_database,
    cleanup_backfill_batch,
)
from config import settings


def build_valid_signal_indicators(price: float) -> dict:
    return {
        "current_price": price,
        "rsi": 28.5,
        "volatility": 1.2,
        "ma_medium": price + 5,
        "bb_lower": price + 1,
        "evaluation_score": 72,
        "evaluation_reasons": ["RSI超卖"],
        "momentum": {"change_pct": -0.6, "trend": "down", "acceleration": 0.01},
        "timeframe_analysis": {
            "short_term": "bearish",
            "mid_term": "neutral",
            "long_term": "neutral",
            "alignment": "mixed",
        },
    }


def setup_function(_):
    if os.path.exists(settings.database_path):
        os.remove(settings.database_path)
    init_db()


def test_save_collection_writes_history_and_sources():
    now = datetime.now()
    data = {
        "timestamp": now,
        "price_cny_per_gram": 500.0,
        "sources": {"sina": 500.0, "eastmoney": 502.0},
        "invalid_sources": {"gold_cn": 520.0},
    }

    history_id = save_collection(data)

    session = get_session()
    try:
        history = session.query(PriceHistory).filter_by(id=history_id).first()
        sources = session.query(PriceSource).filter_by(price_history_id=history_id).all()
        assert history is not None
        assert history.source_count == 2
        assert len(sources) == 3
        invalid = [s for s in sources if not s.is_valid]
        assert len(invalid) == 1
        assert invalid[0].source_name == "gold_cn"
    finally:
        session.close()


def test_save_collection_rejects_price_far_from_recent_regime():
    session = get_session()
    try:
        base = datetime.now() - timedelta(minutes=15)
        for idx in range(6):
            session.add(
                PriceHistory(
                    timestamp=base + timedelta(minutes=idx * 3),
                    price_cny_per_gram=1040.0 + idx * 0.2,
                    source_count=1,
                )
            )
        session.commit()
    finally:
        session.close()

    data = {
        "timestamp": datetime.now(),
        "price_cny_per_gram": 546.0,
        "sources": {"goldcn": 546.0},
        "invalid_sources": {},
    }

    history_id = save_collection(data)

    session = get_session()
    try:
        count = session.query(PriceHistory).count()
    finally:
        session.close()

    assert history_id is None
    assert count == 6


def test_save_collection_accepts_price_within_recent_regime():
    session = get_session()
    try:
        base = datetime.now() - timedelta(minutes=15)
        for idx in range(6):
            session.add(
                PriceHistory(
                    timestamp=base + timedelta(minutes=idx * 3),
                    price_cny_per_gram=1040.0 + idx * 0.2,
                    source_count=1,
                )
            )
        session.commit()
    finally:
        session.close()

    data = {
        "timestamp": datetime.now(),
        "price_cny_per_gram": 1042.0,
        "sources": {"goldcn": 1042.0},
        "invalid_sources": {},
    }

    history_id = save_collection(data)

    session = get_session()
    try:
        history = session.query(PriceHistory).filter_by(id=history_id).first()
    finally:
        session.close()

    assert history_id is not None
    assert history is not None


def test_save_collection_skips_price_guard_when_reference_is_stale(monkeypatch):
    monkeypatch.setattr("app.scheduler.settings.price_guard_reference_max_age_hours", 1)
    stale_base = datetime.now() - timedelta(hours=30)

    session = get_session()
    try:
        for idx in range(6):
            session.add(
                PriceHistory(
                    timestamp=stale_base + timedelta(minutes=idx * 3),
                    price_cny_per_gram=1040.0 + idx * 0.2,
                    source_count=1,
                )
            )
        session.commit()
    finally:
        session.close()

    data = {
        "timestamp": datetime.now(),
        "price_cny_per_gram": 546.0,
        "sources": {"goldcn": 546.0},
        "invalid_sources": {},
    }

    history_id = save_collection(data)

    session = get_session()
    try:
        created = session.query(PriceHistory).filter_by(id=history_id).first()
    finally:
        session.close()

    assert history_id is not None
    assert created is not None
    assert created.price_cny_per_gram == 546.0


class FakeDetector:
    def __init__(self):
        self.marked = False

    def check_buy_signal(self):
        return True

    def should_notify(self):
        return True

    def get_latest_signal(self):
        return {
            "price_cny_per_gram": 480.0,
            "indicators": {"rsi": 25},
        }

    def mark_notified(self):
        self.marked = True


class FakeNotifier:
    def __init__(self):
        self.sent = False
        self.payload = None

    def notify_buy_signal(self, price, indicators):
        self.sent = True
        self.payload = {"price": price, "indicators": indicators}


def test_run_analysis_triggers_notification():
    detector = FakeDetector()
    notifier = FakeNotifier()

    run_analysis(detector=detector, notifier=notifier, enable_notify=True)

    assert notifier.sent is True
    assert notifier.payload["price"] == 480.0
    assert detector.marked is True


def test_backup_database_creates_copy(tmp_path):
    backup_dir = tmp_path / "backups"
    os.makedirs(backup_dir, exist_ok=True)

    # Create a fake db file
    with open(settings.database_path, "w", encoding="utf-8") as f:
        f.write("test")

    backup_path = backup_database(backup_dir=str(backup_dir))

    assert backup_path is not None
    assert os.path.exists(backup_path)


def test_cleanup_backfill_batch_removes_orphan_history_and_invalid_signals():
    batch_created_at = datetime(2026, 3, 20, 20, 22, 52)
    outside_batch = batch_created_at + timedelta(minutes=10)

    session = get_session()
    try:
        orphan_history = PriceHistory(
            timestamp=datetime(2026, 3, 20, 18, 22, 0),
            price_cny_per_gram=547.34,
            source_count=2,
            created_at=batch_created_at,
        )
        valid_history = PriceHistory(
            timestamp=datetime(2026, 3, 20, 20, 30, 0),
            price_cny_per_gram=1041.59,
            source_count=1,
            created_at=batch_created_at,
        )
        session.add_all([orphan_history, valid_history])
        session.flush()

        session.add(
            PriceSource(
                price_history_id=valid_history.id,
                source_name="goldcn",
                price_cny_per_gram=1041.59,
                is_valid=True,
                created_at=batch_created_at,
            )
        )

        session.add(
            AnalysisSignal(
                timestamp=datetime(2026, 3, 20, 18, 22, 51),
                signal_type="buy",
                price_cny_per_gram=548.2,
                indicators=json.dumps({"rsi": 29.8}),
                notified=False,
                created_at=batch_created_at,
            )
        )
        session.add(
            AnalysisSignal(
                timestamp=datetime(2026, 3, 20, 20, 30, 0),
                signal_type="buy",
                price_cny_per_gram=470.0,
                indicators=json.dumps(build_valid_signal_indicators(470.0)),
                notified=False,
                created_at=outside_batch,
            )
        )
        session.commit()
    finally:
        session.close()

    result = cleanup_backfill_batch(
        created_after=batch_created_at - timedelta(seconds=1),
        created_before=batch_created_at + timedelta(seconds=1),
    )

    session = get_session()
    try:
        remaining_history_prices = [
            row[0] for row in session.query(PriceHistory.price_cny_per_gram).all()
        ]
        remaining_signal_prices = [
            row[0] for row in session.query(AnalysisSignal.price_cny_per_gram).all()
        ]
    finally:
        session.close()

    assert result == {"deleted_history": 1, "deleted_signals": 1}
    assert 547.34 not in remaining_history_prices
    assert 1041.59 in remaining_history_prices
    assert 548.2 not in remaining_signal_prices
    assert 470.0 in remaining_signal_prices
