import bisect
import json
from datetime import datetime, timedelta
from typing import Dict, Optional

import numpy as np
from sklearn.linear_model import LogisticRegression

from app.database import get_db_session
from app.models import AnalysisSignal, PriceHistory


_MODEL_CACHE: dict = {
    "as_of": None,
    "model": None,
    "samples": 0,
    "expires_at": None,
}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _alignment_to_number(alignment: Optional[str]) -> float:
    if alignment == "bullish_aligned":
        return 1.0
    if alignment == "bearish_aligned":
        return -1.0
    return 0.0


def _extract_features_from_payload(indicators: Dict) -> list[float]:
    setup_flags = indicators.get("setup_flags", []) or []
    confirmation_flags = indicators.get("confirmation_flags", []) or []
    risk_flags = indicators.get("risk_flags", []) or []
    momentum = indicators.get("momentum", {}) or {}
    timeframe = indicators.get("timeframe_analysis", {}) or indicators.get("timeframe", {}) or {}

    return [
        len(setup_flags),
        len(confirmation_flags),
        1.0 if indicators.get("entry_ready") else 0.0,
        1.0 if "falling_knife" in risk_flags else 0.0,
        _safe_float(indicators.get("rsi"), 50.0),
        _safe_float(indicators.get("macd_histogram"), 0.0),
        _safe_float(indicators.get("volatility"), 2.0),
        _safe_float(momentum.get("change_pct"), 0.0),
        _safe_float(momentum.get("acceleration"), 0.0),
        _alignment_to_number(timeframe.get("alignment")),
    ]


def _build_training_samples(
    *,
    horizon_minutes: int = 120,
    max_signals: int = 800,
) -> tuple[list[list[float]], list[int]]:
    with get_db_session(read_only=True) as session:
        signals = (
            session.query(
                AnalysisSignal.timestamp,
                AnalysisSignal.price_cny_per_gram,
                AnalysisSignal.indicators,
            )
            .filter(AnalysisSignal.signal_type == "buy")
            .order_by(AnalysisSignal.timestamp.desc())
            .limit(max_signals)
            .all()
        )
        if not signals:
            return [], []

        signals = list(reversed(signals))
        min_target = signals[0][0] + timedelta(minutes=horizon_minutes)
        price_rows = (
            session.query(PriceHistory.timestamp, PriceHistory.price_cny_per_gram)
            .filter(PriceHistory.timestamp >= min_target)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

    if not price_rows:
        return [], []

    price_timestamps = [row[0] for row in price_rows]
    price_values = [row[1] for row in price_rows]

    features: list[list[float]] = []
    labels: list[int] = []

    for signal_timestamp, signal_price, indicators_raw in signals:
        if signal_price is None:
            continue
        target_time = signal_timestamp + timedelta(minutes=horizon_minutes)
        idx = bisect.bisect_left(price_timestamps, target_time)
        if idx >= len(price_values):
            continue

        future_price = price_values[idx]
        if future_price is None:
            continue

        future_return = (future_price - signal_price) / signal_price
        label = 1 if future_return > 0 else 0

        indicators = {}
        if indicators_raw:
            try:
                indicators = json.loads(indicators_raw)
            except json.JSONDecodeError:
                indicators = {}

        feature_row = _extract_features_from_payload(indicators if isinstance(indicators, dict) else {})
        features.append(feature_row)
        labels.append(label)

    return features, labels


def _train_logistic_model() -> tuple[Optional[LogisticRegression], int]:
    features, labels = _build_training_samples()
    if len(features) < 60:
        return None, len(features)
    if len(set(labels)) < 2:
        return None, len(features)

    model = LogisticRegression(
        max_iter=800,
        class_weight="balanced",
        solver="lbfgs",
    )
    model.fit(np.asarray(features), np.asarray(labels))
    return model, len(features)


def _get_latest_signal_timestamp() -> Optional[datetime]:
    with get_db_session(read_only=True) as session:
        latest = session.query(AnalysisSignal.timestamp).order_by(AnalysisSignal.timestamp.desc()).first()
    return latest[0] if latest else None


def _get_cached_model() -> tuple[Optional[LogisticRegression], int]:
    now = datetime.now()
    latest_ts = _get_latest_signal_timestamp()

    if (
        _MODEL_CACHE.get("model") is not None
        and _MODEL_CACHE.get("as_of") == latest_ts
        and _MODEL_CACHE.get("expires_at") is not None
        and _MODEL_CACHE.get("expires_at") > now
    ):
        return _MODEL_CACHE["model"], int(_MODEL_CACHE.get("samples", 0))

    model, sample_count = _train_logistic_model()
    _MODEL_CACHE["model"] = model
    _MODEL_CACHE["samples"] = sample_count
    _MODEL_CACHE["as_of"] = latest_ts
    _MODEL_CACHE["expires_at"] = now + timedelta(minutes=10)
    return model, sample_count


def predict_upside_probability(feature_payload: Dict, fallback_probability: float) -> tuple[float, str, int]:
    try:
        model, sample_count = _get_cached_model()
    except Exception:
        return fallback_probability, "heuristic", 0

    if model is None:
        return fallback_probability, "heuristic", sample_count

    try:
        vector = np.asarray([_extract_features_from_payload(feature_payload)])
        probability = float(model.predict_proba(vector)[0][1])
    except Exception:
        return fallback_probability, "heuristic", sample_count

    return probability, "logistic_regression", sample_count
