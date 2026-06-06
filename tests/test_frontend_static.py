from pathlib import Path
import re


INDEX_HTML = Path(__file__).resolve().parents[1] / "static" / "index.html"
STYLE_CSS = Path(__file__).resolve().parents[1] / "static" / "css" / "style.css"
CHART_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "chart.js"
CANDLESTICK_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "candlestick.js"


def test_dashboard_header_copy_is_streamlined():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "GoldPrice · 智能监控" not in html
    assert "实时采集、多源校验、技术指标与本机通知" not in html


def test_dashboard_scripts_use_deferred_loading():
    html = INDEX_HTML.read_text(encoding="utf-8")

    script_tags = re.findall(r'<script[^>]+src="[^"]+"([^>]*)></script>', html)

    assert script_tags
    assert all("defer" in attrs for attrs in script_tags)


def test_lightweight_charts_script_uses_local_vendor_url():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "/static/vendor/lightweight-charts.standalone.production.js" in html
    assert "cdn.jsdelivr.net/npm/lightweight-charts@" not in html
    assert "unpkg.com/lightweight-charts" not in html


def test_status_pill_has_live_region_attributes():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="status-pill"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html


def test_styles_define_refined_gold_theme_variables():
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert "--bg-0:" in css
    assert "--bg-1:" in css
    assert "--tone-gold:" in css
    assert "--tone-cyan:" in css
    assert "--elevation-2:" in css


def test_dashboard_chart_script_has_timeout_and_request_guard():
    script = CHART_JS.read_text(encoding="utf-8")

    assert "AbortController" in script
    assert "activeRequestId" in script
    assert "REQUEST_TIMEOUT_MS" in script
    assert "parsing: false" not in script
    assert "normalized: true" not in script
    assert "Number.isFinite(signalItem.price_cny_per_gram)" in script
    assert "state.chart = null;" in script


def test_candlestick_switch_handles_missing_dom_nodes():
    script = CANDLESTICK_JS.read_text(encoding="utf-8")

    assert "if (!canvas || !lineChartContainer || !candlestickContainer) return;" in script


def test_candlestick_script_supports_modern_lightweight_charts_and_deferred_layout():
    script = CANDLESTICK_JS.read_text(encoding="utf-8")

    assert "chart.addSeries(" in script
    assert "LightweightCharts.CandlestickSeries" in script
    assert "LightweightCharts.HistogramSeries" in script
    assert "window.requestAnimationFrame" in script


def test_candlestick_script_has_library_loader_and_failure_fallback():
    script = CANDLESTICK_JS.read_text(encoding="utf-8")

    assert "ensureLightweightChartsLoaded" in script
    assert "lightweightChartsLoadPromise" in script
    assert "loadScriptSequentially" in script
    assert "Failed to load Lightweight Charts" in script


def test_dashboard_uses_financial_terminal_fonts():
    html = INDEX_HTML.read_text(encoding="utf-8")
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert "IBM+Plex+Sans" in html
    assert "IBM+Plex+Mono" in html
    assert '--font-display: "IBM Plex Sans", sans-serif;' in css
    assert '--font-mono: "IBM Plex Mono", monospace;' in css


def test_chart_area_uses_high_contrast_terminal_tokens():
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert "--chart-bg:" in css
    assert "--chart-grid:" in css
    assert "background: var(--chart-bg);" in css


def test_signal_state_has_live_attention_animation():
    css = STYLE_CSS.read_text(encoding="utf-8")
    script = CHART_JS.read_text(encoding="utf-8")

    assert ".signal-state.signal-live" in css
    assert "@keyframes signalPulse" in css
    assert 'stateEl.classList.add("signal-live")' in script


def test_dashboard_has_market_brief_slots():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="source-quality-level"' in html
    assert 'id="source-quality-score"' in html
    assert 'id="source-quality-summary"' in html
    assert 'id="source-quality-primary-status"' in html
    assert 'id="source-quality-aggregation"' in html
    assert 'id="source-quality-list"' in html
    assert 'id="market-brief"' in html
    assert 'id="market-recommendation"' in html
    assert 'id="market-state"' in html
    assert 'id="market-score"' in html
    assert 'id="market-risk-summary"' in html
    assert 'id="market-risk-flags"' in html
    assert 'id="market-action-label"' in html
    assert 'id="market-action-detail"' in html
    assert 'id="market-insights"' in html


def test_dashboard_chart_script_renders_market_brief():
    script = CHART_JS.read_text(encoding="utf-8")

    assert 'fetchJSON("/api/price/sources/latest", signal)' in script
    assert "function updateSourceQuality(panelData)" in script
    assert 'getEl("source-quality-level")' in script
    assert 'getEl("source-quality-score")' in script
    assert 'getEl("source-quality-summary")' in script
    assert 'getEl("source-quality-primary-status")' in script
    assert 'getEl("source-quality-aggregation")' in script
    assert 'getEl("source-quality-list")' in script
    assert "panelData.primary_source" in script
    assert "当前主源：" in script
    assert "主源缺席" in script
    assert 'fetchJSON("/api/analysis/advice", signal)' in script
    assert "function updateMarketBrief(advice)" in script
    assert "function getRecommendationToneClass(recommendation)" in script
    assert "function stripLeadingEmoji(text)" in script
    assert 'getEl("market-recommendation")' in script
    assert 'getEl("market-score")' in script
    assert 'getEl("market-risk-summary")' in script
    assert 'getEl("market-risk-flags")' in script
    assert 'getEl("market-action-label")' in script
    assert 'getEl("market-action-detail")' in script
    assert 'getEl("market-insights")' in script


def test_market_brief_styles_define_recommendation_and_risk_tones():
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert ".hero-source-quality" in css
    assert ".source-quality-list" in css
    assert ".market-recommendation.market-buy" in css
    assert ".market-recommendation.market-hold" in css
    assert ".market-recommendation.market-risk" in css
    assert ".risk-chip.risk-danger" in css
    assert ".market-meta" in css
    assert ".market-action" in css
    assert ".market-action-label" in css


def test_dashboard_has_chart_status_slots():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="chart-status-summary"' in html
    assert 'id="line-chart-status"' in html
    assert 'id="line-chart-detail"' in html
    assert 'id="candlestick-chart-status"' in html
    assert 'id="candlestick-chart-detail"' in html


def test_dashboard_chart_script_renders_chart_status_summary():
    script = CHART_JS.read_text(encoding="utf-8")

    assert "function updateSingleChartStatus(chartType, status)" in script
    assert "function buildChartStatusFromMeta(chartType, meta)" in script
    assert 'getEl("line-chart-status")' in script
    assert 'getEl("candlestick-chart-status")' in script
    assert 'updateSingleChartStatus(\n      "line"' in script
    assert 'updateSingleChartStatus(\n      "candlestick"' in script


def test_chart_status_styles_define_summary_cards():
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert ".chart-status-summary" in css
    assert ".chart-status-card" in css
    assert ".chart-status-label" in css
    assert ".chart-status-detail" in css


def test_dashboard_has_signal_debug_slots():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="signal-debug"' in html
    assert 'id="debug-entry-status"' in html
    assert 'id="debug-confidence"' in html
    assert 'id="debug-dominant-factor"' in html
    assert 'id="debug-change-reason"' in html
    assert 'id="debug-previous-advice"' in html
    assert 'id="debug-change-time"' in html
    assert 'id="debug-factor-changes"' in html
    assert 'id="debug-regime"' in html
    assert 'id="debug-expected-return"' in html
    assert 'id="debug-position-size"' in html
    assert 'id="debug-setup-flags"' in html
    assert 'id="debug-confirmation-flags"' in html
    assert 'id="debug-risk-flags"' in html
    assert 'id="debug-reasons"' in html


def test_dashboard_has_signal_performance_and_sr_slots():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="backtest-window"' in html
    assert 'id="backtest-signal-count"' in html
    assert 'id="backtest-evaluated-count"' in html
    assert 'id="backtest-avg-return"' in html
    assert 'id="backtest-win-rate"' in html
    assert 'id="backtest-max-drawdown"' in html
    assert 'id="backtest-highscore"' in html
    assert 'id="backtest-correlation"' in html
    assert 'id="sr-current-price"' in html
    assert 'id="sr-nearest-support"' in html
    assert 'id="sr-nearest-resistance"' in html
    assert 'id="sr-round-levels"' in html
    assert 'id="sr-level-list"' in html
    assert 'id="custom-alert-form"' in html
    assert 'id="custom-alert-list"' in html
    assert 'id="custom-alert-status"' in html
    assert 'id="alert-delivery-list"' in html
    assert 'id="alert-delivery-state"' in html
    assert 'id="macro-domestic-price"' in html
    assert 'id="macro-global-price"' in html
    assert 'id="macro-premium"' in html
    assert 'id="macro-corr"' in html
    assert 'id="macro-usd-close"' in html
    assert 'id="macro-usd-change"' in html
    assert 'id="macro-hint"' in html
    assert 'id="timeframe-alignment"' in html
    assert 'id="timeframe-score"' in html
    assert 'id="timeframe-list"' in html
    assert 'id="timeframe-summary"' in html
    assert 'id="forecast-current"' in html
    assert 'id="forecast-expected"' in html
    assert 'id="forecast-prob-up"' in html
    assert 'id="forecast-range"' in html
    assert 'id="forecast-scenario"' in html
    assert 'id="entry-plan-form"' in html
    assert 'id="entry-plan-summary"' in html
    assert 'id="entry-plan-list"' in html
    assert 'id="confidence-health"' in html
    assert 'id="confidence-signal-count"' in html
    assert 'id="confidence-primary-win-rate"' in html
    assert 'id="confidence-primary-return"' in html
    assert 'id="confidence-current-recommendation"' in html
    assert 'id="confidence-current-dominant-factor"' in html
    assert 'id="confidence-current-summary"' in html
    assert 'id="confidence-current-regime-summary"' in html
    assert 'id="confidence-risk-checks"' in html
    assert 'id="confidence-regime-breakdown"' in html
    assert 'id="confidence-similar-history"' in html


def test_dashboard_chart_script_renders_performance_and_sr_panels():
    script = CHART_JS.read_text(encoding="utf-8")

    assert "function updateSignalPerformance(performance)" in script
    assert "function updateConfidenceCenter(panelData)" in script
    assert "regime_breakdown" in script
    assert "is_current" in script
    assert "当前状态" in script
    assert "当前环境历史表现" in script
    assert "高于整体胜率" in script
    assert "低于整体胜率" in script
    assert 'getEl("confidence-current-regime-summary")' in script
    assert 'getEl("confidence-regime-breakdown")' in script
    assert "function updateSupportResistance(levelData)" in script
    assert "function buildSupportResistanceDatasets(length, levelLines)" in script
    assert 'fetchJSON(`/api/analysis/signal-performance?window_days=${Math.max(range.days, 90)}`' in script
    assert 'fetchJSON(`/api/analysis/confidence-center?window_days=${Math.max(range.days, 120)}`' in script
    assert 'fetchJSON(`/api/analysis/support-resistance?window_days=${Math.max(range.days, 90)}`' in script
    assert "state.supportResistanceLines = Array.isArray(levelData.plot_lines)" in script
    assert "function loadCustomAlerts(signal)" in script
    assert 'fetchJSON("/api/alerts", signal)' in script
    assert "function bindCustomAlertPanel()" in script
    assert "function createCustomAlertRule()" in script
    assert "function loadAlertDeliveries(signal)" in script
    assert 'fetchJSON(`/api/alerts/deliveries?' in script
    assert "function updateMacroCorrelation(panelData)" in script
    assert 'fetchJSON(`/api/analysis/macro-correlation?window_days=${Math.max(range.days, 120)}`' in script
    assert "function updateMultiTimeframe(panelData)" in script
    assert "function updateForecast(panelData)" in script
    assert "function renderEntryPlan(planData)" in script
    assert "function loadEntryPlan(signal)" in script
    assert 'fetchJSON(`/api/analysis/multi-timeframe?windows=1,7,30&lookback_days=${Math.max(range.days, 120)}`' in script
    assert 'fetchJSON(`/api/analysis/forecast?lookback_days=${Math.max(range.days, 120)}&horizon_days=7`' in script
    assert 'fetchJSON(`/api/analysis/entry-plan?' in script


def test_candlestick_supports_sr_price_lines_bridge():
    script = CANDLESTICK_JS.read_text(encoding="utf-8")

    assert "applySupportResistancePriceLines" in script
    assert "clearSupportResistancePriceLines" in script
    assert "createPriceLine" in script
    assert "window.updateCandlestickSupportResistanceLines = (lines) => {" in script


def test_dashboard_chart_script_renders_signal_debug_view():
    script = CHART_JS.read_text(encoding="utf-8")

    assert 'fetchJSON("/api/analysis/buy-signal", signal)' in script
    assert "function updateSignalDebug(evaluation)" in script
    assert 'getEl("debug-entry-status")' in script
    assert 'getEl("debug-confidence")' in script
    assert 'getEl("debug-dominant-factor")' in script
    assert 'getEl("debug-change-reason")' in script
    assert 'getEl("debug-previous-advice")' in script
    assert 'getEl("debug-change-time")' in script
    assert 'getEl("debug-factor-changes")' in script
    assert 'getEl("debug-regime")' in script
    assert 'getEl("debug-expected-return")' in script
    assert 'getEl("debug-position-size")' in script
    assert 'getEl("debug-setup-flags")' in script
    assert 'getEl("debug-confirmation-flags")' in script
    assert 'getEl("debug-risk-flags")' in script
    assert 'getEl("debug-reasons")' in script
    assert "evaluation.explainability" in script
    assert "function buildLineChartContext" in script
    assert "function buildCandlestickChartContext" in script
    assert "window.updateCandlestickChartContext" in script


def test_signal_debug_styles_define_panels_and_flag_lists():
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert ".signal-debug" in css
    assert ".debug-grid" in css
    assert ".debug-block" in css
    assert ".debug-meta" in css
    assert ".debug-meta-item" in css
    assert ".debug-flag-list" in css
    assert ".debug-flag" in css
    assert ".debug-factor-changes" in css
    assert ".debug-chart-detail-grid" in css


def test_performance_and_sr_styles_are_defined():
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert ".signal-performance" in css
    assert ".sr-panel" in css
    assert ".performance-overview" in css
    assert ".metric-box" in css
    assert ".performance-note" in css
    assert ".sr-grid" in css
    assert ".sr-item" in css
    assert ".sr-item-support" in css
    assert ".sr-item-resistance" in css
    assert ".sr-item-round" in css
    assert ".alert-delivery-panel" in css
    assert ".alert-delivery-controls" in css
    assert ".macro-correlation-panel" in css
    assert ".timeframe-panel" in css
    assert ".forecast-panel" in css
    assert ".entry-plan-panel" in css
    assert ".entry-plan-form" in css
