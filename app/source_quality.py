from __future__ import annotations

from collections import defaultdict
from statistics import mean, median
from typing import Any, Optional


SOURCE_PROFILES: dict[str, dict[str, Any]] = {
    "sge_official": {
        "display_name": "SGE 官网延时行情",
        "kind": "exchange_official_delayed",
        "trust_tier": "high",
        "trust_score": 0.97,
        "is_backup": False,
    },
    "gold_cn": {
        "display_name": "SGE 延迟行情",
        "kind": "exchange_delayed",
        "trust_tier": "high",
        "trust_score": 0.92,
        "is_backup": False,
    },
    "sina": {
        "display_name": "新浪财经",
        "kind": "market_portal",
        "trust_tier": "medium",
        "trust_score": 0.78,
        "is_backup": False,
    },
    "eastmoney": {
        "display_name": "东方财富",
        "kind": "market_portal",
        "trust_tier": "medium",
        "trust_score": 0.8,
        "is_backup": False,
    },
    "global_gold": {
        "display_name": "国际金价换算",
        "kind": "derived_backup",
        "trust_tier": "low",
        "trust_score": 0.58,
        "is_backup": True,
    },
}

DEFAULT_SOURCE_PROFILE = {
    "display_name": "未知来源",
    "kind": "unknown",
    "trust_tier": "low",
    "trust_score": 0.5,
    "is_backup": True,
}


def get_source_profile(source_name: str) -> dict[str, Any]:
    profile = SOURCE_PROFILES.get(source_name, DEFAULT_SOURCE_PROFILE)
    return {
        "name": source_name,
        "display_name": profile["display_name"],
        "kind": profile["kind"],
        "trust_tier": profile["trust_tier"],
        "trust_score": float(profile["trust_score"]),
        "is_backup": bool(profile["is_backup"]),
    }


def build_source_entry(
    *,
    source_name: str,
    price_cny_per_gram: float,
    is_valid: bool,
    health: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    profile = get_source_profile(source_name)
    return {
        **profile,
        "price_cny_per_gram": round(float(price_cny_per_gram), 2),
        "is_valid": bool(is_valid),
        "health": health or {},
    }


def _round_optional(value: Optional[float], digits: int = 3) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def summarize_source_quality(source_entries: list[dict[str, Any]]) -> dict[str, Any]:
    valid_entries = [item for item in source_entries if item.get("is_valid")]
    invalid_entries = [item for item in source_entries if not item.get("is_valid")]
    trusted_valid_entries = [
        item for item in valid_entries if item.get("trust_tier") == "high" and not item.get("is_backup")
    ]
    backup_valid_entries = [item for item in valid_entries if item.get("is_backup")]

    valid_prices = [float(item["price_cny_per_gram"]) for item in valid_entries]
    spread_pct = None
    if len(valid_prices) >= 2:
        median_price = median(valid_prices)
        if median_price > 0:
            spread_pct = (max(valid_prices) - min(valid_prices)) / median_price * 100

    avg_trust_score = mean(item["trust_score"] for item in valid_entries) if valid_entries else 0.0
    avg_valid_rate = mean(
        item.get("health", {}).get("recent_valid_rate_pct", 100.0) for item in valid_entries
    ) if valid_entries else 0.0
    confidence_score = int(round(avg_trust_score * 100))
    confidence_score += min(len(valid_entries), 4) * 4
    if trusted_valid_entries:
        confidence_score += 8
    else:
        confidence_score -= 14
    if len(valid_entries) == 1:
        confidence_score -= 18
    elif len(valid_entries) == 2:
        confidence_score -= 8
    if invalid_entries:
        confidence_score -= min(12, len(invalid_entries) * 6)
    if len(valid_entries) == len(backup_valid_entries) and valid_entries:
        confidence_score -= 15
    if spread_pct is not None:
        if spread_pct <= 0.2:
            confidence_score += 6
        elif spread_pct <= 0.6:
            confidence_score += 0
        elif spread_pct <= 1.2:
            confidence_score -= 10
        else:
            confidence_score -= 22
    if avg_valid_rate:
        if avg_valid_rate >= 90:
            confidence_score += 4
        elif avg_valid_rate >= 75:
            confidence_score += 0
        elif avg_valid_rate >= 60:
            confidence_score -= 8
        else:
            confidence_score -= 16

    confidence_score = max(0, min(100, confidence_score))

    if confidence_score >= 80:
        confidence_level = "high"
    elif confidence_score >= 60:
        confidence_level = "medium"
    else:
        confidence_level = "low"

    if spread_pct is None:
        consensus = "insufficient"
    elif spread_pct <= 0.2:
        consensus = "tight"
    elif spread_pct <= 0.8:
        consensus = "normal"
    else:
        consensus = "wide"

    summary = (
        f"{len(valid_entries)} 个有效源，{len(trusted_valid_entries)} 个高可信源，"
        f"价差离散 {spread_pct:.2f}%"
        if spread_pct is not None
        else f"{len(valid_entries)} 个有效源，当前样本不足以判断离散度"
    )

    return {
        "confidence_level": confidence_level,
        "confidence_score": confidence_score,
        "valid_source_count": len(valid_entries),
        "invalid_source_count": len(invalid_entries),
        "trusted_valid_source_count": len(trusted_valid_entries),
        "backup_source_count": len(backup_valid_entries),
        "avg_recent_valid_rate_pct": _round_optional(avg_valid_rate, 2),
        "spread_pct": _round_optional(spread_pct, 3),
        "consensus": consensus,
        "summary": summary,
    }


def build_source_health_map(
    rows: list[tuple[str, bool]],
    *,
    per_source_limit: int = 20,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for source_name, is_valid in rows:
        if len(grouped[source_name]) >= per_source_limit:
            continue
        grouped[source_name].append(bool(is_valid))

    health_map: dict[str, dict[str, Any]] = {}
    for source_name, samples in grouped.items():
        sample_count = len(samples)
        valid_count = sum(1 for item in samples if item)
        valid_rate_pct = valid_count / sample_count * 100 if sample_count else 0.0
        if valid_rate_pct >= 90:
            status = "healthy"
        elif valid_rate_pct >= 65:
            status = "watch"
        else:
            status = "degraded"
        health_map[source_name] = {
            "sample_count": sample_count,
            "recent_valid_rate_pct": _round_optional(valid_rate_pct, 2),
            "status": status,
            "last_is_valid": bool(samples[0]) if samples else None,
        }
    return health_map


def calculate_effective_weight(entry: dict[str, Any]) -> float:
    trust_score = float(entry.get("trust_score", 0.5))
    health = entry.get("health", {}) or {}
    valid_rate_pct = health.get("recent_valid_rate_pct")
    health_factor = 1.0
    if valid_rate_pct is not None:
        health_factor = max(0.35, min(1.0, float(valid_rate_pct) / 100))
    if entry.get("is_backup"):
        health_factor *= 0.8
    return round(trust_score * health_factor, 4)


def determine_primary_source(source_entries: list[dict[str, Any]]) -> dict[str, Any]:
    valid_primary_entries = [
        item
        for item in source_entries
        if item.get("is_valid") and item.get("trust_tier") == "high" and not item.get("is_backup")
    ]
    preferred_entry = next((item for item in valid_primary_entries if item.get("name") == "sge_official"), None)
    primary_entry = preferred_entry or (valid_primary_entries[0] if valid_primary_entries else None)

    if not primary_entry:
        return {
            "name": None,
            "display_name": "主源缺席",
            "status": "missing",
            "trust_tier": None,
            "kind": None,
        }

    return {
        "name": primary_entry.get("name"),
        "display_name": primary_entry.get("display_name") or primary_entry.get("name"),
        "status": "available",
        "trust_tier": primary_entry.get("trust_tier"),
        "kind": primary_entry.get("kind"),
    }


def calculate_consensus_price(source_entries: list[dict[str, Any]]) -> dict[str, Any]:
    valid_entries = [item for item in source_entries if item.get("is_valid")]
    if not valid_entries:
        return {"price_cny_per_gram": None, "method": "unavailable"}

    valid_prices = [float(item["price_cny_per_gram"]) for item in valid_entries]
    spread_pct = None
    if len(valid_prices) >= 2:
        median_price = median(valid_prices)
        if median_price > 0:
            spread_pct = (max(valid_prices) - min(valid_prices)) / median_price * 100

    primary_trusted_entries = [
        item
        for item in valid_entries
        if item.get("trust_tier") == "high" and not item.get("is_backup")
    ]
    if len(primary_trusted_entries) >= 1 and spread_pct is not None and spread_pct <= 0.3:
        trusted_prices = [float(item["price_cny_per_gram"]) for item in primary_trusted_entries]
        trusted_anchor = median(trusted_prices)
        return {
            "price_cny_per_gram": round(trusted_anchor, 2),
            "method": "primary_trusted_anchor",
            "contributors": [
                {
                    "name": item["name"],
                    "weight": calculate_effective_weight(item),
                }
                for item in primary_trusted_entries
            ],
        }
    aggregation_method = "weighted_trust_mean" if primary_trusted_entries else "secondary_weighted"

    weighted_sum = 0.0
    total_weight = 0.0
    contributors = []
    for entry in valid_entries:
        weight = calculate_effective_weight(entry)
        weighted_sum += float(entry["price_cny_per_gram"]) * weight
        total_weight += weight
        contributors.append({"name": entry["name"], "weight": weight})

    if total_weight <= 0:
        avg_price = mean(float(item["price_cny_per_gram"]) for item in valid_entries)
        return {
            "price_cny_per_gram": round(avg_price, 2),
            "method": "fallback_mean",
            "contributors": contributors,
        }

    return {
        "price_cny_per_gram": round(weighted_sum / total_weight, 2),
        "method": aggregation_method,
        "contributors": contributors,
    }
