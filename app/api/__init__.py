from fastapi import APIRouter

from app.api.price import (
    get_current_price,
    get_price_history,
    get_candlestick_data,
    router as price_router,
)
from app.api.analysis import (
    get_indicators,
    get_signals,
    get_advice,
    get_buy_signal_evaluation,
    get_cache_stats,
    get_signal_performance,
    get_support_resistance,
    get_macro_correlation,
    get_multi_timeframe,
    get_price_forecast,
    get_entry_plan,
    router as analysis_router,
)
from app.api.health import health_check, router as health_router
from app.api.websocket import websocket_endpoint, router as websocket_router
from app.api.logs import get_logs, get_log_stats, search_logs, router as logs_router
from app.api.alerts import (
    list_alert_rules,
    create_alert_rule,
    update_alert_rule,
    delete_alert_rule,
    list_delivery_logs,
    router as alerts_router,
)

router = APIRouter()
router.include_router(price_router)
router.include_router(analysis_router)
router.include_router(health_router)
router.include_router(websocket_router)
router.include_router(logs_router)
router.include_router(alerts_router)

v1_router = APIRouter()
v1_router.get("/api/v1/price/current")(get_current_price)
v1_router.get("/api/v1/price/history")(get_price_history)
v1_router.get("/api/v1/price/candlestick")(get_candlestick_data)
v1_router.get("/api/v1/analysis/indicators")(get_indicators)
v1_router.get("/api/v1/analysis/signals")(get_signals)
v1_router.get("/api/v1/analysis/advice")(get_advice)
v1_router.get("/api/v1/analysis/buy-signal")(get_buy_signal_evaluation)
v1_router.get("/api/v1/analysis/cache/stats")(get_cache_stats)
v1_router.get("/api/v1/analysis/signal-performance")(get_signal_performance)
v1_router.get("/api/v1/analysis/support-resistance")(get_support_resistance)
v1_router.get("/api/v1/analysis/macro-correlation")(get_macro_correlation)
v1_router.get("/api/v1/analysis/multi-timeframe")(get_multi_timeframe)
v1_router.get("/api/v1/analysis/forecast")(get_price_forecast)
v1_router.get("/api/v1/analysis/entry-plan")(get_entry_plan)
v1_router.get("/api/v1/health")(health_check)
v1_router.websocket("/api/v1/ws")(websocket_endpoint)
v1_router.get("/api/v1/logs")(get_logs)
v1_router.get("/api/v1/logs/stats")(get_log_stats)
v1_router.get("/api/v1/logs/search")(search_logs)
v1_router.get("/api/v1/alerts")(list_alert_rules)
v1_router.post("/api/v1/alerts")(create_alert_rule)
v1_router.patch("/api/v1/alerts/{rule_id}")(update_alert_rule)
v1_router.delete("/api/v1/alerts/{rule_id}")(delete_alert_rule)
v1_router.get("/api/v1/alerts/deliveries")(list_delivery_logs)
