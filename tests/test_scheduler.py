from datetime import datetime
import os
import shutil

from app.database import init_db, get_session
from app.models import PriceHistory, PriceSource
from app.scheduler import save_collection, run_analysis, backup_database
from config import settings


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
