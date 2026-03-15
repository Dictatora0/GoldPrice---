const ranges = {
  "7D": { days: 7, interval: "30m" },
  "30D": { days: 30, interval: "2h" },
  "90D": { days: 90, interval: "6h" },
  "1Y": { days: 365, interval: "1d" },
  "ALL": { days: 3650, interval: "1d" },
};

const state = {
  range: "30D",
  chart: null,
};

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${url}`);
  }
  return response.json();
}

function formatPrice(value) {
  if (value == null) return "--";
  return `¥${Number(value).toFixed(2)}/克`;
}

function formatPercent(value) {
  if (value == null || Number.isNaN(value)) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function simpleMovingAverage(values, windowSize) {
  return values.map((_, idx) => {
    if (idx + 1 < windowSize) return null;
    const slice = values.slice(idx + 1 - windowSize, idx + 1);
    const avg = slice.reduce((sum, v) => sum + v, 0) / windowSize;
    return Number(avg.toFixed(2));
  });
}

function bollingerBands(values, windowSize, factor) {
  const upper = [];
  const lower = [];
  for (let i = 0; i < values.length; i += 1) {
    if (i + 1 < windowSize) {
      upper.push(null);
      lower.push(null);
      continue;
    }
    const slice = values.slice(i + 1 - windowSize, i + 1);
    const mean = slice.reduce((sum, v) => sum + v, 0) / windowSize;
    const variance = slice.reduce((sum, v) => sum + (v - mean) ** 2, 0) / windowSize;
    const std = Math.sqrt(variance);
    upper.push(Number((mean + factor * std).toFixed(2)));
    lower.push(Number((mean - factor * std).toFixed(2)));
  }
  return { upper, lower };
}

function updateIndicators(indicators) {
  const list = document.getElementById("indicator-list");
  list.innerHTML = "";

  const entries = [
    ["MA7", indicators.ma_short],
    ["MA30", indicators.ma_medium],
    ["MA90", indicators.ma_long],
    ["布林上轨", indicators.bb_upper],
    ["布林中轨", indicators.bb_middle],
    ["布林下轨", indicators.bb_lower],
    ["RSI", indicators.rsi],
    ["波动率", indicators.volatility],
  ];

  entries.forEach(([label, value]) => {
    const li = document.createElement("li");
    const display = value == null ? "--" : Number(value).toFixed(2);
    li.textContent = `${label}: ${display}`;
    list.appendChild(li);
  });

  document.getElementById("metric-rsi").textContent =
    indicators.rsi == null ? "--" : indicators.rsi.toFixed(2);
  document.getElementById("metric-volatility").textContent =
    indicators.volatility == null ? "--" : indicators.volatility.toFixed(2);
  document.getElementById("metric-ma").textContent =
    indicators.ma_medium == null ? "--" : indicators.ma_medium.toFixed(2);
  document.getElementById("metric-bb").textContent =
    indicators.bb_lower == null ? "--" : indicators.bb_lower.toFixed(2);
}

function updateSignals(signals) {
  const list = document.getElementById("signal-list");
  list.innerHTML = "";

  if (!signals.length) {
    const li = document.createElement("li");
    li.textContent = "暂无信号";
    list.appendChild(li);
    return;
  }

  signals.slice(0, 6).forEach((signal) => {
    const li = document.createElement("li");
    const time = new Date(signal.timestamp).toLocaleString();
    li.textContent = `${time} · ¥${signal.price_cny_per_gram.toFixed(2)} · ${signal.signal_type}`;
    list.appendChild(li);
  });

  const latest = signals[0];
  document.getElementById("signal-state").textContent = "触发买入信号";
  document.getElementById("signal-reason").textContent =
    `价格 ¥${latest.price_cny_per_gram.toFixed(2)} · RSI ${latest.indicators?.rsi ?? "--"}`;
}

function buildChart(labels, prices, ma30, bbUpper, bbLower, signalPoints) {
  const ctx = document.getElementById("priceChart");
  if (state.chart) {
    state.chart.destroy();
  }

  state.chart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "价格",
          data: prices,
          borderColor: "#f0d08b",
          backgroundColor: "rgba(240, 208, 139, 0.15)",
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.25,
        },
        {
          label: "MA30",
          data: ma30,
          borderColor: "rgba(139, 211, 199, 0.9)",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.25,
        },
        {
          label: "布林上轨",
          data: bbUpper,
          borderColor: "rgba(212, 178, 111, 0.6)",
          borderDash: [6, 6],
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.2,
        },
        {
          label: "布林下轨",
          data: bbLower,
          borderColor: "rgba(212, 178, 111, 0.6)",
          borderDash: [6, 6],
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.2,
        },
        {
          type: "scatter",
          label: "信号",
          data: signalPoints,
          borderColor: "#8bd3c7",
          backgroundColor: "#8bd3c7",
          pointRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: {
            color: "#9aa2b1",
            boxWidth: 12,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: "#7f8795",
            maxTicksLimit: 6,
          },
          grid: {
            color: "rgba(255,255,255,0.05)",
          },
        },
        y: {
          ticks: {
            color: "#7f8795",
          },
          grid: {
            color: "rgba(255,255,255,0.05)",
          },
        },
      },
    },
  });
}

async function loadDashboard() {
  const range = ranges[state.range];
  const status = document.getElementById("status-pill");
  try {
    const [current, history, indicators, signals] = await Promise.all([
      fetchJSON("/api/price/current"),
      fetchJSON(`/api/price/history?days=${range.days}&interval=${range.interval}`),
      fetchJSON("/api/analysis/indicators"),
      fetchJSON(`/api/analysis/signals?days=${range.days}`),
    ]);

    status.textContent = "在线";

    const latestPrice = current.price_cny_per_gram;
    document.getElementById("current-price").textContent = formatPrice(latestPrice);
    document.getElementById("last-updated").textContent = new Date(
      current.timestamp
    ).toLocaleString();

    const items = history.items || [];
    const useTime = range.interval.includes("m") || range.interval.includes("h");
    const labels = items.map((item) =>
      useTime
        ? new Date(item.timestamp).toLocaleString()
        : new Date(item.timestamp).toLocaleDateString()
    );
    const prices = items.map((item) => item.price_cny_per_gram);

    const ma30 = simpleMovingAverage(prices, 30);
    const bands = bollingerBands(prices, 20, 2);

    const signalPoints = (signals.items || []).map((signal) => ({
      x: useTime
        ? new Date(signal.timestamp).toLocaleString()
        : new Date(signal.timestamp).toLocaleDateString(),
      y: signal.price_cny_per_gram,
    }));

    buildChart(labels, prices, ma30, bands.upper, bands.lower, signalPoints);

    let change = null;
    if (items.length > 1) {
      const latestTime = new Date(items[items.length - 1].timestamp).getTime();
      const targetTime = latestTime - 24 * 60 * 60 * 1000;
      const pastItem = items.find(
        (item) => new Date(item.timestamp).getTime() >= targetTime
      );
      if (pastItem) {
        change =
          ((latestPrice - pastItem.price_cny_per_gram) / pastItem.price_cny_per_gram) *
          100;
      }
    }
    document.getElementById("price-change").textContent = formatPercent(change);

    if (indicators.status === "ok") {
      updateIndicators(indicators.items);
    }

    updateSignals(signals.items || []);
  } catch (error) {
    status.textContent = "离线";
    console.error(error);
  }
}

function bindRangeSwitch() {
  const container = document.getElementById("range-switch");
  container.addEventListener("click", (event) => {
    if (!(event.target instanceof HTMLButtonElement)) return;
    const range = event.target.dataset.range;
    if (!range || range === state.range) return;
    state.range = range;

    container.querySelectorAll("button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.range === range);
    });

    loadDashboard();
  });
}

bindRangeSwitch();
loadDashboard();
setInterval(loadDashboard, 180000);
