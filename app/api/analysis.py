from datetime import datetime, timedelta

from fastapi import APIRouter, Query, HTTPException

from app.analyzers.indicators import IndicatorCalculator
from app.analyzers.advisor import MarketAdvisor
from app.analyzers.signals import SignalDetector
from app.database import get_db_session
from app.models import AnalysisSignal
from app.cache import cache_manager
from app.signal_validation import decode_signal_indicators, is_complete_signal_payload

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/indicators")
def get_indicators():
    calculator = IndicatorCalculator()
    indicators = calculator.calculate_all_cached()
    if not indicators:
        return {"status": "insufficient_data", "items": {}}
    # Convert numpy types to native for JSON
    cleaned = {k: (float(v) if v is not None else None) for k, v in indicators.items()}
    return {"status": "ok", "items": cleaned}


@router.get("/signals")
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


@router.get("/advice")
def get_advice():
    """获取智能买入建议和市场分析"""
    advisor = MarketAdvisor()
    advice = advisor.analyze_cached()

    if advice is None:
        raise HTTPException(
            status_code=503,
            detail="数据积累中,请稍后再试。需要至少90天的历史数据才能提供准确建议。"
        )

    return {"data": advice}


@router.get("/buy-signal")
def get_buy_signal_evaluation():
    """获取买入信号评估(带缓存)"""
    detector = SignalDetector()
    evaluation = detector.evaluate_buy_signal_cached()

    if evaluation is None:
        raise HTTPException(
            status_code=503,
            detail="数据积累中,请稍后再试。"
        )

    return {"data": evaluation}


@router.get("/cache/stats")
def get_cache_stats():
    """获取缓存统计信息"""
    stats = cache_manager.get_stats()
    return {"data": stats}
