from __future__ import annotations

import re
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Optional

import requests

from app.collectors.global_gold import GlobalGoldCollector
from app.database import get_db_session
from app.logging_config import get_logger
from app.models import PriceHistory, PriceSource

logger = get_logger(__name__)

FX_USDCNY_URL = "https://hq.sinajs.cn/list=fx_susdcny"


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_optional(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _pearson_correlation(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None

    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = sum((x - mean_x) ** 2 for x in xs)
    denom_y = sum((y - mean_y) ** 2 for y in ys)
    denominator = (denom_x * denom_y) ** 0.5
    if denominator == 0:
        return None
    return numerator / denominator


def _calculate_pct_returns(values: list[float]) -> list[float]:
    returns: list[float] = []
    for idx in range(1, len(values)):
        previous = values[idx - 1]
        current = values[idx]
        if previous > 0:
            returns.append((current - previous) / previous * 100)
    return returns


def _extract_quoted_fields(payload: str) -> list[str]:
    match = re.search(r'="([^"]+)"', payload)
    if not match:
        return []
    return [item.strip() for item in match.group(1).split(",")]


def fetch_usdcny_snapshot(timeout: float = 3.5) -> dict[str, Any]:
    """
    获取 USDCNY 即期快照。
    这里使用新浪公开行情接口，失败时只返回空值，不阻断主流程。
    """
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn",
    }
    try:
        response = requests.get(FX_USDCNY_URL, headers=headers, timeout=timeout)
        response.raise_for_status()
        response.encoding = "gbk"
        payload = response.text
        fields = _extract_quoted_fields(payload)

        close = _safe_float(fields[8]) if len(fields) > 8 else None
        previous = _safe_float(fields[3]) if len(fields) > 3 else None

        if close is None:
            close = GlobalGoldCollector.extract_usdcny_rate(payload)
        if previous is not None and previous <= 0:
            previous = None

        change_pct = None
        if close is not None and previous is not None and previous > 0:
            change_pct = (close - previous) / previous * 100

        return {
            "pair": "USDCNY",
            "name": fields[9] if len(fields) > 9 else "USDCNY 即期汇率",
            "time": fields[0] if fields else None,
            "close": _round_optional(close, 4),
            "previous_close": _round_optional(previous, 4),
            "change_pct": _round_optional(change_pct, 4),
            "source": "sina",
        }
    except Exception as exc:
        logger.warning("Failed to fetch USDCNY snapshot: %s", exc)
        return {
            "pair": "USDCNY",
            "name": "USDCNY 即期汇率",
            "time": None,
            "close": None,
            "previous_close": None,
            "change_pct": None,
            "source": "sina",
            "error": str(exc),
        }


def _build_macro_hint(
    *,
    premium_pct: Optional[float],
    domestic_global_corr: Optional[float],
    usd_change_pct: Optional[float],
) -> str:
    usd_clause = "美元方向暂不明确。"
    if usd_change_pct is not None:
        if usd_change_pct <= -0.2:
            usd_clause = "美元走弱（USDCNY 回落），通常利好黄金。"
        elif usd_change_pct >= 0.2:
            usd_clause = "美元走强（USDCNY 走高），通常压制黄金。"
        else:
            usd_clause = "美元波动有限，对黄金边际影响中性。"

    spread_clause = "内外盘价差数据有限。"
    if premium_pct is not None:
        if premium_pct >= 1.2:
            spread_clause = "内盘对外盘溢价偏高，短线追高需谨慎。"
        elif premium_pct <= -0.8:
            spread_clause = "内盘相对外盘贴水，若基本面稳定可关注修复。"
        else:
            spread_clause = "内外盘价差在常态区间。"

    corr_clause = "内外盘联动性待观察。"
    if domestic_global_corr is not None:
        if domestic_global_corr >= 0.85:
            corr_clause = "内外盘联动性强，宏观驱动有效。"
        elif domestic_global_corr >= 0.6:
            corr_clause = "内外盘联动性中等，需结合本地供需判断。"
        else:
            corr_clause = "内外盘联动性较弱，短期更多受本地因素影响。"

    return f"{usd_clause}{spread_clause}{corr_clause}"


def calculate_macro_correlation(
    *,
    window_days: int = 180,
    limit: int = 2000,
    include_live_fx: bool = True,
) -> dict[str, Any]:
    start_window = datetime.now() - timedelta(days=window_days)

    with get_db_session(read_only=True) as session:
        rows = (
            session.query(
                PriceHistory.timestamp,
                PriceHistory.price_cny_per_gram,
                PriceSource.price_cny_per_gram,
            )
            .join(PriceSource, PriceSource.price_history_id == PriceHistory.id)
            .filter(PriceHistory.timestamp >= start_window)
            .filter(PriceSource.source_name == "global_gold")
            .filter(PriceSource.is_valid.is_(True))
            .order_by(PriceHistory.timestamp.desc())
            .limit(limit)
            .all()
        )

        if not rows:
            rows = (
                session.query(
                    PriceHistory.timestamp,
                    PriceHistory.price_cny_per_gram,
                    PriceSource.price_cny_per_gram,
                )
                .join(PriceSource, PriceSource.price_history_id == PriceHistory.id)
                .filter(PriceHistory.timestamp >= start_window)
                .filter(PriceSource.source_name == "global_gold")
                .order_by(PriceHistory.timestamp.desc())
                .limit(limit)
                .all()
            )

    rows = list(reversed(rows))
    if not rows:
        usd_snapshot = fetch_usdcny_snapshot() if include_live_fx else {
            "pair": "USDCNY",
            "name": "USDCNY 即期汇率",
            "time": None,
            "close": None,
            "previous_close": None,
            "change_pct": None,
            "source": "disabled",
        }
        return {
            "window_days": window_days,
            "sample_count": 0,
            "domestic_latest_cny_per_gram": None,
            "global_latest_cny_per_gram": None,
            "premium_cny_per_gram": None,
            "premium_pct": None,
            "premium_avg_cny_per_gram": None,
            "premium_min_cny_per_gram": None,
            "premium_max_cny_per_gram": None,
            "domestic_global_corr": None,
            "domestic_global_return_corr": None,
            "correlation_basis": "return_pct",
            "usd_proxy": usd_snapshot,
            "macro_hint": "样本不足，暂无法形成美元/国际金价联动判断。",
            "recent_points": [],
            "generated_at": datetime.now().isoformat(),
        }

    points: list[dict[str, Any]] = []
    domestic_prices: list[float] = []
    global_prices: list[float] = []
    premium_values: list[float] = []

    for timestamp, domestic_raw, global_raw in rows:
        domestic = _safe_float(domestic_raw)
        global_price = _safe_float(global_raw)
        if domestic is None or global_price is None or domestic <= 0 or global_price <= 0:
            continue
        premium = domestic - global_price
        premium_pct = premium / global_price * 100
        points.append(
            {
                "timestamp": timestamp.isoformat(),
                "domestic_cny_per_gram": round(domestic, 3),
                "global_cny_per_gram": round(global_price, 3),
                "premium_cny_per_gram": round(premium, 3),
                "premium_pct": _round_optional(premium_pct, 3),
            }
        )
        domestic_prices.append(domestic)
        global_prices.append(global_price)
        premium_values.append(premium)

    if not points:
        return {
            "window_days": window_days,
            "sample_count": 0,
            "domestic_latest_cny_per_gram": None,
            "global_latest_cny_per_gram": None,
            "premium_cny_per_gram": None,
            "premium_pct": None,
            "premium_avg_cny_per_gram": None,
            "premium_min_cny_per_gram": None,
            "premium_max_cny_per_gram": None,
            "domestic_global_corr": None,
            "domestic_global_return_corr": None,
            "correlation_basis": "return_pct",
            "usd_proxy": fetch_usdcny_snapshot() if include_live_fx else None,
            "macro_hint": "样本不足，暂无法形成美元/国际金价联动判断。",
            "recent_points": [],
            "generated_at": datetime.now().isoformat(),
        }

    latest = points[-1]
    domestic_global_corr = _pearson_correlation(domestic_prices, global_prices)
    domestic_returns = _calculate_pct_returns(domestic_prices)
    global_returns = _calculate_pct_returns(global_prices)
    domestic_global_return_corr = _pearson_correlation(domestic_returns, global_returns)
    usd_snapshot = fetch_usdcny_snapshot() if include_live_fx else {
        "pair": "USDCNY",
        "name": "USDCNY 即期汇率",
        "time": None,
        "close": None,
        "previous_close": None,
        "change_pct": None,
        "source": "disabled",
    }

    hint = _build_macro_hint(
        premium_pct=latest.get("premium_pct"),
        domestic_global_corr=domestic_global_return_corr,
        usd_change_pct=usd_snapshot.get("change_pct"),
    )

    return {
        "window_days": window_days,
        "sample_count": len(points),
        "domestic_latest_cny_per_gram": latest["domestic_cny_per_gram"],
        "global_latest_cny_per_gram": latest["global_cny_per_gram"],
        "premium_cny_per_gram": latest["premium_cny_per_gram"],
        "premium_pct": latest["premium_pct"],
        "premium_avg_cny_per_gram": _round_optional(mean(premium_values), 3),
        "premium_min_cny_per_gram": _round_optional(min(premium_values), 3),
        "premium_max_cny_per_gram": _round_optional(max(premium_values), 3),
        "domestic_global_corr": _round_optional(domestic_global_corr, 4),
        "domestic_global_return_corr": _round_optional(domestic_global_return_corr, 4),
        "correlation_basis": "return_pct",
        "usd_proxy": usd_snapshot,
        "macro_hint": hint,
        "recent_points": points[-120:],
        "generated_at": datetime.now().isoformat(),
    }
