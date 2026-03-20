import json
from typing import Any, Dict


REQUIRED_SIGNAL_FIELDS = {
    "current_price",
    "evaluation_score",
    "evaluation_reasons",
    "momentum",
    "timeframe_analysis",
}


def decode_signal_indicators(indicators_raw: Any) -> Dict[str, Any]:
    if not indicators_raw:
        return {}

    if isinstance(indicators_raw, dict):
        return indicators_raw

    if isinstance(indicators_raw, str):
        try:
            parsed = json.loads(indicators_raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    return {}


def is_complete_signal_payload(price_cny_per_gram: float, indicators: Dict[str, Any]) -> bool:
    if not isinstance(indicators, dict):
        return False

    if not REQUIRED_SIGNAL_FIELDS.issubset(indicators):
        return False

    try:
        current_price = float(indicators["current_price"])
        evaluation_score = float(indicators["evaluation_score"])
        signal_price = float(price_cny_per_gram)
    except (TypeError, ValueError):
        return False

    if abs(current_price - signal_price) > 0.01:
        return False

    if evaluation_score < 0:
        return False

    if not isinstance(indicators["evaluation_reasons"], list):
        return False

    if not isinstance(indicators["momentum"], dict):
        return False

    if not isinstance(indicators["timeframe_analysis"], dict):
        return False

    return True
