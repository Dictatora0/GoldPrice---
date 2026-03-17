from datetime import datetime, timedelta
import re
from typing import Optional, List, Dict

import pandas as pd
from fastapi import APIRouter, Query, HTTPException

from app.database import get_db_session
from app.models import PriceHistory

router = APIRouter(prefix="/api/price", tags=["price"])


def parse_interval(interval: Optional[str]) -> Optional[str]:
    if not interval:
        return None
    match = re.match(r"^(\d+)([mhd])$", interval.strip().lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    mapping = {"m": "min", "h": "H", "d": "D"}
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


@router.get("/current")
def get_current_price():
    with get_db_session() as session:
        latest = (
            session.query(PriceHistory)
            .order_by(PriceHistory.timestamp.desc())
            .first()
        )
        if not latest:
            raise HTTPException(status_code=404, detail="No price data")
        return {
            "timestamp": latest.timestamp.isoformat(),
            "price_cny_per_gram": latest.price_cny_per_gram,
            "source_count": latest.source_count,
        }


@router.get("/history")
def get_price_history(
    days: int = Query(30, ge=1, le=3650),
    interval: Optional[str] = Query(None, description="e.g. 1h, 30m, 1d"),
):
    interval_str = parse_interval(interval)
    if interval and interval_str is None:
        raise HTTPException(status_code=400, detail="Invalid interval")

    with get_db_session() as session:
        start_time = datetime.now() - timedelta(days=days)
        records = (
            session.query(PriceHistory)
            .filter(PriceHistory.timestamp >= start_time)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

        items = [
            {
                "timestamp": r.timestamp,
                "price_cny_per_gram": r.price_cny_per_gram,
            }
            for r in records
        ]
        output = downsample_history(items, interval_str)
        if not interval_str:
            output = [
                {
                    "timestamp": item["timestamp"].isoformat(),
                    "price_cny_per_gram": item["price_cny_per_gram"],
                }
                for item in items
            ]
        return {"items": output}


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

    with get_db_session() as session:
        start_time = datetime.now() - timedelta(days=days)
        records = (
            session.query(PriceHistory)
            .filter(PriceHistory.timestamp >= start_time)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

        if not records:
            return {"items": []}

        # 转换为 DataFrame
        items = [
            {
                "timestamp": r.timestamp,
                "price": r.price_cny_per_gram,
            }
            for r in records
        ]

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

        return {"items": candlesticks}
