import json
from datetime import datetime, timedelta
import time
import re
from collections import OrderedDict
from typing import Optional, List, Dict

import pandas as pd
from fastapi import APIRouter, Query

from app.api.errors import error_response
from app.cache import cache_manager, get_json_cache, set_json_cache, build_cache_key
from app.database import get_db_session
from app.models import PriceHistory, PriceSource, SourceDiagnostic
from app.price_regime import build_regime_meta, filter_current_regime
from app.source_quality import (
    build_source_entry,
    build_source_health_map,
    calculate_consensus_price,
    determine_primary_source,
    build_diagnostic_payload,
    summarize_source_quality,
)
from config import settings

router = APIRouter(prefix="/api/price", tags=["price"])

class HistoryLocalCache:
    def __init__(self, max_items: int = 256):
        self.max_items = max_items
        self._store: OrderedDict[str, tuple[float, Dict]] = OrderedDict()

    def get(self, cache_key: str) -> Optional[Dict]:
        item = self._store.get(cache_key)
        if not item:
            return None
        expires_at, payload = item
        if expires_at <= time.time():
            self._store.pop(cache_key, None)
            return None
        self._store.move_to_end(cache_key)
        return payload

    def set(self, cache_key: str, payload: Dict, ttl: int) -> None:
        self._store[cache_key] = (time.time() + ttl, payload)
        self._store.move_to_end(cache_key)
        while len(self._store) > self.max_items:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


history_local_cache = HistoryLocalCache()
_HISTORY_LOCAL_CACHE = history_local_cache
_PRICE_CACHE_SCHEMA_VERSION = "v2"


def parse_interval(interval: Optional[str]) -> Optional[str]:
    if not interval:
        return None
    match = re.match(r"^(\d+)([mhd])$", interval.strip().lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    mapping = {"m": "min", "h": "h", "d": "D"}
    return f"{value}{mapping[unit]}"


def downsample_history(items: List[Dict], interval: Optional[str]) -> List[Dict]:
    if not interval:
        return items
    df = pd.DataFrame(items)
    if df.empty:
        return []
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df.resample(interval).last().dropna()
    return [
        {"timestamp": idx.isoformat(), "price_cny_per_gram": row["price_cny_per_gram"]}
        for idx, row in df.iterrows()
    ]


def _history_cache_key(days: int, interval: Optional[str], latest_timestamp: datetime) -> str:
    interval_token = parse_interval(interval) or interval or "raw"
    return build_cache_key(
        "history",
        "price",
        _PRICE_CACHE_SCHEMA_VERSION,
        str(days),
        interval_token,
        latest_timestamp.isoformat(),
    )


@router.get(
    "/current",
    summary="Get current gold price",
    description="Return the latest persisted gold price and source count.",
)
def get_current_price():
    with get_db_session(read_only=True) as session:
        latest = (
            session.query(
                PriceHistory.timestamp,
                PriceHistory.price_cny_per_gram,
                PriceHistory.source_count,
            )
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )
        if not latest:
            return error_response(404, "PRICE_NOT_FOUND", "No price data", "No price data")
        timestamp, price_cny_per_gram, source_count = latest
        return {
            "timestamp": timestamp.isoformat(),
            "price_cny_per_gram": price_cny_per_gram,
            "source_count": source_count,
        }


@router.get(
    "/sources/latest",
    summary="Get latest source quality snapshot",
    description="Return the latest persisted source breakdown and a credibility summary for the current price.",
)
def get_latest_price_sources():
    with get_db_session(read_only=True) as session:
        latest = (
            session.query(
                PriceHistory.id,
                PriceHistory.timestamp,
                PriceHistory.price_cny_per_gram,
                PriceHistory.source_count,
            )
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )
        if not latest:
            return error_response(404, "PRICE_NOT_FOUND", "No price data", "No price data")

        history_id, timestamp, price_cny_per_gram, source_count = latest
        source_rows = (
            session.query(
                PriceSource.source_name,
                PriceSource.price_cny_per_gram,
                PriceSource.is_valid,
            )
            .filter(PriceSource.price_history_id == history_id)
            .order_by(PriceSource.is_valid.desc(), PriceSource.source_name.asc())
            .all()
        )
        health_rows = (
            session.query(PriceSource.source_name, PriceSource.is_valid)
            .order_by(PriceSource.created_at.desc())
            .limit(200)
            .all()
        )

    health_map = build_source_health_map(health_rows)
    sources = [
        build_source_entry(
            source_name=source_name,
            price_cny_per_gram=source_price,
            is_valid=is_valid,
            health=health_map.get(source_name),
        )
        for source_name, source_price, is_valid in source_rows
    ]
    quality = summarize_source_quality(sources)
    aggregation = calculate_consensus_price(sources)
    primary_source = determine_primary_source(sources)

    return {
        "timestamp": timestamp.isoformat(),
        "price_cny_per_gram": price_cny_per_gram,
        "source_count": source_count,
        "quality": quality,
        "primary_source": primary_source,
        "aggregation": aggregation,
        "sources": sources,
    }


@router.get(
    "/diagnostics/latest",
    summary="Get latest source diagnostics",
    description="Return recent source filtering and price-guard diagnostics for the data credibility panel.",
)
def get_latest_price_diagnostics(limit: int = Query(10, ge=1, le=100)):
    with get_db_session(read_only=True) as session:
        records = (
            session.query(
                SourceDiagnostic.timestamp,
                SourceDiagnostic.status,
                SourceDiagnostic.raw_sources,
                SourceDiagnostic.valid_sources,
                SourceDiagnostic.invalid_sources,
                SourceDiagnostic.aggregation,
                SourceDiagnostic.guard_context,
            )
            .order_by(SourceDiagnostic.timestamp.desc(), SourceDiagnostic.id.desc())
            .limit(limit)
            .all()
        )
        rows = [
            {
                "timestamp": timestamp,
                "status": status,
                "raw_sources": raw_sources,
                "valid_sources": valid_sources,
                "invalid_sources": invalid_sources,
                "aggregation": aggregation,
                "guard_context": guard_context,
            }
            for (
                timestamp,
                status,
                raw_sources,
                valid_sources,
                invalid_sources,
                aggregation,
                guard_context,
            ) in records
        ]
    return build_diagnostic_payload(rows)


@router.get(
    "/history",
    summary="Get historical gold prices",
    description="Return historical gold prices with optional downsampling and regime filtering metadata.",
)
def get_price_history(
    days: int = Query(30, ge=1, le=3650),
    interval: Optional[str] = Query(None, description="e.g. 1h, 30m, 1d"),
):
    interval_str = parse_interval(interval)
    if interval and interval_str is None:
        return error_response(400, "INVALID_INTERVAL", "Invalid interval", "Invalid interval")

    with get_db_session(read_only=True) as session:
        latest = (
            session.query(PriceHistory.timestamp)
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )
        if not latest:
            return {"items": []}

        cache_key = _history_cache_key(days, interval_str or interval, latest[0])
        cached_payload = history_local_cache.get(cache_key)
        if cached_payload is not None:
            return cached_payload

        cached_payload = get_json_cache(cache_key)
        if cached_payload is not None:
            history_local_cache.set(cache_key, cached_payload, settings.cache_history_ttl)
            return cached_payload

        start_time = datetime.now() - timedelta(days=days)
        records = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= start_time)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

        items = [
            {
                "timestamp": timestamp,
                "price_cny_per_gram": price_cny_per_gram,
            }
            for timestamp, price_cny_per_gram in records
        ]
        meta = build_regime_meta(
            items,
            price_getter=lambda item: item["price_cny_per_gram"],
            timestamp_getter=lambda item: item["timestamp"],
        )
        items = filter_current_regime(
            items,
            price_getter=lambda item: item["price_cny_per_gram"],
        )
        output = downsample_history(items, interval_str)
        if not interval_str:
            output = [
                {
                    "timestamp": item["timestamp"].isoformat(),
                    "price_cny_per_gram": item["price_cny_per_gram"],
                }
                for item in items
            ]
        response = {"items": output, "meta": meta}
        history_local_cache.set(cache_key, response, settings.cache_history_ttl)
        set_json_cache(cache_key, response, settings.cache_history_ttl)
        return response


@router.get(
    "/candlestick",
    summary="Get OHLC candlestick data",
    description="Aggregate historical prices into OHLC candlesticks for supported intervals.",
)
def get_candlestick_data(
    days: int = Query(7, ge=1, le=365),
    interval: str = Query("1h", description="1h, 4h, 1d"),
):
    """获取K线数据(OHLC格式)"""
    # 验证间隔参数
    valid_intervals = {"1h": "1h", "4h": "4h", "1d": "1D"}
    if interval not in valid_intervals:
        return error_response(
            400,
            "INVALID_INTERVAL",
            "Invalid interval. Use: 1h, 4h, 1d",
            "Invalid interval. Use: 1h, 4h, 1d",
        )

    interval_str = valid_intervals[interval]

    with get_db_session(read_only=True) as session:
        start_time = datetime.now() - timedelta(days=days)
        records = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= start_time)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

        if not records:
            return {"items": []}

        # 转换为 DataFrame
        items = [
            {
                "timestamp": timestamp,
                "price": price,
            }
            for timestamp, price in records
        ]
        meta = build_regime_meta(
            items,
            price_getter=lambda item: item["price"],
            timestamp_getter=lambda item: item["timestamp"],
        )
        items = filter_current_regime(
            items,
            price_getter=lambda item: item["price"],
        )

        df = pd.DataFrame(items)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()

        # 聚合为 OHLC 数据
        ohlc = df.resample(interval_str).agg({
            "price": ["first", "max", "min", "last", "count"]
        }).dropna()

        # 格式化输出
        candlesticks = []
        for idx, row in ohlc.iterrows():
            open_price = row[("price", "first")]
            high_price = row[("price", "max")]
            low_price = row[("price", "min")]
            close_price = row[("price", "last")]
            data_points = int(row[("price", "count")])

            # 计算活跃度 = 价格波动幅度 × 数据点数量
            volatility = (high_price - low_price) / low_price * 100 if low_price > 0 else 0
            activity = volatility * data_points

            candlesticks.append({
                "timestamp": idx.isoformat(),
                "open": float(open_price),
                "high": float(high_price),
                "low": float(low_price),
                "close": float(close_price),
                "activity": float(activity),
                "data_points": data_points,
            })

        return {"items": candlesticks, "meta": meta}
