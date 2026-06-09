const REQUEST_TIMEOUT_MS = 10000;
const REFRESH_INTERVAL_MS = 180000;

const ranges = {
  "7D": { days: 7, interval: "30m" },
  "30D": { days: 30, interval: "2h" },
  "90D": { days: 90, interval: "6h" },
  "1Y": { days: 365, interval: "1d" },
  ALL: { days: 3650, interval: "1d" },
};

const state = {
  range: "30D",
  chart: null,
  activeRequestId: 0,
  activeController: null,
  refreshHandle: null,
  lineChartContext: null,
  candlestickChartContext: null,
  supportResistanceLines: [],
};

function getEl(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function updateStatus(text, mode) {
  const status = getEl("status-pill");
  if (!status) return;
  status.textContent = text;
  status.classList.remove("online", "offline", "status-pending");
  if (mode) {
    status.classList.add(mode);
  }
}

async function fetchJSON(url, signal) {
  const timeoutController = new AbortController();
  const timeoutId = window.setTimeout(() => timeoutController.abort(), REQUEST_TIMEOUT_MS);

  if (signal) {
    if (signal.aborted) {
      timeoutController.abort();
    } else {
      signal.addEventListener("abort", () => timeoutController.abort(), { once: true });
    }
  }

  try {
    const response = await fetch(url, { signal: timeoutController.signal });
    if (!response.ok) {
      throw new Error(`Request failed: ${url}`);
    }
    return response.json();
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function formatPrice(value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return `¥${Number(value).toFixed(2)}/克`;
}

function formatPercent(value) {
  if (value == null || Number.isNaN(value)) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatPctCompact(value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

function formatSignedNumber(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(digits)}`;
}

function prettifyAlertType(ruleType) {
  const mapping = {
    price_above: "价格突破",
    price_below: "价格跌破",
    rsi_above: "RSI 超买",
    rsi_below: "RSI 超卖",
    daily_change_abs_gte: "单日波动",
  };
  return mapping[ruleType] || ruleType;
}

function formatAlertThreshold(ruleType, threshold) {
  const numeric = Number(threshold);
  if (!Number.isFinite(numeric)) return "--";
  if (ruleType === "rsi_above" || ruleType === "rsi_below") {
    return numeric.toFixed(2);
  }
  if (ruleType === "daily_change_abs_gte") {
    return `${numeric.toFixed(2)}%`;
  }
  return `¥${numeric.toFixed(2)}`;
}

function resolvePrimarySourceLabel(sourceQuality) {
  const primarySource = sourceQuality?.primary_source || null;
  if (primarySource?.status === "available") {
    return primarySource.display_name || primarySource.name || "SGE 官网延时行情";
  }
  if (primarySource?.status === "missing") {
    return "主源缺席";
  }

  const sources = Array.isArray(sourceQuality?.sources) ? sourceQuality.sources : [];
  const validPrimarySources = sources.filter(
    (item) => item && item.is_valid && item.trust_tier === "high" && !item.is_backup
  );
  const preferredPrimarySource =
    validPrimarySources.find((item) => item.name === "sge_official") || validPrimarySources[0] || null;
  return preferredPrimarySource
    ? preferredPrimarySource.display_name || preferredPrimarySource.name
    : "主源缺席";
}

function updateDecisionStrip({ current, advice, sourceQuality }) {
  const priceEl = getEl("decision-current-price");
  const adviceEl = getEl("decision-current-advice");
  const sourceEl = getEl("decision-primary-source");
  const actionEl = getEl("decision-action");

  if (!priceEl || !adviceEl || !sourceEl || !actionEl) return;

  const latestPrice = Number(current?.price_cny_per_gram ?? current?.price);
  priceEl.textContent = Number.isFinite(latestPrice) ? formatPrice(latestPrice) : "--";
  adviceEl.textContent = advice?.recommendation || "分析中";
  sourceEl.textContent = `当前主源：${resolvePrimarySourceLabel(sourceQuality)}`;
  actionEl.textContent = advice?.action_label || "等待建议";
}

function updatePositionDecision(positionPayload, advicePayload) {
  const statusEl = getEl("position-status");
  const adviceEl = getEl("sell-advice");
  const detailEl = getEl("sell-advice-detail");
  if (!statusEl || !adviceEl || !detailEl) return;

  const position = advicePayload?.position || positionPayload || {};
  const sellAdvice = advicePayload?.sell_advice || {};
  if (!position.has_position) {
    statusEl.textContent = "未记录持仓";
    adviceEl.textContent = "无需卖出";
    detailEl.textContent = "当前没有持仓，卖出/减仓建议暂不适用。";
    return;
  }

  const quantity = Number(position.quantity_gram || 0);
  const cost = Number(position.avg_cost_price);
  const quantityText = Number.isFinite(quantity) ? `${quantity.toFixed(3)}g` : "--";
  const costText = Number.isFinite(cost) ? `成本 ${formatPrice(cost)}` : "成本未设置";
  statusEl.textContent = `${quantityText} · ${costText}`;
  adviceEl.textContent = sellAdvice.action_label || "继续持有";
  const pnlText =
    sellAdvice.unrealized_pnl_pct == null
      ? ""
      : `浮盈亏 ${formatPctCompact(sellAdvice.unrealized_pnl_pct)} · `;
  const sellPctText =
    Number(sellAdvice.suggested_sell_pct || 0) > 0
      ? `建议减仓 ${Number(sellAdvice.suggested_sell_pct)}% · `
      : "";
  detailEl.textContent = `${pnlText}${sellPctText}${sellAdvice.reason || "当前未触发明确卖出条件。"}`;
}

function simpleMovingAverage(values, windowSize) {
  const result = new Array(values.length).fill(null);
  if (windowSize <= 0) return result;

  let rollingSum = 0;
  let invalidCount = 0;
  for (let i = 0; i < values.length; i += 1) {
    const added = values[i];
    if (Number.isFinite(added)) {
      rollingSum += added;
    } else {
      invalidCount += 1;
    }

    if (i >= windowSize) {
      const removed = values[i - windowSize];
      if (Number.isFinite(removed)) {
        rollingSum -= removed;
      } else {
        invalidCount -= 1;
      }
    }

    if (i >= windowSize - 1 && invalidCount === 0) {
      result[i] = Number((rollingSum / windowSize).toFixed(2));
    }
  }

  return result;
}

function bollingerBands(values, windowSize, factor) {
  const upper = new Array(values.length).fill(null);
  const lower = new Array(values.length).fill(null);
  if (windowSize <= 0) {
    return { upper, lower };
  }

  let rollingSum = 0;
  let rollingSumSquares = 0;
  let invalidCount = 0;

  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (Number.isFinite(value)) {
      rollingSum += value;
      rollingSumSquares += value * value;
    } else {
      invalidCount += 1;
    }

    if (i >= windowSize) {
      const dropped = values[i - windowSize];
      if (Number.isFinite(dropped)) {
        rollingSum -= dropped;
        rollingSumSquares -= dropped * dropped;
      } else {
        invalidCount -= 1;
      }
    }

    if (i >= windowSize - 1 && invalidCount === 0) {
      const mean = rollingSum / windowSize;
      const variance = Math.max(rollingSumSquares / windowSize - mean * mean, 0);
      const std = Math.sqrt(variance);
      upper[i] = Number((mean + factor * std).toFixed(2));
      lower[i] = Number((mean - factor * std).toFixed(2));
    }
  }

  return { upper, lower };
}

function updatePrice(data) {
  if (!data) return;
  const latestPrice = Number(data.price_cny_per_gram ?? data.price);
  if (!Number.isFinite(latestPrice)) return;

  const priceEl = getEl("current-price");
  const updatedEl = getEl("last-updated");
  if (priceEl) {
    priceEl.textContent = formatPrice(latestPrice);
  }
  if (updatedEl) {
    const timestamp = data.timestamp ? new Date(data.timestamp) : new Date();
    updatedEl.textContent = timestamp.toLocaleString();
  }
}

function updateSourceQuality(panelData) {
  const levelEl = getEl("source-quality-level");
  const scoreEl = getEl("source-quality-score");
  const summaryEl = getEl("source-quality-summary");
  const primaryStatusEl = getEl("source-quality-primary-status");
  const aggregationEl = getEl("source-quality-aggregation");
  const listEl = getEl("source-quality-list");

  if (!levelEl || !scoreEl || !summaryEl || !primaryStatusEl || !aggregationEl || !listEl) {
    return;
  }

  if (!panelData) {
    levelEl.textContent = "等待分析";
    scoreEl.textContent = "--";
    summaryEl.textContent = "等待最近一次源共识分析";
    primaryStatusEl.textContent = "当前主源：等待分析";
    aggregationEl.textContent = "等待聚合方法分析";
    listEl.innerHTML = "<li>等待数据源明细</li>";
    return;
  }

  const quality = panelData.quality || {};
  const aggregation = panelData.aggregation || {};
  const sources = Array.isArray(panelData.sources) ? panelData.sources : [];
  const primarySource = panelData.primary_source || null;
  const levelMap = {
    high: "高可信",
    medium: "中可信",
    low: "低可信",
  };
  levelEl.textContent = levelMap[quality.confidence_level] || "待判断";
  scoreEl.textContent = Number.isFinite(Number(quality.confidence_score))
    ? `${Math.round(Number(quality.confidence_score))}`
    : "--";
  summaryEl.textContent = quality.summary || "当前尚无足够源共识信息";
  if (primarySource && primarySource.status === "available") {
    primaryStatusEl.textContent = `当前主源：${primarySource.display_name || primarySource.name}`;
  } else if (primarySource && primarySource.status === "missing") {
    primaryStatusEl.textContent = "当前主源：主源缺席";
  } else {
    const validPrimarySources = sources.filter(
      (item) => item && item.is_valid && item.trust_tier === "high" && !item.is_backup
    );
    const preferredPrimarySource =
      validPrimarySources.find((item) => item.name === "sge_official") || validPrimarySources[0] || null;
    primaryStatusEl.textContent = preferredPrimarySource
      ? `当前主源：${preferredPrimarySource.display_name || preferredPrimarySource.name}`
      : "当前主源：主源缺席";
  }
  const aggregationMap = {
    primary_trusted_anchor: "聚合方法：高可信主源锚定",
    weighted_trust_mean: "聚合方法：多源加权均值",
    secondary_weighted: "聚合方法：主源缺席下的次级加权",
    fallback_mean: "聚合方法：退回简单均值",
    unavailable: "聚合方法：当前不可用",
  };
  aggregationEl.textContent =
    aggregationMap[aggregation.method] || "聚合方法：当前不可判定";
  listEl.innerHTML = sources.length
    ? sources
        .map((item) => {
          const validity = item.is_valid ? "有效" : "剔除";
          const backup = item.is_backup ? " · 备用源" : "";
          const recentValidRate = Number.isFinite(Number(item.health?.recent_valid_rate_pct))
            ? ` · 健康率 ${Number(item.health.recent_valid_rate_pct).toFixed(0)}%`
            : "";
          return `<li>${escapeHtml(item.display_name)} · ¥${Number(item.price_cny_per_gram).toFixed(
            2
          )} · ${escapeHtml(item.trust_tier)} 可信 · ${escapeHtml(validity)}${escapeHtml(
            backup
          )}${escapeHtml(recentValidRate)}</li>`;
        })
        .join("")
    : "<li>暂无数据源明细</li>";
}

function updateSourceDiagnostics(panelData) {
  const statusEl = getEl("source-diagnostic-status");
  const outlierEl = getEl("source-outlier-summary");
  if (!statusEl || !outlierEl) return;

  if (!panelData) {
    statusEl.textContent = "诊断状态：等待采集诊断";
    outlierEl.textContent = "异常价：等待分析";
    return;
  }

  const statusMap = {
    accepted: "正常入库",
    rejected_by_source_filter: "已剔除异常源",
    rejected_by_price_guard: "价格守卫拒绝",
    unavailable: "暂无诊断",
  };
  const summary = panelData.summary || {};
  statusEl.textContent = `诊断状态：${statusMap[panelData.status] || panelData.status || "暂无诊断"}`;
  if (summary.has_outliers && panelData.latest_rejection) {
    const rejection = panelData.latest_rejection;
    outlierEl.textContent = `异常价：${rejection.source_name} · ${formatPrice(
      rejection.price_cny_per_gram
    )} 已隔离`;
  } else if (summary.invalid_source_count > 0) {
    outlierEl.textContent = `异常价：${Number(summary.invalid_source_count)} 个来源已隔离`;
  } else {
    outlierEl.textContent = "异常价：最近采集未发现异常源";
  }
}

function updateIndicators(indicators) {
  const values = indicators || {};
  const list = getEl("indicator-list");
  if (list) {
    list.innerHTML = "";
    const entries = [
      ["MA7", values.ma_short],
      ["MA30", values.ma_medium],
      ["MA90", values.ma_long],
      ["布林上轨", values.bb_upper],
      ["布林中轨", values.bb_middle],
      ["布林下轨", values.bb_lower],
      ["RSI", values.rsi],
      ["波动率", values.volatility],
    ];

    entries.forEach(([label, value]) => {
      const li = document.createElement("li");
      const display = value == null ? "--" : Number(value).toFixed(2);
      li.textContent = `${label}: ${display}`;
      list.appendChild(li);
    });
  }

  const metricRsi = getEl("metric-rsi");
  const metricVolatility = getEl("metric-volatility");
  const metricMa = getEl("metric-ma");
  const metricBb = getEl("metric-bb");

  if (metricRsi) metricRsi.textContent = values.rsi == null ? "--" : values.rsi.toFixed(2);
  if (metricVolatility) {
    metricVolatility.textContent =
      values.volatility == null ? "--" : values.volatility.toFixed(2);
  }
  if (metricMa) metricMa.textContent = values.ma_medium == null ? "--" : values.ma_medium.toFixed(2);
  if (metricBb) metricBb.textContent = values.bb_lower == null ? "--" : values.bb_lower.toFixed(2);
}

function updateSignals(signals) {
  const signalItems = Array.isArray(signals) ? signals : [];
  const list = getEl("signal-list");
  const stateEl = getEl("signal-state");
  const reasonEl = getEl("signal-reason");

  if (list) {
    list.innerHTML = "";
  }

  if (!signalItems.length) {
    if (list) {
      const li = document.createElement("li");
      li.textContent = "暂无信号";
      list.appendChild(li);
    }
    if (stateEl) {
      stateEl.textContent = "暂无信号";
      stateEl.classList.remove("signal-live");
    }
    if (reasonEl) reasonEl.textContent = "等待下一次分析";
    return;
  }

  signalItems.slice(0, 6).forEach((signal) => {
    if (!list) return;
    const li = document.createElement("li");
    const time = new Date(signal.timestamp).toLocaleString();
    li.textContent = `${time} · ¥${signal.price_cny_per_gram.toFixed(2)} · ${signal.signal_type}`;
    list.appendChild(li);
  });

  const latest = signalItems[0];
  if (stateEl) {
    stateEl.textContent = "触发买入信号";
    stateEl.classList.add("signal-live");
  }
  if (reasonEl) {
    reasonEl.textContent = `价格 ¥${latest.price_cny_per_gram.toFixed(2)} · RSI ${latest.indicators?.rsi ?? "--"}`;
  }
}

function resolveHorizonStat(performance, horizonDays) {
  const stats = Array.isArray(performance?.horizon_stats) ? performance.horizon_stats : [];
  if (!stats.length) return null;
  const exact = stats.find((item) => Number(item?.horizon_days) === Number(horizonDays));
  return exact || stats[0];
}

function updateSignalPerformance(performance) {
  const signalCountEl = getEl("backtest-signal-count");
  const evaluatedCountEl = getEl("backtest-evaluated-count");
  const primaryWindowEl = getEl("backtest-window");
  const avgReturnEl = getEl("backtest-avg-return");
  const winRateEl = getEl("backtest-win-rate");
  const drawdownEl = getEl("backtest-max-drawdown");
  const highScoreEl = getEl("backtest-highscore");
  const correlationEl = getEl("backtest-correlation");

  if (
    !signalCountEl ||
    !evaluatedCountEl ||
    !primaryWindowEl ||
    !avgReturnEl ||
    !winRateEl ||
    !drawdownEl ||
    !highScoreEl ||
    !correlationEl
  ) {
    return;
  }

  if (!performance) {
    signalCountEl.textContent = "--";
    evaluatedCountEl.textContent = "--";
    primaryWindowEl.textContent = "等待回测";
    avgReturnEl.textContent = "--";
    winRateEl.textContent = "--";
    drawdownEl.textContent = "--";
    highScoreEl.textContent = "高分信号表现暂不可用";
    correlationEl.textContent = "评分与收益相关性暂不可用";
    return;
  }

  signalCountEl.textContent = `${Number(performance.signal_count || 0)}`;
  evaluatedCountEl.textContent = `${Number(performance.evaluated_signal_count || 0)}`;

  const primaryHorizon = resolveHorizonStat(performance, 7) || resolveHorizonStat(performance, 3);
  const horizonDays = primaryHorizon?.horizon_days ?? 7;
  primaryWindowEl.textContent = `${horizonDays}天窗口`;
  avgReturnEl.textContent = formatPctCompact(primaryHorizon?.avg_return_pct);
  winRateEl.textContent = formatPctCompact(primaryHorizon?.win_rate_pct);
  drawdownEl.textContent = formatPctCompact(primaryHorizon?.max_drawdown_pct);

  const highScore = performance.high_score_segment || {};
  const highSampleCount = Number(highScore.sample_count || 0);
  highScoreEl.textContent =
    highSampleCount > 0
      ? `评分≥${highScore.threshold}，${highScore.horizon_days}天胜率 ${formatPctCompact(highScore.win_rate_pct)}`
      : `评分≥${highScore.threshold || 80} 暂无足够样本`;

  correlationEl.textContent =
    primaryHorizon?.score_return_correlation == null
      ? "评分与收益相关性样本不足"
      : `评分-收益相关性: ${Number(primaryHorizon.score_return_correlation).toFixed(3)}`;
}

function getAuditTone(status) {
  if (status === "healthy") return { label: "健康", className: "risk-chip risk-safe" };
  if (status === "watch") return { label: "观察", className: "risk-chip risk-watch" };
  if (status === "degraded") return { label: "退化", className: "risk-chip risk-danger" };
  return { label: "样本不足", className: "risk-chip risk-watch" };
}

function updateConfidenceCenter(panelData) {
  const healthEl = getEl("confidence-health");
  const signalCountEl = getEl("confidence-signal-count");
  const winRateEl = getEl("confidence-primary-win-rate");
  const returnEl = getEl("confidence-primary-return");
  const recommendationEl = getEl("confidence-current-recommendation");
  const factorEl = getEl("confidence-current-dominant-factor");
  const summaryEl = getEl("confidence-current-summary");
  const currentRegimeSummaryEl = getEl("confidence-current-regime-summary");
  const checksEl = getEl("confidence-risk-checks");
  const regimeEl = getEl("confidence-regime-breakdown");
  const historyEl = getEl("confidence-similar-history");

  if (
    !healthEl ||
    !signalCountEl ||
    !winRateEl ||
    !returnEl ||
    !recommendationEl ||
    !factorEl ||
    !summaryEl ||
    !currentRegimeSummaryEl ||
    !checksEl ||
    !regimeEl ||
    !historyEl
  ) {
    return;
  }

  if (!panelData) {
    healthEl.textContent = "等待分析";
    signalCountEl.textContent = "--";
    winRateEl.textContent = "--";
    returnEl.textContent = "--";
    recommendationEl.textContent = "--";
    factorEl.textContent = "--";
    summaryEl.textContent = "等待可信度分析";
    currentRegimeSummaryEl.textContent = "等待当前环境历史表现";
    checksEl.innerHTML = '<span class="risk-chip risk-watch">等待检查</span>';
    regimeEl.innerHTML = "<li>等待状态分层统计</li>";
    historyEl.innerHTML = "<li>等待历史相似样本分析</li>";
    return;
  }

  const summary = panelData.summary || {};
  const primary = panelData.performance_snapshot?.primary_horizon || {};
  const regimeBreakdown = Array.isArray(panelData.performance_snapshot?.regime_breakdown)
    ? panelData.performance_snapshot.regime_breakdown
    : [];
  const currentRegime = panelData.performance_snapshot?.current_regime || {};
  const advice = panelData.current_advice || {};
  const tone = getAuditTone(summary.degradation_status);
  const sortedRegimeBreakdown = [...regimeBreakdown].sort((a, b) => {
    if (Boolean(a?.is_current) === Boolean(b?.is_current)) return 0;
    return a?.is_current ? -1 : 1;
  });
  const bestRegime = regimeBreakdown[0];
  const currentRegimeLabel = currentRegime.label;
  const currentRegimeItem =
    sortedRegimeBreakdown.find((item) => item?.is_current) || null;
  const overallWinRate = Number.isFinite(Number(primary.win_rate_pct))
    ? Number(primary.win_rate_pct)
    : null;
  const overallAvgReturn = Number.isFinite(Number(primary.avg_return_pct))
    ? Number(primary.avg_return_pct)
    : null;

  healthEl.textContent = tone.label;
  signalCountEl.textContent = `${Number(summary.signal_count || 0)}`;
  winRateEl.textContent = formatPctCompact(primary.win_rate_pct);
  returnEl.textContent = formatPctCompact(primary.avg_return_pct);
  recommendationEl.textContent = advice.recommendation || "暂无建议";
  factorEl.textContent = advice.dominant_factor || "暂无主导因子";
  summaryEl.textContent =
    currentRegimeItem && currentRegimeLabel
      ? `${summary.degradation_reason || "暂无策略体检摘要"} 当前处于${currentRegimeLabel}。`
      : bestRegime && currentRegimeLabel
      ? `${summary.degradation_reason || "暂无策略体检摘要"} 当前处于${currentRegimeLabel}，样本最多的状态是${bestRegime.label}，胜率 ${formatPctCompact(
          bestRegime.win_rate_pct
        )}，平均收益 ${formatPctCompact(bestRegime.avg_return_pct)}。`
      : bestRegime
      ? `${summary.degradation_reason || "暂无策略体检摘要"} 当前样本最多的状态是${bestRegime.label}，胜率 ${formatPctCompact(
          bestRegime.win_rate_pct
        )}，平均收益 ${formatPctCompact(bestRegime.avg_return_pct)}。`
      : summary.degradation_reason ||
        advice.change_reason ||
        advice.summary ||
        panelData.similar_history?.summary ||
        "暂无可信度摘要";
  currentRegimeSummaryEl.textContent = currentRegimeItem
    ? (() => {
        const currentWinRate = Number.isFinite(Number(currentRegimeItem.win_rate_pct))
          ? Number(currentRegimeItem.win_rate_pct)
          : null;
        const currentAvgReturn = Number.isFinite(Number(currentRegimeItem.avg_return_pct))
          ? Number(currentRegimeItem.avg_return_pct)
          : null;
        const winRateDelta =
          currentWinRate != null && overallWinRate != null
            ? currentWinRate - overallWinRate
            : null;
        const avgReturnDelta =
          currentAvgReturn != null && overallAvgReturn != null
            ? currentAvgReturn - overallAvgReturn
            : null;
        const winRateCompare =
          winRateDelta == null
            ? "整体胜率对比暂不可用"
            : winRateDelta >= 0
            ? `高于整体胜率 ${formatSignedNumber(winRateDelta)}pct`
            : `低于整体胜率 ${Math.abs(winRateDelta).toFixed(2)}pct`;
        const avgReturnCompare =
          avgReturnDelta == null
            ? "整体收益对比暂不可用"
            : avgReturnDelta >= 0
            ? `高于整体收益 ${formatPctCompact(avgReturnDelta)}`
            : `低于整体收益 ${Math.abs(avgReturnDelta).toFixed(2)}%`;
        return `当前环境历史表现：${currentRegimeItem.label} · 样本 ${Number(
          currentRegimeItem.sample_count || 0
        )} · ${winRateCompare} · ${avgReturnCompare}`;
      })()
    : "当前环境历史表现暂不可用";

  const checks = Array.isArray(panelData.risk_checks) ? panelData.risk_checks : [];
  checksEl.innerHTML = checks.length
    ? checks
        .map((check) => {
          const checkTone =
            check.status === "pass"
              ? "risk-safe"
              : check.status === "warn"
              ? "risk-watch"
              : "risk-danger";
          return `<span class="risk-chip ${checkTone}">${escapeHtml(check.name)}: ${escapeHtml(
            check.detail
          )}</span>`;
        })
        .join("")
    : '<span class="risk-chip risk-watch">暂无检查结果</span>';

  regimeEl.innerHTML = sortedRegimeBreakdown.length
    ? sortedRegimeBreakdown
        .map((item) => {
          const sampleCount = Number(item.sample_count || 0);
          const currentChip = item.is_current
            ? ' <span class="risk-chip risk-safe">当前状态</span>'
            : "";
          return `<li>${escapeHtml(item.label)} · 样本 ${sampleCount} · 胜率 ${formatPctCompact(
            item.win_rate_pct
          )} · 平均收益 ${formatPctCompact(item.avg_return_pct)}${currentChip}</li>`;
        })
        .join("")
    : "<li>暂无状态分层统计</li>";

  const matches = Array.isArray(panelData.similar_history?.matches)
    ? panelData.similar_history.matches
    : [];
  historyEl.innerHTML = matches.length
    ? matches
        .map((item) => {
          const reasons = Array.isArray(item.reasons) && item.reasons.length
            ? ` · ${escapeHtml(item.reasons.join(" / "))}`
            : "";
          const score = Number.isFinite(Number(item.score)) ? ` · 评分 ${Number(item.score).toFixed(0)}` : "";
          const realized = item.primary_horizon_return_pct == null
            ? ""
            : ` · 主窗口收益 ${formatPctCompact(item.primary_horizon_return_pct)}`;
          return `<li>${new Date(item.timestamp).toLocaleDateString()} · ¥${Number(item.price_cny_per_gram).toFixed(2)}${score}${realized}${reasons}</li>`;
        })
        .join("")
    : `<li>${escapeHtml(panelData.similar_history?.summary || "未找到相似历史样本")}</li>`;
}

function levelToneClass(kind) {
  if (kind === "support") return "sr-item-support";
  if (kind === "resistance") return "sr-item-resistance";
  return "sr-item-round";
}

function renderSupportResistanceList(levelData) {
  const listEl = getEl("sr-level-list");
  if (!listEl) return;

  if (!levelData) {
    listEl.innerHTML = "<li>等待关键位分析</li>";
    return;
  }

  const supports = Array.isArray(levelData.supports) ? levelData.supports.slice(0, 2) : [];
  const resistances = Array.isArray(levelData.resistances) ? levelData.resistances.slice(0, 2) : [];
  const rows = [
    ...supports.map((item, idx) => ({
      kind: "support",
      label: `S${idx + 1}`,
      price: item.price,
      strength: item.strength,
    })),
    ...resistances.map((item, idx) => ({
      kind: "resistance",
      label: `R${idx + 1}`,
      price: item.price,
      strength: item.strength,
    })),
  ];

  if (!rows.length) {
    listEl.innerHTML = "<li>当前窗口未识别出稳定支撑/阻力</li>";
    return;
  }

  listEl.innerHTML = rows
    .map(
      (row) =>
        `<li class="${levelToneClass(row.kind)}">${escapeHtml(row.label)} · ¥${Number(
          row.price
        ).toFixed(2)} · 强度 ${Number(row.strength || 0)}</li>`
    )
    .join("");
}

function updateSupportResistance(levelData) {
  const supportEl = getEl("sr-nearest-support");
  const resistanceEl = getEl("sr-nearest-resistance");
  const roundLevelsEl = getEl("sr-round-levels");
  const currentPriceEl = getEl("sr-current-price");

  if (!supportEl || !resistanceEl || !roundLevelsEl || !currentPriceEl) {
    return;
  }

  if (!levelData) {
    currentPriceEl.textContent = "--";
    supportEl.textContent = "等待分析";
    resistanceEl.textContent = "等待分析";
    roundLevelsEl.textContent = "等待分析";
    renderSupportResistanceList(null);
    state.supportResistanceLines = [];
    if (typeof window.updateCandlestickSupportResistanceLines === "function") {
      window.updateCandlestickSupportResistanceLines([]);
    }
    return;
  }

  currentPriceEl.textContent = formatPrice(levelData.current_price);

  const nearestSupport = levelData.nearest_support;
  const nearestResistance = levelData.nearest_resistance;

  supportEl.textContent = nearestSupport
    ? `¥${Number(nearestSupport.price).toFixed(2)} (${formatPctCompact(-Math.abs(Number(nearestSupport.distance_pct || 0)))})`
    : "暂无";
  resistanceEl.textContent = nearestResistance
    ? `¥${Number(nearestResistance.price).toFixed(2)} (+${Math.abs(Number(nearestResistance.distance_pct || 0)).toFixed(2)}%)`
    : "暂无";

  const roundLevels = Array.isArray(levelData.round_levels) ? levelData.round_levels : [];
  roundLevelsEl.textContent = roundLevels.length
    ? roundLevels
        .slice(Math.max(0, roundLevels.length - 5))
        .map((value) => `¥${Number(value).toFixed(0)}`)
        .join(" / ")
    : "暂无";

  renderSupportResistanceList(levelData);

  state.supportResistanceLines = Array.isArray(levelData.plot_lines) ? levelData.plot_lines : [];
  if (typeof window.updateCandlestickSupportResistanceLines === "function") {
    window.updateCandlestickSupportResistanceLines(state.supportResistanceLines);
  }
}

function renderCustomAlertList(items) {
  const listEl = getEl("custom-alert-list");
  if (!listEl) return;

  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) {
    listEl.innerHTML = "<li>暂无自定义预警</li>";
    return;
  }

  listEl.innerHTML = rows
    .map((row) => {
      const enabledText = row.enabled ? "启用" : "停用";
      const channels = Array.isArray(row.channels) ? row.channels.join("/") : "system";
      const threshold = formatAlertThreshold(row.rule_type, row.threshold);
      return `<li data-alert-id="${row.id}">
        #${Number(row.id)} · ${escapeHtml(row.name)} · ${escapeHtml(
          prettifyAlertType(row.rule_type)
        )} ${escapeHtml(threshold)}
        · 冷却 ${Number(row.cooldown_minutes)}m · ${escapeHtml(channels)} · ${escapeHtml(enabledText)}
        <button data-action="toggle" data-id="${row.id}" data-enabled="${row.enabled}">${row.enabled ? "停用" : "启用"}</button>
        <button data-action="delete" data-id="${row.id}">删除</button>
      </li>`;
    })
    .join("");
}

function renderAlertDeliveryList(items) {
  const listEl = getEl("alert-delivery-list");
  if (!listEl) return;

  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) {
    listEl.innerHTML = "<li>暂无发送日志</li>";
    return;
  }

  listEl.innerHTML = rows
    .map((row) => {
      const createdAt = row.created_at ? new Date(row.created_at).toLocaleString() : "--";
      const statusClass = row.status === "success" ? "delivery-success" : "delivery-failed";
      const errorText = row.error_message ? ` · ${escapeHtml(row.error_message)}` : "";
      return `<li class="${statusClass}">
        ${escapeHtml(createdAt)} · ${escapeHtml(row.channel)} · ${escapeHtml(
          row.status
        )} · #${escapeHtml(row.rule_name)}
        · attempt ${Number(row.attempt)}/${Number(row.max_attempts)}${errorText}
      </li>`;
    })
    .join("");
}

async function loadAlertDeliveries(signal) {
  const stateEl = getEl("alert-delivery-state");
  const channelEl = getEl("alert-delivery-channel");
  const statusEl = getEl("alert-delivery-status-filter");
  const limitEl = getEl("alert-delivery-limit");

  const channel = channelEl?.value?.trim() || "";
  const status = statusEl?.value?.trim() || "";
  const limitRaw = Number(limitEl?.value || 30);
  const limit = Number.isFinite(limitRaw) ? Math.min(200, Math.max(1, limitRaw)) : 30;

  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (channel) params.set("channel", channel);
  if (status) params.set("status", status);

  try {
    const payload = await fetchJSON(`/api/alerts/deliveries?${params.toString()}`, signal);
    renderAlertDeliveryList(payload.items || []);
    if (stateEl) {
      stateEl.textContent = `已加载 ${Array.isArray(payload.items) ? payload.items.length : 0} 条发送记录`;
    }
  } catch (error) {
    if (error?.name === "AbortError") return;
    renderAlertDeliveryList([]);
    if (stateEl) {
      stateEl.textContent = "加载发送日志失败";
    }
  }
}

function updateMacroCorrelation(panelData) {
  const domesticEl = getEl("macro-domestic-price");
  const globalEl = getEl("macro-global-price");
  const premiumEl = getEl("macro-premium");
  const corrEl = getEl("macro-corr");
  const usdCloseEl = getEl("macro-usd-close");
  const usdChangeEl = getEl("macro-usd-change");
  const hintEl = getEl("macro-hint");

  if (
    !domesticEl ||
    !globalEl ||
    !premiumEl ||
    !corrEl ||
    !usdCloseEl ||
    !usdChangeEl ||
    !hintEl
  ) {
    return;
  }

  if (!panelData) {
    domesticEl.textContent = "--";
    globalEl.textContent = "--";
    premiumEl.textContent = "--";
    corrEl.textContent = "--";
    usdCloseEl.textContent = "--";
    usdChangeEl.textContent = "--";
    hintEl.textContent = "宏观关联数据暂不可用";
    return;
  }

  domesticEl.textContent = formatPrice(panelData.domestic_latest_cny_per_gram);
  globalEl.textContent = formatPrice(panelData.global_latest_cny_per_gram);
  premiumEl.textContent =
    panelData.premium_cny_per_gram == null
      ? "--"
      : `${formatSignedNumber(panelData.premium_cny_per_gram, 2)} (${formatPctCompact(panelData.premium_pct)})`;
  corrEl.textContent =
    panelData.domestic_global_return_corr == null && panelData.domestic_global_corr == null
      ? "--"
      : Number(panelData.domestic_global_return_corr ?? panelData.domestic_global_corr).toFixed(3);
  usdCloseEl.textContent =
    panelData.usd_proxy?.close == null ? "--" : Number(panelData.usd_proxy.close).toFixed(4);
  usdChangeEl.textContent = formatPctCompact(panelData.usd_proxy?.change_pct);
  const sampleNote =
    panelData.sample_count == null
      ? ""
      : ` · 样本 ${Number(panelData.sample_count)} · ${panelData.correlation_basis || "return_pct"}`;
  hintEl.textContent = `${panelData.macro_hint || "暂无宏观提示"}${sampleNote}`;
}

function prettifyAlignment(alignment) {
  const mapping = {
    bullish_aligned: "偏多共振",
    bearish_aligned: "偏空共振",
    mixed: "分歧震荡",
    insufficient_data: "样本不足",
  };
  return mapping[alignment] || alignment || "--";
}

function updateMultiTimeframe(panelData) {
  const alignmentEl = getEl("timeframe-alignment");
  const scoreEl = getEl("timeframe-score");
  const listEl = getEl("timeframe-list");
  const summaryEl = getEl("timeframe-summary");
  if (!alignmentEl || !scoreEl || !listEl || !summaryEl) return;

  if (!panelData) {
    alignmentEl.textContent = "--";
    scoreEl.textContent = "--";
    listEl.innerHTML = "<li>暂无多周期数据</li>";
    summaryEl.textContent = "等待多周期分析";
    return;
  }

  alignmentEl.textContent = prettifyAlignment(panelData.alignment);
  scoreEl.textContent =
    panelData.alignment_score == null ? "--" : Number(panelData.alignment_score).toFixed(3);
  summaryEl.textContent = panelData.summary || "暂无多周期提示";

  const rows = Array.isArray(panelData.frames) ? panelData.frames : [];
  if (!rows.length) {
    listEl.innerHTML = "<li>暂无多周期数据</li>";
    return;
  }

  listEl.innerHTML = rows
    .map((row) => {
      return `<li>${Number(row.window_days)}天 · ${escapeHtml(row.trend)} · 收益 ${formatPctCompact(
        row.return_pct
      )} · 波动 ${formatPctCompact(row.volatility_pct)}</li>`;
    })
    .join("");
}

function updateForecast(panelData) {
  const currentEl = getEl("forecast-current");
  const expectedEl = getEl("forecast-expected");
  const probEl = getEl("forecast-prob-up");
  const rangeEl = getEl("forecast-range");
  const scenarioEl = getEl("forecast-scenario");
  const confidenceEl = getEl("forecast-confidence");
  if (!currentEl || !expectedEl || !probEl || !rangeEl || !scenarioEl || !confidenceEl) return;

  if (!panelData) {
    currentEl.textContent = "--";
    expectedEl.textContent = "--";
    probEl.textContent = "--";
    rangeEl.textContent = "--";
    scenarioEl.textContent = "等待预测情景分析";
    confidenceEl.textContent = "等待预测可信度评估";
    return;
  }

  currentEl.textContent = formatPrice(panelData.current_price);
  expectedEl.textContent = `${formatPrice(panelData.expected_price)} (${formatPctCompact(
    panelData.expected_change_pct
  )})`;
  probEl.textContent = formatPctCompact(panelData.probability_up_pct);

  const lower = panelData.forecast_range?.lower;
  const upper = panelData.forecast_range?.upper;
  rangeEl.textContent =
    lower == null || upper == null ? "--" : `${formatPrice(lower)} ~ ${formatPrice(upper)}`;

  const scenario = panelData.scenario || {};
  scenarioEl.textContent = `P10/P50/P90: ${formatPrice(scenario.p10)} / ${formatPrice(
    scenario.p50
  )} / ${formatPrice(scenario.p90)}；+5%约需 ${scenario.days_to_gain_5pct ?? "--"} 天`;

  const confidence = panelData.confidence || {};
  const levelMap = {
    insufficient: "样本不足",
    low: "低可信",
    medium: "中可信",
    high: "高可信",
  };
  const level = levelMap[confidence.level] || "可信度待定";
  const sampleCount =
    confidence.sample_count ?? panelData.sample_count ?? panelData.lookback_sample_count;
  const basis = confidence.basis_interval || panelData.basis_interval || "1d";
  confidenceEl.textContent = `${level} · 样本 ${sampleCount ?? "--"} · 基准 ${basis} · ${
    confidence.reason || "预测结果仅用于辅助判断"
  }`;
}

function renderEntryPlan(planData) {
  const summaryEl = getEl("entry-plan-summary");
  const listEl = getEl("entry-plan-list");
  const triggerStatusEl = getEl("entry-trigger-status");
  const triggerListEl = getEl("entry-trigger-list");
  if (!summaryEl || !listEl || !triggerStatusEl || !triggerListEl) return;

  if (!planData) {
    summaryEl.textContent = "等待生成入场计划";
    triggerStatusEl.textContent = "等待条件触发判断";
    triggerListEl.innerHTML = "<li>暂无触发条件</li>";
    listEl.innerHTML = "<li>暂无入场计划</li>";
    return;
  }

  const summary = planData.summary || {};
  const gate = planData.execution_gate || {};
  const conditional = planData.conditional_triggers || {};
  const gateMessage = gate.message || "请结合当前建议决定是否执行。";
  const statusMap = {
    armed: "条件已满足",
    waiting: "等待触发",
    blocked: "暂不执行",
    unavailable: "不可用",
  };
  triggerStatusEl.textContent = `${statusMap[conditional.status] || "等待触发"} · ${
    conditional.next_action || "请等待触发条件满足。"
  }`;
  const conditions = Array.isArray(conditional.conditions) ? conditional.conditions : [];
  triggerListEl.innerHTML = conditions.length
    ? conditions
        .map((item) => {
          const target =
            item.target_price == null ? "" : ` · 目标 ${formatPrice(item.target_price)}`;
          const distance =
            item.distance_pct == null ? "" : ` · 距离 ${formatPctCompact(item.distance_pct)}`;
          return `<li>${escapeHtml(item.label)} · ${escapeHtml(item.status)}${target}${distance} · ${escapeHtml(
            item.description
          )}</li>`;
        })
        .join("")
    : "<li>暂无触发条件</li>";
  summaryEl.textContent = `${gateMessage} · 均价 ${formatPrice(summary.avg_entry_price)} · 止损 ${formatPrice(
    summary.stop_loss_price
  )} · 目标 ${formatPrice(summary.target_price)} · 盈亏比 ${summary.risk_reward_ratio ?? "--"}`;

  const rows = Array.isArray(planData.plan) ? planData.plan : [];
  if (!rows.length) {
    listEl.innerHTML = "<li>暂无入场计划</li>";
    return;
  }

  listEl.innerHTML = rows
    .map((row) => {
      const budget = row.budget_cny == null ? "" : ` · 预算 ¥${Number(row.budget_cny).toFixed(2)}`;
      const qty = row.quantity_gram == null ? "" : ` · 约 ${Number(row.quantity_gram).toFixed(3)}g`;
      return `<li>第${Number(row.batch)}批 · ${escapeHtml(row.status || "waiting")} · 买入价 ${formatPrice(row.buy_price)}${escapeHtml(
        budget
      )}${escapeHtml(qty)} · ${escapeHtml(row.trigger_condition || "条件满足后执行")}</li>`;
    })
    .join("");
}

function updateWeeklyReport(panelData) {
  const summaryEl = getEl("weekly-report-summary");
  const priceEl = getEl("weekly-report-price");
  const adviceEl = getEl("weekly-report-advice");
  const focusEl = getEl("weekly-report-focus");
  if (!summaryEl || !priceEl || !adviceEl || !focusEl) return;

  if (!panelData) {
    summaryEl.textContent = "等待生成周报";
    priceEl.textContent = "--";
    adviceEl.textContent = "--";
    focusEl.innerHTML = "<li>等待下周关注点</li>";
    return;
  }

  const price = panelData.price || {};
  const advice = panelData.advice || {};
  const sourceQuality = panelData.source_quality || {};
  summaryEl.textContent = `近 ${Number(panelData.period_days || 7)} 天 · 数据源 ${
    sourceQuality.confidence_level || "unknown"
  } · 样本 ${Number(price.sample_count || 0)}`;
  priceEl.textContent = `${formatPrice(price.end_price)} (${formatPctCompact(price.change_pct)})`;
  adviceEl.textContent = advice.recommendation || "暂无建议";
  const focusItems = Array.isArray(panelData.next_week_focus) ? panelData.next_week_focus : [];
  focusEl.innerHTML = focusItems.length
    ? focusItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
    : "<li>暂无下周关注点</li>";
}

async function loadEntryPlan(signal) {
  const budgetEl = getEl("entry-budget");
  const batchesEl = getEl("entry-batches");
  const stepEl = getEl("entry-step");
  const targetEl = getEl("entry-target");

  const params = new URLSearchParams();
  const budget = Number(budgetEl?.value);
  const batches = Number(batchesEl?.value || 3);
  const step = Number(stepEl?.value || 2);
  const target = Number(targetEl?.value || 5);

  if (Number.isFinite(budget) && budget > 0) {
    params.set("budget_cny", String(budget));
  }
  if (Number.isFinite(batches)) params.set("batches", String(batches));
  if (Number.isFinite(step)) params.set("step_pct", String(step));
  if (Number.isFinite(target)) params.set("target_profit_pct", String(target));

  try {
    const payload = await fetchJSON(`/api/analysis/entry-plan?${params.toString()}`, signal);
    renderEntryPlan(payload.data || null);
  } catch (error) {
    if (error?.name === "AbortError") return;
    renderEntryPlan(null);
  }
}

async function loadCustomAlerts(signal) {
  const statusEl = getEl("custom-alert-status");
  try {
    const payload = await fetchJSON("/api/alerts", signal);
    renderCustomAlertList(payload.items || []);
    if (statusEl) {
      statusEl.textContent = `已加载 ${Array.isArray(payload.items) ? payload.items.length : 0} 条预警规则`;
    }
  } catch (error) {
    if (error?.name === "AbortError") return;
    renderCustomAlertList([]);
    if (statusEl) {
      statusEl.textContent = "加载预警规则失败";
    }
  }
}

async function createCustomAlertRule() {
  const statusEl = getEl("custom-alert-status");
  const nameEl = getEl("alert-name");
  const typeEl = getEl("alert-type");
  const thresholdEl = getEl("alert-threshold");
  const cooldownEl = getEl("alert-cooldown");
  const channelsEl = getEl("alert-channels");

  if (!nameEl || !typeEl || !thresholdEl || !cooldownEl || !channelsEl) return;

  const name = nameEl.value.trim();
  const ruleType = typeEl.value;
  const threshold = Number(thresholdEl.value);
  const cooldown = Number(cooldownEl.value || 60);
  const channels = channelsEl.value.trim() || "system";

  if (!name || !Number.isFinite(threshold)) {
    if (statusEl) statusEl.textContent = "请填写合法规则名和阈值";
    return;
  }

  const url = `/api/alerts?name=${encodeURIComponent(name)}&rule_type=${encodeURIComponent(
    ruleType
  )}&threshold=${encodeURIComponent(String(threshold))}&cooldown_minutes=${encodeURIComponent(
    String(cooldown)
  )}&channels=${encodeURIComponent(channels)}&enabled=true`;

  try {
    const response = await fetch(url, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload?.error?.message || "创建失败");
    }
    if (statusEl) statusEl.textContent = `已创建规则 #${payload.data.id}`;
    nameEl.value = "";
    thresholdEl.value = "";
    await loadCustomAlerts();
  } catch (error) {
    if (statusEl) statusEl.textContent = `创建失败: ${error?.message || error}`;
  }
}

async function toggleCustomAlertRule(ruleId, enabled) {
  const statusEl = getEl("custom-alert-status");
  try {
    const response = await fetch(`/api/alerts/${ruleId}?enabled=${enabled}`, { method: "PATCH" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload?.error?.message || "更新失败");
    }
    if (statusEl) statusEl.textContent = `规则 #${ruleId} 已${enabled ? "启用" : "停用"}`;
    await loadCustomAlerts();
  } catch (error) {
    if (statusEl) statusEl.textContent = `更新失败: ${error?.message || error}`;
  }
}

async function deleteCustomAlertRule(ruleId) {
  const statusEl = getEl("custom-alert-status");
  try {
    const response = await fetch(`/api/alerts/${ruleId}`, { method: "DELETE" });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(payload?.error?.message || "删除失败");
    }
    if (statusEl) statusEl.textContent = `规则 #${ruleId} 已删除`;
    await loadCustomAlerts();
  } catch (error) {
    if (statusEl) statusEl.textContent = `删除失败: ${error?.message || error}`;
  }
}

function bindCustomAlertPanel() {
  const form = getEl("custom-alert-form");
  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await createCustomAlertRule();
    });
  }

  const list = getEl("custom-alert-list");
  if (list) {
    list.addEventListener("click", async (event) => {
      const button = event.target;
      if (!(button instanceof HTMLButtonElement)) return;
      const action = button.dataset.action;
      const id = Number(button.dataset.id);
      if (!Number.isFinite(id)) return;

      if (action === "toggle") {
        const currentEnabled = button.dataset.enabled === "true";
        await toggleCustomAlertRule(id, !currentEnabled);
      } else if (action === "delete") {
        await deleteCustomAlertRule(id);
      }
    });
  }

  const deliveryRefresh = getEl("alert-delivery-refresh");
  if (deliveryRefresh) {
    deliveryRefresh.addEventListener("click", async () => {
      await loadAlertDeliveries();
    });
  }

  const deliveryFilterChannel = getEl("alert-delivery-channel");
  const deliveryFilterStatus = getEl("alert-delivery-status-filter");
  if (deliveryFilterChannel) {
    deliveryFilterChannel.addEventListener("change", async () => {
      await loadAlertDeliveries();
    });
  }
  if (deliveryFilterStatus) {
    deliveryFilterStatus.addEventListener("change", async () => {
      await loadAlertDeliveries();
    });
  }

  const entryPlanForm = getEl("entry-plan-form");
  if (entryPlanForm) {
    entryPlanForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      await loadEntryPlan();
    });
  }
}

function prettifyRiskFlag(flag) {
  const mapping = {
    falling_knife: "飞刀风险",
  };
  return mapping[flag] || flag;
}

function stripLeadingEmoji(text) {
  if (typeof text !== "string") return "";
  return text.replace(/^[\p{Extended_Pictographic}\uFE0F\u200D\s]+/u, "").trim();
}

function prettifyRegime(regime) {
  const mapping = {
    risk_off_falling_knife: "风险关闭 · 飞刀",
    confirmed_reversal: "确认反转",
    tentative_reversal: "弱确认反转",
    reversal_watch: "反转观察",
    trend_following_up: "顺势偏多",
    neutral_chop: "震荡中性",
  };
  return mapping[regime] || regime || "等待分析";
}

function formatBasisPoints(value) {
  const numeric = value == null ? Number.NaN : Number(value);
  if (!Number.isFinite(numeric)) return "--";
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(1)} bp`;
}

function formatPositionSize(value) {
  const numeric = value == null ? Number.NaN : Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return `${numeric.toFixed(1)}%`;
}

function getRecommendationToneClass(recommendation) {
  if (recommendation === "强烈推荐买入" || recommendation === "推荐买入") {
    return "market-buy";
  }
  if (recommendation === "观望") {
    return "market-hold";
  }
  return "market-risk";
}

function getRiskToneClass(flag) {
  if (flag === "falling_knife") {
    return "risk-danger";
  }
  return "risk-watch";
}

function prettifySetupFlag(flag) {
  const mapping = {
    extreme_oversold: "极度超卖",
    oversold: "超卖",
    mild_oversold: "轻度超卖",
    band_break: "跌破下轨",
    below_ma: "低于均线",
  };
  return mapping[flag] || flag;
}

function prettifyConfirmationFlag(flag) {
  const mapping = {
    macd_stabilizing: "MACD 稳定",
    macd_contracting: "MACD 收敛",
    momentum_turn: "动量转强",
    selling_pressure_easing: "卖压趋缓",
    trend_pressure_not_extreme: "趋势压力缓和",
  };
  return mapping[flag] || flag;
}

function setFlagList(container, flags, toneClass, formatter) {
  if (!container) return;

  const items = Array.isArray(flags) ? flags : [];
  if (!items.length) {
    container.innerHTML = '<span class="debug-flag debug-empty">无</span>';
    return;
  }

  container.innerHTML = items
    .map((flag) => `<span class="debug-flag ${toneClass}">${escapeHtml(formatter(flag))}</span>`)
    .join("");
}

function formatExplainabilityTime(value) {
  if (!value) return "暂无历史变化";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? "暂无历史变化" : timestamp.toLocaleString();
}

function buildChartStatusFromMeta(chartType, meta) {
  if (!meta) {
    return {
      label: "等待分析",
      detail: "正在加载图表状态说明。",
    };
  }

  if (meta.returned_points === 0) {
    return {
      label: "暂无有效数据",
      detail: "当前没有足够的连续有效价格可用于绘图。",
    };
  }

  if (meta.regime_filtered) {
    return {
      label: "已切换当前有效价格段",
      detail:
        chartType === "line"
          ? "折线图已剔除旧异常价格段，出现时间断点属于预期行为。"
          : "K线图仅基于当前连续有效价格段聚合，旧异常价格段已被剔除。",
    };
  }

  return {
    label: chartType === "line" ? "连续价格段" : "连续K线段",
    detail:
      chartType === "line"
        ? "折线图当前展示的是一段连续有效价格，没有检测到异常断层。"
        : "K线图基于当前连续有效价格段聚合，当前形态可直接参与分析。",
  };
}

function updateSingleChartStatus(chartType, status) {
  const labelEl = getEl(chartType === "line" ? "line-chart-status" : "candlestick-chart-status");
  const detailEl = getEl(chartType === "line" ? "line-chart-detail" : "candlestick-chart-detail");

  if (!labelEl || !detailEl) return;

  labelEl.textContent = status?.label || "等待分析";
  detailEl.textContent = status?.detail || "正在加载图表状态说明。";
}

function parseIntervalToMs(interval) {
  if (typeof interval !== "string") return null;
  const match = interval.trim().toLowerCase().match(/^(\d+)([mhd])$/);
  if (!match) return null;

  const value = Number(match[1]);
  const unit = match[2];
  const multiplier = unit === "m" ? 60_000 : unit === "h" ? 3_600_000 : 86_400_000;
  return value * multiplier;
}

function countMissingBuckets(items, interval) {
  const intervalMs = parseIntervalToMs(interval);
  if (!intervalMs || !Array.isArray(items) || items.length < 2) return 0;

  let missingBuckets = 0;
  for (let i = 1; i < items.length; i += 1) {
    const previous = new Date(items[i - 1].timestamp).getTime();
    const current = new Date(items[i].timestamp).getTime();
    if (!Number.isFinite(previous) || !Number.isFinite(current) || current <= previous) {
      continue;
    }
    const bucketsBetween = Math.round((current - previous) / intervalMs) - 1;
    if (bucketsBetween > 0) {
      missingBuckets += bucketsBetween;
    }
  }
  return missingBuckets;
}

function formatSignedPercent(value, digits = 1) {
  if (!Number.isFinite(value)) return null;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

function calculatePercentChange(start, end) {
  if (!Number.isFinite(start) || !Number.isFinite(end) || start === 0) return null;
  return ((end - start) / start) * 100;
}

function summarizeLineTrend(changePct) {
  if (!Number.isFinite(changePct)) {
    return {
      state: "趋势待定",
      detail: "样本数量还不够，暂时无法判断价格主线的方向性。",
    };
  }

  if (changePct >= 1.8) {
    return {
      state: "偏强上行",
      detail: `最近一段价格抬升 ${formatSignedPercent(changePct)}，说明买盘在主动抬高成交中枢。`,
    };
  }
  if (changePct >= 0.5) {
    return {
      state: "温和上行",
      detail: `最近一段价格上涨 ${formatSignedPercent(changePct)}，高低点都在缓慢上移。`,
    };
  }
  if (changePct <= -1.8) {
    return {
      state: "偏弱下行",
      detail: `最近一段价格回落 ${formatSignedPercent(changePct)}，空头仍在压低短线重心。`,
    };
  }
  if (changePct <= -0.5) {
    return {
      state: "回落承压",
      detail: `最近一段价格回落 ${formatSignedPercent(changePct)}，反弹力度暂时还不足以扭转节奏。`,
    };
  }

  return {
    state: "窄幅整理",
    detail: `最近一段价格变化仅 ${formatSignedPercent(changePct)}，更像在等待新的方向选择。`,
  };
}

function summarizeRangePosition(price, low, high) {
  if (!Number.isFinite(price) || !Number.isFinite(low) || !Number.isFinite(high) || high <= low) {
    return {
      state: "区间待定",
      detail: "最近区间样本不足，暂时无法判断价格靠近支撑还是阻力。",
    };
  }

  const position = (price - low) / (high - low);
  if (position >= 0.8) {
    return {
      state: "区间高位",
      detail: "最新价已经逼近最近一段区间上沿，接下来要重点观察能否把上方抛压真正吃掉。",
    };
  }
  if (position <= 0.2) {
    return {
      state: "区间低位",
      detail: "最新价贴近最近一段区间下沿，当前位置更像在测试下方承接是否稳固。",
    };
  }

  return {
    state: "区间中部",
    detail: "最新价仍在最近一段区间中部，多空暂时都没有形成决定性突破。",
  };
}

function summarizeMovingAverageRelation(price, ma30) {
  if (!Number.isFinite(price) || !Number.isFinite(ma30)) {
    return "MA30 仍在预热，暂时只能先看主线方向，不能用中期均线判断支撑阻力。";
  }

  const deviationPct = calculatePercentChange(ma30, price);
  if (!Number.isFinite(deviationPct)) {
    return "MA30 数据异常，暂时跳过均线位置判断。";
  }

  if (deviationPct >= 1.5) {
    return `价格运行在 MA30 上方 ${deviationPct.toFixed(1)}%，说明中期成本区仍在为上涨提供支撑。`;
  }
  if (deviationPct >= 0) {
    return `价格仍站在 MA30 上方 ${deviationPct.toFixed(1)}%，当前走势还没有跌回中期成本线以下。`;
  }
  if (deviationPct <= -1.5) {
    return `价格落在 MA30 下方 ${Math.abs(deviationPct).toFixed(1)}%，反弹还没有收复中期趋势线。`;
  }

  return "价格正围绕 MA30 反复拉锯，下一次放量离开均线往往会决定短线方向。";
}

function summarizeBollingerRelation(price, upper, middle, lower) {
  if (
    !Number.isFinite(price) ||
    !Number.isFinite(upper) ||
    !Number.isFinite(middle) ||
    !Number.isFinite(lower) ||
    upper <= lower
  ) {
    return "布林带还在预热，暂时不评价价格处于扩张还是回归阶段。";
  }

  const bandSpan = upper - lower;
  const position = (price - lower) / bandSpan;

  if (position >= 0.92) {
    return "价格已经贴近布林上轨，说明上攻很强，但也意味着短线更容易出现高位震荡。";
  }
  if (position >= 0.65) {
    return "价格运行在布林中上轨之间，节奏偏强，但还没到明显过热的位置。";
  }
  if (position <= 0.08) {
    return "价格已经压到布林下轨附近，当前位置更适合观察是止跌承接还是继续破位。";
  }
  if (position <= 0.35) {
    return "价格运行在布林中下轨之间，整体仍偏弱，反弹需要进一步确认。";
  }

  return "价格大体围绕布林中轨震荡，市场当前更像在消化前一段波动。";
}

function buildLineChartContext(items, interval) {
  const points = Array.isArray(items) ? items : [];
  if (!points.length) {
    return {
      state: "数据不足",
      detail: "当前没有足够的折线图数据，暂时无法解读趋势、支撑和阻力关系。",
    };
  }

  const prices = points
    .map((item) => Number(item?.price_cny_per_gram))
    .filter((value) => Number.isFinite(value));
  if (prices.length < 2) {
    return {
      state: "样本偏少",
      detail: "折线图样本太少，暂时只能确认有数据，还无法判断趋势结构。",
    };
  }

  const missingBuckets = countMissingBuckets(points, interval);
  const recentWindowSize = Math.min(prices.length, 12);
  const recentWindow = prices.slice(-recentWindowSize);
  const recentChangePct = calculatePercentChange(recentWindow[0], recentWindow[recentWindow.length - 1]);
  const trendSummary = summarizeLineTrend(recentChangePct);

  const rangeWindow = prices.slice(-Math.min(prices.length, 20));
  const recentHigh = Math.max(...rangeWindow);
  const recentLow = Math.min(...rangeWindow);
  const latestPrice = prices[prices.length - 1];
  const rangeSummary = summarizeRangePosition(latestPrice, recentLow, recentHigh);

  const priceSeries = points.map((item) => {
    const price = Number(item?.price_cny_per_gram);
    return Number.isFinite(price) ? price : null;
  });
  const ma20Series = simpleMovingAverage(priceSeries, 20);
  const ma30Series = simpleMovingAverage(priceSeries, 30);
  const bands = bollingerBands(priceSeries, 20, 2);

  const detailParts = [
    trendSummary.detail,
    summarizeMovingAverageRelation(latestPrice, ma30Series[ma30Series.length - 1]),
    rangeSummary.detail,
    summarizeBollingerRelation(
      latestPrice,
      bands.upper[bands.upper.length - 1],
      ma20Series[ma20Series.length - 1],
      bands.lower[bands.lower.length - 1]
    ),
  ];

  if (missingBuckets > 0) {
    detailParts.push(
      `另外检测到 ${missingBuckets} 个时间桶缺口，这通常表示异常价段已被过滤，或该时段采样不连续。`
    );
  } else {
    detailParts.push("时间桶连续，这一段折线更适合直接用来判断趋势斜率和区间位置。");
  }

  return {
    state: `${trendSummary.state} · ${rangeSummary.state}`,
    detail: detailParts.join(" "),
  };
}

function averageCandlestickActivity(items) {
  const values = (Array.isArray(items) ? items : [])
    .map((item) => Number(item?.activity))
    .filter((value) => Number.isFinite(value));
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function classifyCandlestickActivity(item, items) {
  const activity = Number(item?.activity);
  const dataPoints = Number(item?.data_points);
  const baseline = averageCandlestickActivity((Array.isArray(items) ? items : []).slice(-6, -1));

  if (
    activity >= 8 ||
    dataPoints >= 20 ||
    (Number.isFinite(baseline) && activity >= baseline * 1.8)
  ) {
    return "高";
  }
  if (
    activity >= 2 ||
    dataPoints >= 8 ||
    (Number.isFinite(baseline) && activity >= baseline * 1.1)
  ) {
    return "中";
  }
  return "低";
}

function describeCandlestickStructure(item) {
  const open = Number(item?.open);
  const high = Number(item?.high);
  const low = Number(item?.low);
  const close = Number(item?.close);
  const range = high - low;

  if (
    !Number.isFinite(open) ||
    !Number.isFinite(high) ||
    !Number.isFinite(low) ||
    !Number.isFinite(close) ||
    range <= 0
  ) {
    return {
      state: "结构待定",
      detail: "这根 K 线的高低点信息不足，暂时不能判断是承接还是抛压占优。",
    };
  }

  const body = Math.abs(close - open);
  const upperWick = high - Math.max(open, close);
  const lowerWick = Math.min(open, close) - low;
  const bullish = close > open;
  const bearish = close < open;
  const bodyRatio = body / range;

  if (bullish && lowerWick >= body * 0.85 && lowerWick >= upperWick * 1.8) {
    return {
      state: "下探回收",
      detail: "下影明显长于上影，说明价格下探后被快速拉回，低位承接开始增强。",
    };
  }
  if (bearish && upperWick >= body * 0.85 && upperWick >= lowerWick * 1.8) {
    return {
      state: "冲高回落",
      detail: "上影明显长于下影，说明盘中拉高后卖压立即出现，高位承接偏弱。",
    };
  }
  if (bodyRatio >= 0.58) {
    return {
      state: bullish ? "阳线推进" : "阴线下压",
      detail: bullish
        ? "实体占据了本根 K 线的大部分波幅，说明这轮反弹更像主动推进。"
        : "实体占据了本根 K 线的大部分波幅，说明抛压仍在主导节奏。",
    };
  }
  if (body <= range * 0.18) {
    return {
      state: "震荡十字",
      detail: "实体很小，说明多空在这一根 K 线上还没有分出明显胜负。",
    };
  }

  return {
    state: bullish ? "温和反弹" : "弱势回落",
    detail: bullish
      ? "这根 K 线收阳，但实体不算特别坚决，更像试探性的回补。"
      : "这根 K 线收阴，但上下影都不短，说明空头虽然占优，仍有反复拉扯。",
  };
}

function describeCandlestickSequence(items) {
  const candles = Array.isArray(items) ? items.slice(-3) : [];
  if (candles.length < 2) {
    return "最近可参考的 K 线不多，暂时先以最新一根的形态为主。";
  }

  const bullishCount = candles.filter((item) => Number(item?.close) > Number(item?.open)).length;
  const bearishCount = candles.filter((item) => Number(item?.close) < Number(item?.open)).length;
  const latestClose = Number(candles[candles.length - 1]?.close);
  const previousClose = Number(candles[candles.length - 2]?.close);

  if (bullishCount >= 2 && latestClose > previousClose) {
    return "最近 3 根里多头开始占优，短线反弹已经不只是单根 K 线的孤立动作。";
  }
  if (bearishCount >= 2 && latestClose < previousClose) {
    return "最近 3 根里空头仍占优势，即便有反抽，也更像下跌中的修复。";
  }

  return "最近几根 K 线多空拉锯明显，市场仍在确认下一段是延续还是反转。";
}

function describeCandlestickBreakout(items) {
  const candles = Array.isArray(items) ? items : [];
  if (candles.length < 2) {
    return "历史 K 线还不够，暂时不判断是否在试图突破前高或跌破前低。";
  }

  const latest = candles[candles.length - 1];
  const previous = candles.slice(Math.max(0, candles.length - 6), -1);
  const previousHigh = Math.max(...previous.map((item) => Number(item?.high)).filter(Number.isFinite));
  const previousLow = Math.min(...previous.map((item) => Number(item?.low)).filter(Number.isFinite));
  const latestHigh = Number(latest?.high);
  const latestLow = Number(latest?.low);
  const latestClose = Number(latest?.close);

  if (!Number.isFinite(previousHigh) || !Number.isFinite(previousLow)) {
    return "历史波动区间不足，暂时不判断突破与否。";
  }
  if (latestClose > previousHigh) {
    return "收盘价已经站上前一段 K 线高点，后续只要活跃度不掉，向上突破就更容易成立。";
  }
  if (latestHigh > previousHigh && latestClose <= previousHigh) {
    return "盘中曾经上探前高，但收盘没有稳住，说明上方抛压还没有完全被消化。";
  }
  if (latestClose < previousLow) {
    return "收盘价已经跌破前一段 K 线低点，空头正在把波动区间继续往下推。";
  }
  if (latestLow < previousLow && latestClose >= previousLow) {
    return "盘中跌破前低后被拉回，说明下方开始出现主动承接，而不是单边失守。";
  }

  return "最新 K 线仍在最近几根的震荡区间内，市场更像在为下一次突破蓄势。";
}

function describeCandlestickParticipation(item, items, activityLevel) {
  const activity = Number(item?.activity);
  const averageActivity = averageCandlestickActivity((Array.isArray(items) ? items : []).slice(-6, -1));

  if (activityLevel === "高") {
    if (Number.isFinite(averageActivity) && Number.isFinite(activity)) {
      return `活跃度高，明显高于最近均值，这意味着这根 K 线背后有更强的参与和换手。`;
    }
    return "活跃度高，说明这根 K 线的波动和成交参与都更值得重视。";
  }
  if (activityLevel === "中") {
    return "活跃度中等，当前形态有参考价值，但还不足以单独定义趋势。";
  }
  return "活跃度偏低，当前 K 线更像试探，后续最好等待更多跟随确认。";
}

function buildCandlestickChartContext(items, interval) {
  const candles = Array.isArray(items) ? items : [];
  if (!candles.length) {
    return {
      state: "等待K线数据",
      detail: "切换到 K 线图并成功加载数据后，这里会解读最新结构、动能和承接/抛压变化。",
    };
  }

  const latest = candles[candles.length - 1];
  const missingBuckets = countMissingBuckets(candles, interval);
  const activityLevel = classifyCandlestickActivity(latest, candles);
  const structure = describeCandlestickStructure(latest);

  const detailParts = [
    `最新一根 K 线呈现${structure.state}，${structure.detail}`,
    describeCandlestickSequence(candles),
    describeCandlestickParticipation(latest, candles, activityLevel),
    describeCandlestickBreakout(candles),
  ];

  if (missingBuckets > 0) {
    detailParts.push(
      `另外检测到 ${missingBuckets} 个 K 线时间桶缺口，通常表示该时段无有效数据或异常价段已被过滤。`
    );
  } else {
    detailParts.push("K 线时间桶连续，这组形态可以直接用来观察承接、抛压和区间突破。");
  }

  return {
    state: `${structure.state} · 活跃度${activityLevel}`,
    detail: detailParts.join(" "),
  };
}

function updateChartDiagnostics() {
  const lineStateEl = getEl("line-chart-status");
  const lineDetailEl = getEl("line-chart-detail");
  const candlestickStateEl = getEl("candlestick-chart-status");
  const candlestickDetailEl = getEl("candlestick-chart-detail");

  if (!lineStateEl || !lineDetailEl || !candlestickStateEl || !candlestickDetailEl) {
    return;
  }

  const lineContext = state.lineChartContext || {
    state: "等待分析",
    detail: "折线图解读会在历史数据加载后显示。",
  };
  const candlestickContext = state.candlestickChartContext || {
    state: "等待分析",
    detail: "切换到 K 线图后会补充最新形态解读。",
  };

  lineStateEl.textContent = lineContext.state;
  lineDetailEl.textContent = lineContext.detail;
  candlestickStateEl.textContent = candlestickContext.state;
  candlestickDetailEl.textContent = candlestickContext.detail;
}

function updateSignalDebug(evaluation) {
  const entryStatusEl = getEl("debug-entry-status");
  const confidenceEl = getEl("debug-confidence");
  const dominantFactorEl = getEl("debug-dominant-factor");
  const regimeEl = getEl("debug-regime");
  const expectedReturnEl = getEl("debug-expected-return");
  const positionSizeEl = getEl("debug-position-size");
  const changeReasonEl = getEl("debug-change-reason");
  const previousAdviceEl = getEl("debug-previous-advice");
  const changeTimeEl = getEl("debug-change-time");
  const factorChangesEl = getEl("debug-factor-changes");
  const setupFlagsEl = getEl("debug-setup-flags");
  const confirmationFlagsEl = getEl("debug-confirmation-flags");
  const riskFlagsEl = getEl("debug-risk-flags");
  const reasonsEl = getEl("debug-reasons");

  if (
    !entryStatusEl ||
    !confidenceEl ||
    !dominantFactorEl ||
    !regimeEl ||
    !expectedReturnEl ||
    !positionSizeEl ||
    !changeReasonEl ||
    !previousAdviceEl ||
    !changeTimeEl ||
    !factorChangesEl ||
    !setupFlagsEl ||
    !confirmationFlagsEl ||
    !riskFlagsEl ||
    !reasonsEl
  ) {
    return;
  }

  if (!evaluation) {
    entryStatusEl.textContent = "等待分析";
    confidenceEl.textContent = "--";
    dominantFactorEl.textContent = "等待分析";
    regimeEl.textContent = "等待分析";
    expectedReturnEl.textContent = "--";
    positionSizeEl.textContent = "--";
    changeReasonEl.textContent = "暂无建议变化记录。";
    previousAdviceEl.textContent = "无历史记录";
    changeTimeEl.textContent = "暂无历史变化";
    factorChangesEl.innerHTML = "<li>当前暂无足够数据展示建议切换因子。</li>";
    setFlagList(setupFlagsEl, [], "debug-setup", prettifySetupFlag);
    setFlagList(confirmationFlagsEl, [], "debug-confirmation", prettifyConfirmationFlag);
    setFlagList(riskFlagsEl, [], "debug-risk", prettifyRiskFlag);
    reasonsEl.innerHTML = "<li>当前暂无足够数据生成判断细节。</li>";
    return;
  }

  const explainability = evaluation.explainability || {};
  entryStatusEl.textContent = evaluation.entry_ready
    ? "确认通过"
    : evaluation.entry_weak
      ? "弱确认可试探"
      : "暂不入场";
  confidenceEl.textContent = Number.isFinite(evaluation.confidence)
    ? `${Math.round(evaluation.confidence * 100)}%`
    : "--";
  dominantFactorEl.textContent = evaluation.dominant_factor || "多因子共同作用";
  regimeEl.textContent = prettifyRegime(evaluation.regime);
  expectedReturnEl.textContent = formatBasisPoints(evaluation.expected_return_bp);
  positionSizeEl.textContent = formatPositionSize(evaluation.suggested_position_pct);
  changeReasonEl.textContent =
    explainability.summary ||
    evaluation.recommendation_change_reason ||
    "建议未发生明显变化。";
  previousAdviceEl.textContent = explainability.previous_advice || "无历史记录";
  changeTimeEl.textContent = formatExplainabilityTime(explainability.changed_at);
  const factorChanges = Array.isArray(explainability.factor_changes)
    ? explainability.factor_changes.slice(0, 4)
    : [];
  factorChangesEl.innerHTML = factorChanges.length
    ? factorChanges.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
    : "<li>本次建议变化暂无足够关键因子差异可展示。</li>";
  setFlagList(setupFlagsEl, evaluation.setup_flags, "debug-setup", prettifySetupFlag);
  setFlagList(
    confirmationFlagsEl,
    evaluation.confirmation_flags,
    "debug-confirmation",
    prettifyConfirmationFlag
  );
  setFlagList(riskFlagsEl, evaluation.risk_flags, "debug-risk", prettifyRiskFlag);

  const reasons = Array.isArray(evaluation.reasons) ? evaluation.reasons.slice(0, 4) : [];
  reasonsEl.innerHTML = reasons.length
    ? reasons.map((reason) => `<li>${escapeHtml(stripLeadingEmoji(reason))}</li>`).join("")
    : "<li>当前暂无额外判断依据。</li>";

  updateChartDiagnostics();
}

function updateMarketBrief(advice) {
  const recommendationEl = getEl("market-recommendation");
  const stateEl = getEl("market-state");
  const scoreEl = getEl("market-score");
  const riskSummaryEl = getEl("market-risk-summary");
  const riskFlagsEl = getEl("market-risk-flags");
  const actionLabelEl = getEl("market-action-label");
  const actionDetailEl = getEl("market-action-detail");
  const insightsEl = getEl("market-insights");

  if (
    !recommendationEl ||
    !stateEl ||
    !scoreEl ||
    !riskSummaryEl ||
    !riskFlagsEl ||
    !actionLabelEl ||
    !actionDetailEl ||
    !insightsEl
  ) {
    return;
  }

  if (!advice) {
    recommendationEl.textContent = "分析中";
    recommendationEl.className = "market-recommendation market-hold";
    stateEl.textContent = "建议数据暂不可用";
    scoreEl.textContent = "--";
    riskSummaryEl.textContent = "等待分析";
    riskFlagsEl.innerHTML = '<span class="risk-chip risk-safe">等待分析</span>';
    actionLabelEl.textContent = "等待建议";
    actionDetailEl.textContent = "当前操作建议将在分析完成后显示。";
    insightsEl.innerHTML = "<li>数据积累中，稍后将展示当前黄金状况。</li>";
    return;
  }

  const recommendation = advice.recommendation || "观望";
  recommendationEl.textContent = recommendation;
  recommendationEl.className = `market-recommendation ${getRecommendationToneClass(recommendation)}`;
  stateEl.textContent = advice.market_state || "市场状态正常";
  scoreEl.textContent = Number.isFinite(advice.score) ? `${advice.score}/100` : "--";

  const riskFlags = Array.isArray(advice.risk_flags) ? advice.risk_flags : [];
  if (riskFlags.length) {
    riskSummaryEl.textContent = riskFlags.map(prettifyRiskFlag).join(" / ");
    riskFlagsEl.innerHTML = riskFlags
      .map(
        (flag) =>
          `<span class="risk-chip ${getRiskToneClass(flag)}">${escapeHtml(prettifyRiskFlag(flag))}</span>`
      )
      .join("");
  } else {
    riskSummaryEl.textContent = "风险可控";
    riskFlagsEl.innerHTML = '<span class="risk-chip risk-safe">风险可控</span>';
  }

  actionLabelEl.textContent = advice.action_label || "继续观望";
  actionDetailEl.textContent =
    advice.action_detail || "等待更清晰的趋势与风险信号后，再决定是否行动。";

  const insightItems = Array.isArray(advice.insights) ? advice.insights.slice(0, 3) : [];
  insightsEl.innerHTML = insightItems.length
    ? insightItems.map((item) => `<li>${escapeHtml(stripLeadingEmoji(item))}</li>`).join("")
    : "<li>当前暂无额外分析洞察。</li>";
}

function showSignalAlert(data) {
  if (!data) return;
  const stateEl = getEl("signal-state");
  const reasonEl = getEl("signal-reason");
  if (stateEl) {
    stateEl.textContent = "触发买入信号";
    stateEl.classList.add("signal-live");
  }
  if (reasonEl) {
    const price = Number(data.price ?? data.price_cny_per_gram);
    const priceLabel = Number.isFinite(price) ? `价格 ¥${price.toFixed(2)}` : "检测到新信号";
    reasonEl.textContent = data.reason || priceLabel;
  }
}

function buildSupportResistanceDatasets(length, levelLines) {
  const lines = Array.isArray(levelLines) ? levelLines : [];
  const colorMap = {
    support: "rgba(47, 214, 198, 0.72)",
    resistance: "rgba(255, 143, 132, 0.74)",
    round: "rgba(242, 178, 76, 0.58)",
  };
  const dashMap = {
    support: [6, 4],
    resistance: [6, 4],
    round: [2, 4],
  };

  return lines.map((line) => {
    const price = Number(line?.price);
    const kind = line?.kind || "round";
    return {
      label: line?.label || kind,
      data: Array.from({ length }, () => (Number.isFinite(price) ? price : null)),
      borderColor: colorMap[kind] || colorMap.round,
      borderDash: dashMap[kind] || dashMap.round,
      borderWidth: 1,
      pointRadius: 0,
      tension: 0,
      order: 5,
    };
  });
}

function buildChart(labels, prices, ma30, bbUpper, bbLower, signalPoints, levelLines = []) {
  const canvas = getEl("priceChart");
  if (!canvas || typeof Chart === "undefined") {
    return;
  }

  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }

  const srDatasets = buildSupportResistanceDatasets(labels.length, levelLines);

  state.chart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "价格",
          data: prices,
          borderColor: "#f7be56",
          backgroundColor: "rgba(247, 190, 86, 0.18)",
          borderWidth: 2.2,
          pointRadius: 0,
          tension: 0.22,
          order: 1,
        },
        {
          label: "MA30",
          data: ma30,
          borderColor: "rgba(47, 214, 198, 0.88)",
          borderWidth: 1.6,
          pointRadius: 0,
          tension: 0.22,
          order: 2,
        },
        {
          label: "布林上轨",
          data: bbUpper,
          borderColor: "rgba(247, 190, 86, 0.56)",
          borderDash: [6, 6],
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.2,
          order: 3,
        },
        {
          label: "布林下轨",
          data: bbLower,
          borderColor: "rgba(247, 190, 86, 0.56)",
          borderDash: [6, 6],
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.2,
          order: 3,
        },
        ...srDatasets,
        {
          type: "scatter",
          label: "信号",
          data: signalPoints,
          borderColor: "#2fd6c6",
          backgroundColor: "#2fd6c6",
          pointRadius: 4,
          order: 10,
        },
      ],
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: "index",
        intersect: false,
      },
      plugins: {
        legend: {
          labels: {
            color: "#a7bbd5",
            boxWidth: 12,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: "#8fa6c2",
            maxTicksLimit: 6,
          },
          grid: {
            color: "rgba(84, 128, 172, 0.2)",
          },
        },
        y: {
          ticks: {
            color: "#8fa6c2",
          },
          grid: {
            color: "rgba(84, 128, 172, 0.2)",
          },
        },
      },
    },
  });
}

function calculate24hChange(items, latestPrice) {
  if (items.length < 2 || !Number.isFinite(latestPrice)) {
    return null;
  }

  const latestTime = new Date(items[items.length - 1].timestamp).getTime();
  const targetTime = latestTime - 24 * 60 * 60 * 1000;
  let pastItem = null;

  for (let i = items.length - 1; i >= 0; i -= 1) {
    const itemTime = new Date(items[i].timestamp).getTime();
    if (itemTime <= targetTime) {
      pastItem = items[i];
      break;
    }
  }

  if (!pastItem || !pastItem.price_cny_per_gram) {
    return null;
  }

  return ((latestPrice - pastItem.price_cny_per_gram) / pastItem.price_cny_per_gram) * 100;
}

async function loadDashboard() {
  const range = ranges[state.range];
  if (!range) return;

  const requestId = state.activeRequestId + 1;
  state.activeRequestId = requestId;

  if (state.activeController) {
    state.activeController.abort();
  }
  state.activeController = new AbortController();
  const { signal } = state.activeController;

  updateStatus("同步中", "status-pending");

  try {
    const [
      current,
      sourceQuality,
      sourceDiagnostics,
      history,
      indicators,
      signals,
      advice,
      position,
      buySignal,
      signalPerformance,
      confidenceCenter,
      supportResistance,
      macroCorrelation,
      multiTimeframe,
      forecast,
      weeklyReport,
    ] = await Promise.all([
      fetchJSON("/api/price/current", signal),
      fetchJSON("/api/price/sources/latest", signal).catch(() => null),
      fetchJSON("/api/price/diagnostics/latest", signal).catch(() => null),
      fetchJSON(`/api/price/history?days=${range.days}&interval=${range.interval}`, signal),
      fetchJSON("/api/analysis/indicators", signal),
      fetchJSON(`/api/analysis/signals?days=${range.days}`, signal),
      fetchJSON("/api/analysis/advice", signal).catch(() => null),
      fetchJSON("/api/analysis/position", signal).catch(() => null),
      fetchJSON("/api/analysis/buy-signal", signal).catch(() => null),
      fetchJSON(`/api/analysis/signal-performance?window_days=${Math.max(range.days, 90)}`, signal).catch(
        () => null
      ),
      fetchJSON(`/api/analysis/confidence-center?window_days=${Math.max(range.days, 120)}`, signal).catch(
        () => null
      ),
      fetchJSON(`/api/analysis/support-resistance?window_days=${Math.max(range.days, 90)}`, signal).catch(
        () => null
      ),
      fetchJSON(`/api/analysis/macro-correlation?window_days=${Math.max(range.days, 120)}`, signal).catch(
        () => null
      ),
      fetchJSON(`/api/analysis/multi-timeframe?windows=1,7,30&lookback_days=${Math.max(range.days, 120)}`, signal).catch(
        () => null
      ),
      fetchJSON(`/api/analysis/forecast?lookback_days=${Math.max(range.days, 120)}&horizon_days=7`, signal).catch(
        () => null
      ),
      fetchJSON("/api/analysis/weekly-report?days=7", signal).catch(() => null),
    ]);

    if (requestId !== state.activeRequestId) {
      return;
    }

    updateStatus("在线", "online");

    const latestPrice = Number(current?.price_cny_per_gram);
    updatePrice({
      price_cny_per_gram: latestPrice,
      timestamp: current?.timestamp,
    });
    updateSourceQuality(sourceQuality);
    updateDecisionStrip({
      current,
      advice: advice?.data || null,
      sourceQuality,
    });
    updatePositionDecision(position?.data || null, advice?.data || null);
    updateSourceDiagnostics(sourceDiagnostics);

    const items = Array.isArray(history?.items) ? history.items : [];
    updateSignalPerformance(signalPerformance?.data || null);
    updateConfidenceCenter(confidenceCenter?.data || null);
    updateSupportResistance(supportResistance?.data || null);
    updateMacroCorrelation(macroCorrelation?.data || null);
    updateMultiTimeframe(multiTimeframe?.data || null);
    updateForecast(forecast?.data || null);
    updateWeeklyReport(weeklyReport?.data || null);
    await loadCustomAlerts(signal);
    await loadAlertDeliveries(signal);
    await loadEntryPlan(signal);
    state.lineChartContext = buildLineChartContext(items, range.interval);
    updateChartDiagnostics();
    const useTime = range.interval.includes("m") || range.interval.includes("h");
    const labels = items.map((item) =>
      useTime
        ? new Date(item.timestamp).toLocaleString()
        : new Date(item.timestamp).toLocaleDateString()
    );
    const prices = items.map((item) => {
      const price = Number(item.price_cny_per_gram);
      return Number.isFinite(price) ? price : null;
    });

    if (prices.some((price) => price != null)) {
      const ma30 = simpleMovingAverage(prices, 30);
      const bands = bollingerBands(prices, 20, 2);
      const signalPoints = (signals.items || [])
        .filter(
          (signalItem) =>
            signalItem?.timestamp && Number.isFinite(signalItem.price_cny_per_gram)
        )
        .map((signalItem) => ({
          x: useTime
            ? new Date(signalItem.timestamp).toLocaleString()
            : new Date(signalItem.timestamp).toLocaleDateString(),
          y: signalItem.price_cny_per_gram,
        }));
      buildChart(
        labels,
        prices,
        ma30,
        bands.upper,
        bands.lower,
        signalPoints,
        state.supportResistanceLines
      );
    }

    const change = calculate24hChange(items, latestPrice);
    const changeEl = getEl("price-change");
    if (changeEl) {
      changeEl.textContent = formatPercent(change);
    }

    if (indicators.status === "ok") {
      updateIndicators(indicators.items);
    } else {
      updateIndicators({});
    }

    updateSignals(signals.items || []);
    updateMarketBrief(advice?.data || null);
    updateSingleChartStatus(
      "line",
      history?.meta ? buildChartStatusFromMeta("line", history.meta) : advice?.data?.chart_status?.line
    );
    updateSingleChartStatus(
      "candlestick",
      advice?.data?.chart_status?.candlestick || buildChartStatusFromMeta("candlestick", null)
    );
    updateSignalDebug({
      ...(buySignal?.data || {}),
      confidence: advice?.data?.confidence,
      dominant_factor: advice?.data?.dominant_factor,
      recommendation_change_reason: advice?.data?.recommendation_change_reason,
      explainability: advice?.data?.explainability,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      return;
    }
    updateSignalPerformance(null);
    updateSupportResistance(null);
    updateMacroCorrelation(null);
    updateMultiTimeframe(null);
    updateForecast(null);
    updateWeeklyReport(null);
    renderEntryPlan(null);
    updateDecisionStrip({ current: null, advice: null, sourceQuality: null });
    updatePositionDecision(null, null);
    updateSourceDiagnostics(null);
    updateStatus("离线", "offline");
    console.error(error);
  } finally {
    if (requestId === state.activeRequestId) {
      state.activeController = null;
    }
  }
}

function bindRangeSwitch() {
  const container = getEl("range-switch");
  if (!container) return;

  container.addEventListener("click", (event) => {
    if (!(event.target instanceof HTMLButtonElement)) return;
    const range = event.target.dataset.range;
    if (!range || range === state.range || !ranges[range]) return;
    state.range = range;

    container.querySelectorAll("button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.range === range);
    });

    loadDashboard();
  });
}

function startAutoRefresh() {
  if (state.refreshHandle) {
    window.clearInterval(state.refreshHandle);
  }
  state.refreshHandle = window.setInterval(() => {
    if (!document.hidden) {
      loadDashboard();
    }
  }, REFRESH_INTERVAL_MS);
}

function initDashboard() {
  bindCustomAlertPanel();
  bindRangeSwitch();
  loadDashboard();
  startAutoRefresh();
}

window.loadDashboard = loadDashboard;
window.updatePrice = updatePrice;
window.updateIndicators = updateIndicators;
window.showSignalAlert = showSignalAlert;
window.updateCandlestickChartContext = (items, interval) => {
  state.candlestickChartContext = buildCandlestickChartContext(items, interval);
  updateChartDiagnostics();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initDashboard);
} else {
  initDashboard();
}
