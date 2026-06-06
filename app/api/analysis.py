from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from app.analyzers.indicators import IndicatorCalculator
from app.analyzers.advisor import MarketAdvisor
from app.analyzers.signals import SignalDetector
from app.analyzers.performance import (
    DEFAULT_BACKTEST_HORIZONS,
    calculate_signal_backtest,
    calculate_support_resistance,
    parse_horizon_days,
)
from app.analyzers.confidence import (
    calculate_confidence_center,
    parse_confidence_horizons,
)
from app.analyzers.macro import calculate_macro_correlation
from app.analyzers.planning import (
    calculate_multi_timeframe,
    calculate_price_forecast,
    calculate_entry_plan,
)
from app.api.errors import error_response
from app.database import get_db_session
from app.models import AnalysisSignal
from app.cache import cache_manager
from app.signal_validation import decode_signal_indicators, is_complete_signal_payload

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get(
    "/indicators",
    summary="Get technical indicators",
    description="Return the latest cached indicator snapshot.",
)
def get_indicators():
    calculator = IndicatorCalculator()
    indicators = calculator.calculate_all_cached()
    if not indicators:
        return {"status": "insufficient_data", "items": {}}
    # Convert numpy types to native for JSON
    cleaned = {k: (float(v) if v is not None else None) for k, v in indicators.items()}
    return {"status": "ok", "items": cleaned}


@router.get(
    "/signals",
    summary="Get signal history",
    description="Return recent persisted buy-signal records with decoded indicators.",
)
def get_signals(days: int = Query(7, ge=1, le=3650)):
    with get_db_session(read_only=True) as session:
        start_time = datetime.now() - timedelta(days=days)
        records = (
            session.query(
                AnalysisSignal.timestamp,
                AnalysisSignal.signal_type,
                AnalysisSignal.price_cny_per_gram,
                AnalysisSignal.indicators,
                AnalysisSignal.notified,
            )
            .filter(AnalysisSignal.timestamp >= start_time)
            .order_by(AnalysisSignal.timestamp.desc())
            .all()
        )
        items = []
        for timestamp, signal_type, price_cny_per_gram, indicators_raw, notified in records:
            indicators = decode_signal_indicators(indicators_raw)
            if not is_complete_signal_payload(price_cny_per_gram, indicators):
                continue
            items.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "signal_type": signal_type,
                    "price_cny_per_gram": price_cny_per_gram,
                    "indicators": indicators,
                    "notified": notified,
                }
            )
        return {"items": items}


@router.get(
    "/advice",
    summary="Get market advice",
    description="Return the latest consolidated market advice and risk analysis.",
)
def get_advice():
    """获取智能买入建议和市场分析"""
    advisor = MarketAdvisor()
    advice = advisor.analyze_cached()

    if advice is None:
        return error_response(
            503,
            "INSUFFICIENT_DATA",
            "数据积累中,请稍后再试。需要至少90天的历史数据才能提供准确建议。",
            "数据积累中,请稍后再试。需要至少90天的历史数据才能提供准确建议。",
        )

    return {"data": advice}


@router.get(
    "/buy-signal",
    summary="Get buy signal evaluation",
    description="Return the latest cached buy-signal evaluation and debug fields.",
)
def get_buy_signal_evaluation():
    """获取买入信号评估(带缓存)"""
    detector = SignalDetector()
    evaluation = detector.evaluate_buy_signal_cached()

    if evaluation is None:
        return error_response(
            503,
            "INSUFFICIENT_DATA",
            "数据积累中,请稍后再试。",
            "数据积累中,请稍后再试。",
        )

    return {"data": evaluation}


@router.get(
    "/cache/stats",
    summary="Get cache stats",
    description="Return in-process cache hit and miss statistics.",
)
def get_cache_stats():
    """获取缓存统计信息"""
    stats = cache_manager.get_stats()
    return {"data": stats}


@router.get(
    "/signal-performance",
    summary="Get historical signal performance",
    description="Backtest historical buy signals and return win-rate, return and drawdown statistics.",
)
def get_signal_performance(
    window_days: int = Query(180, ge=30, le=3650),
    horizons: str = Query("3,7,30", description="Comma-separated horizon days, e.g. 3,7,30"),
    limit: int = Query(300, ge=20, le=2000),
    high_score_threshold: int = Query(80, ge=50, le=100),
):
    parsed_horizons = parse_horizon_days(horizons)
    if not parsed_horizons:
        parsed_horizons = list(DEFAULT_BACKTEST_HORIZONS)
    stats = calculate_signal_backtest(
        window_days=window_days,
        horizons=parsed_horizons,
        limit=limit,
        high_score_threshold=high_score_threshold,
    )
    return {"data": stats}


@router.get(
    "/confidence-center",
    summary="Get strategy confidence center",
    description="Return strategy health, current advice confidence, risk checks and similar historical signals.",
)
def get_confidence_center(
    window_days: int = Query(180, ge=30, le=3650),
    horizons: str = Query("3,7,30", description="Comma-separated horizon days, e.g. 3,7,30"),
    limit: int = Query(300, ge=20, le=2000),
    high_score_threshold: int = Query(80, ge=50, le=100),
):
    payload = calculate_confidence_center(
        window_days=window_days,
        horizons=parse_confidence_horizons(horizons),
        limit=limit,
        high_score_threshold=high_score_threshold,
    )
    return {"data": payload}


@router.get(
    "/support-resistance",
    summary="Get support and resistance levels",
    description="Detect support/resistance levels from recent history and return nearest key levels.",
)
def get_support_resistance(
    window_days: int = Query(180, ge=30, le=3650),
    pivot_window: int = Query(5, ge=2, le=24),
    max_levels: int = Query(4, ge=1, le=10),
):
    levels = calculate_support_resistance(
        window_days=window_days,
        pivot_window=pivot_window,
        max_levels=max_levels,
    )
    return {"data": levels}


@router.get(
    "/macro-correlation",
    summary="Get USD/global-gold macro correlation",
    description="Analyze domestic vs international gold linkage, premium/discount and USD proxy context.",
)
def get_macro_correlation(
    window_days: int = Query(180, ge=30, le=3650),
    limit: int = Query(2000, ge=200, le=8000),
    include_live_fx: bool = Query(True),
):
    payload = calculate_macro_correlation(
        window_days=window_days,
        limit=limit,
        include_live_fx=include_live_fx,
    )
    return {"data": payload}


@router.get(
    "/multi-timeframe",
    summary="Get multi-timeframe alignment",
    description="Compare daily/weekly/monthly trend alignment to support precise entry timing.",
)
def get_multi_timeframe(
    windows: str = Query("1,7,30", description="Comma-separated day windows, e.g. 1,7,30"),
    lookback_days: int = Query(180, ge=30, le=3650),
):
    parsed = []
    for token in windows.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError:
            continue
        if 1 <= value <= 3650:
            parsed.append(value)
    if not parsed:
        parsed = [1, 7, 30]
    payload = calculate_multi_timeframe(windows=parsed, lookback_days=lookback_days)
    return {"data": payload}


@router.get(
    "/forecast",
    summary="Get short-term price forecast",
    description="Return trend extrapolation and probabilistic forecast range based on recent returns.",
)
def get_price_forecast(
    lookback_days: int = Query(180, ge=30, le=3650),
    horizon_days: int = Query(7, ge=1, le=90),
    simulation_paths: int = Query(400, ge=100, le=5000),
):
    payload = calculate_price_forecast(
        lookback_days=lookback_days,
        horizon_days=horizon_days,
        simulation_paths=simulation_paths,
    )
    return {"data": payload}


@router.get(
    "/entry-plan",
    summary="Get entry plan calculator",
    description="Build staged entry, stop-loss and target plan with risk-reward estimate.",
)
def get_entry_plan(
    budget_cny: Optional[float] = Query(None, ge=0),
    batches: int = Query(3, ge=1, le=10),
    step_pct: float = Query(2.0, ge=0.2, le=20.0),
    target_profit_pct: float = Query(5.0, ge=0.5, le=40.0),
):
    payload = calculate_entry_plan(
        budget_cny=budget_cny,
        batches=batches,
        step_pct=step_pct,
        target_profit_pct=target_profit_pct,
    )
    return {"data": payload}
