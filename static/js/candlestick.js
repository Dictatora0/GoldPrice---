/**
 * K线图和活跃度图表模块
 * 使用 Lightweight Charts 库实现专业的K线图展示
 */

const CANDLESTICK_REQUEST_TIMEOUT_MS = 10000;
const LIGHTWEIGHT_CHARTS_SOURCES = [
  "https://cdn.jsdelivr.net/npm/lightweight-charts@5.0.9/dist/lightweight-charts.standalone.production.js",
  "https://unpkg.com/lightweight-charts@5.0.9/dist/lightweight-charts.standalone.production.js",
];

let candlestickChart = null;
let candlestickSeries = null;
let activitySeries = null;
let currentChartType = "line"; // "line" or "candlestick"
let currentInterval = "1h";
let pendingCandlestickController = null;
let resizeBound = false;
let lightweightChartsLoadPromise = null;

function getCandlestickContainer() {
  return document.getElementById("candlestick-container");
}

function renderCandlestickPlaceholder(message) {
  const container = getCandlestickContainer();
  if (!container || candlestickChart) return;

  container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;padding:24px;color:#9bb1cc;font-size:14px;">${message}</div>`;
}

function clearCandlestickPlaceholder() {
  const container = getCandlestickContainer();
  if (!container || candlestickChart) return;
  container.innerHTML = "";
}

function injectScript(url) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.async = true;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`Failed to load script: ${url}`));
    document.head.appendChild(script);
  });
}

async function loadScriptSequentially(urls) {
  let lastError = null;

  for (const url of urls) {
    try {
      await injectScript(url);
      if (typeof LightweightCharts !== "undefined") {
        return LightweightCharts;
      }
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError || new Error("Failed to load Lightweight Charts");
}

async function ensureLightweightChartsLoaded() {
  if (typeof LightweightCharts !== "undefined") {
    return LightweightCharts;
  }

  if (!lightweightChartsLoadPromise) {
    lightweightChartsLoadPromise = loadScriptSequentially(LIGHTWEIGHT_CHARTS_SOURCES).catch(
      (error) => {
        lightweightChartsLoadPromise = null;
        throw error;
      }
    );
  }

  return lightweightChartsLoadPromise;
}

function getCandlestickChartSize(container) {
  const fallbackWidth = container?.parentElement?.clientWidth || 640;
  const fallbackHeight = container?.parentElement?.clientHeight || 360;

  return {
    width: Math.max(container?.clientWidth || fallbackWidth, 1),
    height: Math.max(container?.clientHeight || fallbackHeight, 240),
  };
}

function addChartSeries(chart, legacyMethod, modernSeriesType, options) {
  if (!chart) return null;

  if (typeof chart[legacyMethod] === "function") {
    return chart[legacyMethod](options);
  }

  if (
    typeof chart.addSeries === "function" &&
    typeof modernSeriesType !== "undefined"
  ) {
    return chart.addSeries(modernSeriesType, options);
  }

  return null;
}

function resizeCandlestickChart() {
  const container = getCandlestickContainer();
  if (!candlestickChart || !container) return;
  candlestickChart.applyOptions(getCandlestickChartSize(container));
}

function toChartTime(timestamp) {
  return Math.floor(new Date(timestamp).getTime() / 1000);
}

/**
 * 初始化K线图
 */
function initCandlestickChart() {
  const container = getCandlestickContainer();
  const chartsApi = typeof LightweightCharts !== "undefined" ? LightweightCharts : null;
  if (!container || !chartsApi) return null;

  if (candlestickChart) {
    resizeCandlestickChart();
    return candlestickChart;
  }

  clearCandlestickPlaceholder();

  const chartSize = getCandlestickChartSize(container);

  candlestickChart = chartsApi.createChart(container, {
    width: chartSize.width,
    height: chartSize.height,
    layout: {
      background: { color: "#030a13" },
      textColor: "#9bb1cc",
    },
    grid: {
      vertLines: { color: "rgba(84, 128, 172, 0.2)" },
      horzLines: { color: "rgba(84, 128, 172, 0.2)" },
    },
    crosshair: {
      mode: chartsApi.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: "rgba(126, 172, 221, 0.24)",
    },
    timeScale: {
      borderColor: "rgba(126, 172, 221, 0.24)",
      timeVisible: true,
      secondsVisible: false,
    },
  });

  candlestickSeries = addChartSeries(
    candlestickChart,
    "addCandlestickSeries",
    LightweightCharts.CandlestickSeries,
    {
      upColor: "#2fd6c6",
      downColor: "#ff8f7f",
      borderVisible: false,
      wickUpColor: "#2fd6c6",
      wickDownColor: "#ff8f7f",
    }
  );

  activitySeries = addChartSeries(
    candlestickChart,
    "addHistogramSeries",
    LightweightCharts.HistogramSeries,
    {
      color: "rgba(47, 214, 198, 0.36)",
      priceFormat: {
        type: "volume",
      },
      priceScaleId: "activity",
      scaleMargins: {
        top: 0.72,
        bottom: 0,
      },
    }
  );

  if (!candlestickSeries || !activitySeries) {
    candlestickChart.remove();
    candlestickChart = null;
    candlestickSeries = null;
    activitySeries = null;
    return null;
  }

  if (!resizeBound) {
    resizeBound = true;
    window.addEventListener("resize", resizeCandlestickChart);
  }

  window.requestAnimationFrame(() => {
    resizeCandlestickChart();
    candlestickChart?.timeScale().fitContent();
  });

  return candlestickChart;
}

/**
 * 带超时的请求，避免慢请求阻塞切图
 */
async function fetchCandlestickJSON(url, signal) {
  const timeoutController = new AbortController();
  const timeoutId = window.setTimeout(
    () => timeoutController.abort(),
    CANDLESTICK_REQUEST_TIMEOUT_MS
  );

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
      throw new Error("Failed to fetch candlestick data");
    }
    return response.json();
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/**
 * 加载K线数据
 */
async function loadCandlestickData(days = 7, interval = "1h") {
  if (pendingCandlestickController) {
    pendingCandlestickController.abort();
  }
  pendingCandlestickController = new AbortController();
  const { signal } = pendingCandlestickController;

  try {
    const data = await fetchCandlestickJSON(
      `/api/price/candlestick?days=${days}&interval=${interval}`,
      signal
    );

    if (!data.items || data.items.length === 0) {
      if (candlestickSeries) candlestickSeries.setData([]);
      if (activitySeries) activitySeries.setData([]);
      if (typeof window.updateCandlestickChartContext === "function") {
        window.updateCandlestickChartContext([], interval);
      }
      return;
    }

    const candlestickData = data.items.map((item) => ({
      time: toChartTime(item.timestamp),
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }));

    const activityData = data.items.map((item) => ({
      time: toChartTime(item.timestamp),
      value: item.activity,
      color:
        item.close >= item.open
          ? "rgba(47, 214, 198, 0.42)"
          : "rgba(255, 143, 127, 0.45)",
    }));

    if (candlestickSeries) {
      candlestickSeries.setData(candlestickData);
    }
    if (activitySeries) {
      activitySeries.setData(activityData);
    }
    if (typeof window.updateCandlestickChartContext === "function") {
      window.updateCandlestickChartContext(data.items, interval);
    }
    if (candlestickChart) {
      resizeCandlestickChart();
      candlestickChart.timeScale().fitContent();
    }
  } catch (error) {
    if (error?.name === "AbortError") return;
    console.error("Failed to load candlestick data:", error);
  } finally {
    if (pendingCandlestickController?.signal === signal) {
      pendingCandlestickController = null;
    }
  }
}

async function showCandlestickChart(days = 7, interval = currentInterval) {
  try {
    await ensureLightweightChartsLoaded();
    if (!initCandlestickChart()) {
      throw new Error("Failed to initialize Lightweight Charts");
    }
    await loadCandlestickData(days, interval);
  } catch (error) {
    renderCandlestickPlaceholder("K线图组件加载失败，请稍后重试");
    console.error("Failed to load Lightweight Charts:", error);
  }
}

/**
 * 切换图表类型
 */
function switchChartType(type) {
  currentChartType = type;

  const canvas = document.getElementById("priceChart");
  const lineChartContainer = canvas ? canvas.parentElement : null;
  const candlestickContainer = document.getElementById("candlestick-container");
  if (!canvas || !lineChartContainer || !candlestickContainer) return;

  const intervalSwitch = document.getElementById("interval-switch");
  const rangeSwitch = document.getElementById("range-switch");

  if (type === "line") {
    canvas.style.display = "block";
    candlestickContainer.style.display = "none";
    if (intervalSwitch) {
      intervalSwitch.style.display = "none";
    }
    if (rangeSwitch) {
      rangeSwitch.style.display = "flex";
    }
    if (typeof window.loadDashboard === "function") {
      window.loadDashboard();
    }
  } else if (type === "candlestick") {
    canvas.style.display = "none";
    candlestickContainer.style.display = "block";
    if (intervalSwitch) {
      intervalSwitch.style.display = "flex";
    }
    if (rangeSwitch) {
      rangeSwitch.style.display = "none";
    }
    window.requestAnimationFrame(() => {
      showCandlestickChart(7, currentInterval);
    });
  }

  document.querySelectorAll(".chart-type-switch button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.type === type);
  });
}

/**
 * 切换K线时间间隔
 */
function switchCandlestickInterval(interval) {
  currentInterval = interval;

  const daysMap = {
    "1h": 7,
    "4h": 30,
    "1d": 90,
  };

  const days = daysMap[interval] || 7;
  if (currentChartType === "candlestick") {
    loadCandlestickData(days, interval);
  }

  document.querySelectorAll(".interval-switch button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.interval === interval);
  });
}

/**
 * 绑定图表类型切换事件
 */
function bindChartTypeSwitch() {
  const container = document.getElementById("chart-type-switch");
  if (!container) return;

  container.addEventListener("click", (event) => {
    if (!(event.target instanceof HTMLButtonElement)) return;
    const type = event.target.dataset.type;
    if (type) {
      switchChartType(type);
    }
  });
}

/**
 * 绑定K线间隔切换事件
 */
function bindIntervalSwitch() {
  const container = document.getElementById("interval-switch");
  if (!container) return;

  container.addEventListener("click", (event) => {
    if (!(event.target instanceof HTMLButtonElement)) return;
    const interval = event.target.dataset.interval;
    if (interval) {
      switchCandlestickInterval(interval);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    bindChartTypeSwitch();
    bindIntervalSwitch();
  });
} else {
  bindChartTypeSwitch();
  bindIntervalSwitch();
}
