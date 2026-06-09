from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

import pandas as pd

from app.database import get_db_session
from app.models import PriceHistory
from app.price_regime import filter_current_regime

PriceSeriesInterval = Literal["raw", "1h", "1d"]


@dataclass(frozen=True)
class PricePoint:
    timestamp: datetime
    price: float


@dataclass(frozen=True)
class PriceSeries:
    points: list[PricePoint]
    interval: PriceSeriesInterval
    basis_interval: PriceSeriesInterval
    sample_count: int
    start_time: Optional[datetime]
    end_time: Optional[datetime]

    def to_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame(
            [{"timestamp": point.timestamp, "price": point.price} for point in self.points]
        )
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        df.attrs["interval"] = self.interval
        df.attrs["basis_interval"] = self.basis_interval
        df.attrs["sample_count"] = self.sample_count
        return df


def _normalize_interval(interval: str) -> PriceSeriesInterval:
    normalized = (interval or "raw").strip().lower()
    if normalized in {"raw", "1h", "1d"}:
        return normalized  # type: ignore[return-value]
    raise ValueError(f"Unsupported price series interval: {interval}")


def _resample_points(points: list[PricePoint], interval: PriceSeriesInterval) -> list[PricePoint]:
    if interval == "raw" or not points:
        return points

    df = pd.DataFrame(
        [{"timestamp": point.timestamp, "price": point.price} for point in points]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    rule = "1h" if interval == "1h" else "1D"
    resampled = (
        df.set_index("timestamp")
        .sort_index()
        .resample(rule)
        .last()
        .dropna()
    )
    return [
        PricePoint(timestamp=idx.to_pydatetime(), price=float(row["price"]))
        for idx, row in resampled.iterrows()
    ]


def load_price_series(
    *,
    lookback_days: int = 180,
    interval: str = "raw",
    limit: Optional[int] = None,
    apply_regime_filter: bool = True,
) -> PriceSeries:
    normalized_interval = _normalize_interval(interval)
    start_time = datetime.now() - timedelta(days=lookback_days)

    with get_db_session(read_only=True) as session:
        query = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= start_time)
            .order_by(PriceHistory.timestamp.asc())
        )
        if limit is not None:
            query = query.limit(limit)
        rows = query.all()

    if apply_regime_filter:
        rows = filter_current_regime(rows, price_getter=lambda row: row[1])

    raw_points = [
        PricePoint(timestamp=timestamp, price=float(price))
        for timestamp, price in rows
        if price is not None and float(price) > 0
    ]
    points = _resample_points(raw_points, normalized_interval)

    return PriceSeries(
        points=points,
        interval=normalized_interval,
        basis_interval=normalized_interval,
        sample_count=len(points),
        start_time=points[0].timestamp if points else None,
        end_time=points[-1].timestamp if points else None,
    )
