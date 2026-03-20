import json
from datetime import datetime, timedelta
import time
import re
from collections import OrderedDict
from typing import Optional, List, Dict

import pandas as pd
from fastapi import APIRouter, Query, HTTPException

from app.cache import cache_manager
from app.database import get_db_session
from app.models import PriceHistory
from app.price_regime import build_regime_meta, filter_current_regime
from config import settings

router = APIRouter(prefix="/api/price", tags=["price"])

_HISTORY_LOCAL_CACHE: OrderedDict[str, tuple[float, Dict]] = OrderedDict()
_HISTORY_LOCAL_CACHE_MAX_ITEMS = 256
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
    return (
        f"price:history:{_PRICE_CACHE_SCHEMA_VERSION}:"
        f"{days}:{interval_token}:{latest_timestamp.isoformat()}"
    )


def _get_local_history_cache(cache_key: str) -> Optional[Dict]:
    item = _HISTORY_LOCAL_CACHE.get(cache_key)
    if not item:
        return None

    expires_at, payload = item
    if expires_at <= time.time():
        _HISTORY_LOCAL_CACHE.pop(cache_key, None)
        return None

    _HISTORY_LOCAL_CACHE.move_to_end(cache_key)
    return payload


def _set_local_history_cache(cache_key: str, payload: Dict, ttl: int):
    _HISTORY_LOCAL_CACHE[cache_key] = (time.time() + ttl, payload)
    _HISTORY_LOCAL_CACHE.move_to_end(cache_key)

    while len(_HISTORY_LOCAL_CACHE) > _HISTORY_LOCAL_CACHE_MAX_ITEMS:
        _HISTORY_LOCAL_CACHE.popitem(last=False)


def _decode_cached_payload(cached: Optional[str]) -> Optional[Dict]:
    if not cached:
        return None
    if isinstance(cached, str):
        try:
            payload = json.loads(cached)
        except json.JSONDecodeError:
            return None
    elif isinstance(cached, dict):
        payload = cached
    else:
        return None

    if isinstance(payload, dict) and "items" in payload:
        return payload
    return None


@router.get("/current")
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
            raise HTTPException(status_code=404, detail="No price data")
        timestamp, price_cny_per_gram, source_count = latest
        return {
            "timestamp": timestamp.isoformat(),
            "price_cny_per_gram": price_cny_per_gram,
            "source_count": source_count,
        }


@router.get("/history")
def get_price_history(
    days: int = Query(30, ge=1, le=3650),
    interval: Optional[str] = Query(None, description="e.g. 1h, 30m, 1d"),
):
    interval_str = parse_interval(interval)
    if interval and interval_str is None:
        raise HTTPException(status_code=400, detail="Invalid interval")

    with get_db_session(read_only=True) as session:
        latest = (
            session.query(PriceHistory.timestamp)
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )
        if not latest:
            return {"items": []}

        cache_key = _history_cache_key(days, interval_str or interval, latest[0])
        cached_payload = _get_local_history_cache(cache_key)
        if cached_payload is not None:
            return cached_payload

        cached_payload = _decode_cached_payload(cache_manager.get(cache_key))
        if cached_payload is not None:
            _set_local_history_cache(cache_key, cached_payload, settings.cache_history_ttl)
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
        _set_local_history_cache(cache_key, response, settings.cache_history_ttl)
        cache_manager.set(
            cache_key,
            json.dumps(response, default=str),
            ttl=settings.cache_history_ttl,
        )
        return response


@router.get("/candlestick")
def get_candlestick_data(
    days: int = Query(7, ge=1, le=365),
    interval: str = Query("1h", description="1h, 4h, 1d"),
):
    """获取K线数据(OHLC格式)"""
    # 验证间隔参数
    valid_intervals = {"1h": "1h", "4h": "4h", "1d": "1D"}
    if interval not in valid_intervals:
        raise HTTPException(status_code=400, detail="Invalid interval. Use: 1h, 4h, 1d")

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
