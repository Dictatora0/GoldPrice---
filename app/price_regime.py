from typing import Callable, Optional, Sequence, TypeVar

from config import settings

T = TypeVar("T")


def _relative_jump(previous_price: float, current_price: float) -> float:
    baseline = min(abs(previous_price), abs(current_price))
    if baseline <= 0:
        return 0.0
    return abs(current_price - previous_price) / baseline


def find_current_regime_start_index(
    items: Sequence[T],
    price_getter: Callable[[T], float],
    threshold: Optional[float] = None,
) -> int:
    if len(items) <= 1:
        return 0

    jump_threshold = (
        settings.price_regime_break_threshold
        if threshold is None
        else threshold
    )

    for idx in range(len(items) - 1, 0, -1):
        previous_price = float(price_getter(items[idx - 1]))
        current_price = float(price_getter(items[idx]))

        if _relative_jump(previous_price, current_price) > jump_threshold:
            return idx

    return 0


def filter_current_regime(
    items: Sequence[T],
    price_getter: Callable[[T], float],
    threshold: Optional[float] = None,
) -> list[T]:
    if not items:
        return []

    start_index = find_current_regime_start_index(items, price_getter, threshold)
    return list(items[start_index:])


def build_regime_meta(
    items: Sequence[T],
    price_getter: Callable[[T], float],
    timestamp_getter: Callable[[T], object],
    threshold: Optional[float] = None,
) -> dict:
    if not items:
        return {
            "regime_filtered": False,
            "requested_points": 0,
            "returned_points": 0,
            "removed_points": 0,
            "regime_start_timestamp": None,
        }

    start_index = find_current_regime_start_index(items, price_getter, threshold)
    filtered = list(items[start_index:])

    return {
        "regime_filtered": start_index > 0,
        "requested_points": len(items),
        "returned_points": len(filtered),
        "removed_points": start_index,
        "regime_start_timestamp": str(timestamp_getter(filtered[0])) if filtered else None,
    }
