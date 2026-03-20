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
};

function getEl(id) {
  return document.getElementById(id);
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
    oversold: "超卖",
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
    .map((flag) => `<span class="debug-flag ${toneClass}">${formatter(flag)}</span>`)
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

function buildLineChartContext(items, interval) {
  const points = Array.isArray(items) ? items : [];
  if (!points.length) {
    return {
      state: "数据不足",
      detail: "当前没有足够的折线图数据，无法判断缺口是否来自过滤或采样缺失。",
    };
  }

  const missingBuckets = countMissingBuckets(points, interval);
  const detailParts = [];

  if (missingBuckets > 0) {
    detailParts.push(
      `检测到 ${missingBuckets} 个时间桶缺口，这通常表示异常价段已被过滤，或该时间段没有采样点。`
    );
  } else {
    detailParts.push("价格主线连续，当前没有检测到明显的时间桶缺口。");
  }

  if (points.length < 30) {
    detailParts.push("MA30 与布林带需要 20 到 30 个样本预热，前段断续属于正常现象。");
  } else {
    detailParts.push("若你看到均线或布林带前段短暂断点，通常是指标窗口预热而不是渲染故障。");
  }

  return {
    state: missingBuckets > 0 ? "存在缺口（正常）" : "连续",
    detail: detailParts.join(" "),
  };
}

function classifyCandlestickActivity(item) {
  const activity = Number(item?.activity);
  const dataPoints = Number(item?.data_points);
  if (activity >= 8 || dataPoints >= 20) return "高";
  if (activity >= 2 || dataPoints >= 8) return "中";
  return "低";
}

function buildCandlestickChartContext(items, interval) {
  const candles = Array.isArray(items) ? items : [];
  if (!candles.length) {
    return {
      state: "等待K线数据",
      detail: "切换到 K 线图并成功加载数据后，这里会说明最新 K 线方向和活跃度状态。",
    };
  }

  const latest = candles[candles.length - 1];
  const missingBuckets = countMissingBuckets(candles, interval);
  const activityLevel = classifyCandlestickActivity(latest);
  let direction = "十字";
  if (latest.close > latest.open) direction = "阳线";
  if (latest.close < latest.open) direction = "阴线";

  const detailParts = [
    `最新一根为${direction}，活跃度${activityLevel}，包含 ${latest.data_points} 个采样点。`,
  ];

  if (missingBuckets > 0) {
    detailParts.push(`检测到 ${missingBuckets} 个 K 线时间桶缺口，通常表示该时段无有效数据或异常价段已被过滤。`);
  } else {
    detailParts.push("K线时间桶连续，当前聚合结果完整。");
  }

  return {
    state: `${direction} · 活跃度${activityLevel}`,
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
    detail: "折线图状态会在历史数据加载后显示。",
  };
  const candlestickContext = state.candlestickChartContext || {
    state: "等待分析",
    detail: "切换到 K 线图后会补充最新状态说明。",
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
  entryStatusEl.textContent = evaluation.entry_ready ? "确认通过" : "暂不入场";
  confidenceEl.textContent = Number.isFinite(evaluation.confidence)
    ? `${Math.round(evaluation.confidence * 100)}%`
    : "--";
  dominantFactorEl.textContent = evaluation.dominant_factor || "多因子共同作用";
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
    ? factorChanges.map((item) => `<li>${item}</li>`).join("")
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
    ? reasons.map((reason) => `<li>${stripLeadingEmoji(reason)}</li>`).join("")
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
          `<span class="risk-chip ${getRiskToneClass(flag)}">${prettifyRiskFlag(flag)}</span>`
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
    ? insightItems.map((item) => `<li>${stripLeadingEmoji(item)}</li>`).join("")
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

function buildChart(labels, prices, ma30, bbUpper, bbLower, signalPoints) {
  const canvas = getEl("priceChart");
  if (!canvas || typeof Chart === "undefined") {
    return;
  }

  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }

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
        },
        {
          label: "MA30",
          data: ma30,
          borderColor: "rgba(47, 214, 198, 0.88)",
          borderWidth: 1.6,
          pointRadius: 0,
          tension: 0.22,
        },
        {
          label: "布林上轨",
          data: bbUpper,
          borderColor: "rgba(247, 190, 86, 0.56)",
          borderDash: [6, 6],
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.2,
        },
        {
          label: "布林下轨",
          data: bbLower,
          borderColor: "rgba(247, 190, 86, 0.56)",
          borderDash: [6, 6],
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.2,
        },
        {
          type: "scatter",
          label: "信号",
          data: signalPoints,
          borderColor: "#2fd6c6",
          backgroundColor: "#2fd6c6",
          pointRadius: 4,
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
    const [current, history, indicators, signals, advice, buySignal] = await Promise.all([
      fetchJSON("/api/price/current", signal),
      fetchJSON(`/api/price/history?days=${range.days}&interval=${range.interval}`, signal),
      fetchJSON("/api/analysis/indicators", signal),
      fetchJSON(`/api/analysis/signals?days=${range.days}`, signal),
      fetchJSON("/api/analysis/advice", signal).catch(() => null),
      fetchJSON("/api/analysis/buy-signal", signal).catch(() => null),
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

    const items = Array.isArray(history?.items) ? history.items : [];
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
      buildChart(labels, prices, ma30, bands.upper, bands.lower, signalPoints);
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
