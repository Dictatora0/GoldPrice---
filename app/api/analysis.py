import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query, HTTPException

from app.analyzers.indicators import IndicatorCalculator
from app.analyzers.advisor import MarketAdvisor
from app.database import get_session
from app.models import AnalysisSignal

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/indicators")
def get_indicators():
    calculator = IndicatorCalculator()
    indicators = calculator.calculate_all()
    if not indicators:
        return {"status": "insufficient_data", "items": {}}
    # Convert numpy types to native for JSON
    cleaned = {k: (float(v) if v is not None else None) for k, v in indicators.items()}
    return {"status": "ok", "items": cleaned}


@router.get("/signals")
def get_signals(days: int = Query(7, ge=1, le=3650)):
    session = get_session()
    try:
        start_time = datetime.now() - timedelta(days=days)
        records = (
            session.query(AnalysisSignal)
            .filter(AnalysisSignal.timestamp >= start_time)
            .order_by(AnalysisSignal.timestamp.desc())
            .all()
        )
        items = []
        for r in records:
            indicators = {}
            if r.indicators:
                try:
                    indicators = json.loads(r.indicators)
                except json.JSONDecodeError:
                    indicators = {}
            items.append(
                {
                    "timestamp": r.timestamp.isoformat(),
                    "signal_type": r.signal_type,
                    "price_cny_per_gram": r.price_cny_per_gram,
                    "indicators": indicators,
                    "notified": r.notified,
                }
            )
        return {"items": items}
    finally:
        session.close()


@router.get("/advice")
def get_advice():
    """获取智能买入建议和市场分析"""
    advisor = MarketAdvisor()
    advice = advisor.analyze()

    if advice is None:
        raise HTTPException(
            status_code=503,
            detail="数据积累中,请稍后再试。需要至少90天的历史数据才能提供准确建议。"
        )

    return {"data": advice}
