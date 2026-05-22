from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean, ForeignKey, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from config import settings
import os

Base = declarative_base()


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    price_cny_per_gram = Column(Float, nullable=False)
    source_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    sources = relationship("PriceSource", back_populates="price_history")

    __table_args__ = (
        Index('idx_timestamp_price', 'timestamp', 'price_cny_per_gram'),
    )


class PriceSource(Base):
    __tablename__ = "price_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    price_history_id = Column(Integer, ForeignKey("price_history.id"), nullable=False)
    source_name = Column(String(50), nullable=False)
    price_cny_per_gram = Column(Float, nullable=False)
    is_valid = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    price_history = relationship("PriceHistory", back_populates="sources")

    __table_args__ = (
        Index('idx_price_history_source', 'price_history_id', 'source_name'),
    )


class AnalysisSignal(Base):
    __tablename__ = "analysis_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    signal_type = Column(String(20), nullable=False)
    price_cny_per_gram = Column(Float, nullable=False)
    indicators = Column(Text)
    notified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_notified_timestamp', 'notified', 'timestamp'),
    )


class AdviceSnapshot(Base):
    __tablename__ = "advice_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_timestamp = Column(DateTime, nullable=False, unique=True, index=True)
    recommendation = Column(String(30), nullable=False)
    action_label = Column(String(30), nullable=False)
    score = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=True)
    dominant_factor = Column(String(100), nullable=True)
    risk_flags = Column(Text, nullable=False, default="[]")
    key_indicators = Column(Text, nullable=False, default="{}")
    payload = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_advice_snapshot_timestamp', 'snapshot_timestamp'),
    )


class CustomAlertRule(Base):
    __tablename__ = "custom_alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    rule_type = Column(String(40), nullable=False)
    threshold = Column(Float, nullable=False)
    channels = Column(Text, nullable=False, default='["system"]')
    enabled = Column(Boolean, nullable=False, default=True)
    cooldown_minutes = Column(Integer, nullable=False, default=60)
    last_triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (
        Index("idx_custom_alert_enabled_type", "enabled", "rule_type"),
        Index("idx_custom_alert_last_triggered", "last_triggered_at"),
    )


class NotificationDeliveryLog(Base):
    __tablename__ = "notification_delivery_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_name = Column(String(120), nullable=False)
    channel = Column(String(40), nullable=False)
    level = Column(String(20), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(20), nullable=False)
    attempt = Column(Integer, nullable=False, default=1)
    max_attempts = Column(Integer, nullable=False, default=1)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        Index("idx_delivery_log_created", "created_at"),
        Index("idx_delivery_log_rule_channel", "rule_name", "channel"),
        Index("idx_delivery_log_status", "status"),
    )
