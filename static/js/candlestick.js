/**
 * K线图和活跃度图表模块
 * 使用 Lightweight Charts 库实现专业的K线图展示
 */

let candlestickChart = null;
let candlestickSeries = null;
let activitySeries = null;
let currentChartType = 'line'; // 'line' or 'candlestick'
let currentInterval = '1h';

/**
 * 初始化K线图
 */
function initCandlestickChart() {
  const container = document.getElementById('candlestick-container');
  if (!container) return;

  // 创建图表
  candlestickChart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 500,
    layout: {
      background: { color: '#1a1d29' },
      textColor: '#9aa2b1',
    },
    grid: {
      vertLines: { color: 'rgba(255,255,255,0.05)' },
      horzLines: { color: 'rgba(255,255,255,0.05)' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: 'rgba(255,255,255,0.1)',
    },
    timeScale: {
      borderColor: 'rgba(255,255,255,0.1)',
      timeVisible: true,
      secondsVisible: false,
    },
  });

  // 创建K线系列
  candlestickSeries = candlestickChart.addCandlestickSeries({
    upColor: '#8bd3c7',
    downColor: '#f08080',
    borderVisible: false,
    wickUpColor: '#8bd3c7',
    wickDownColor: '#f08080',
  });

  // 创建活跃度柱状图(在下方)
  activitySeries = candlestickChart.addHistogramSeries({
    color: '#26a69a',
    priceFormat: {
      type: 'volume',
    },
    priceScaleId: 'activity',
    scaleMargins: {
      top: 0.7,
      bottom: 0,
    },
  });

  // 响应式调整
  window.addEventListener('resize', () => {
    if (candlestickChart && container) {
      candlestickChart.applyOptions({
        width: container.clientWidth,
      });
    }
  });

  return candlestickChart;
}

/**
 * 加载K线数据
 */
async function loadCandlestickData(days = 7, interval = '1h') {
  try {
    const response = await fetch(`/api/price/candlestick?days=${days}&interval=${interval}`);
    const data = await response.json();

    if (!data.items || data.items.length === 0) {
      console.warn('No candlestick data available');
      return;
    }

    // 转换数据格式
    const candlestickData = data.items.map(item => ({
      time: new Date(item.timestamp).getTime() / 1000,
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }));

    const activityData = data.items.map(item => ({
      time: new Date(item.timestamp).getTime() / 1000,
      value: item.activity,
      color: item.close >= item.open ? 'rgba(139, 211, 199, 0.5)' : 'rgba(240, 128, 128, 0.5)',
    }));

    // 更新图表
    if (candlestickSeries) {
      candlestickSeries.setData(candlestickData);
    }

    if (activitySeries) {
      activitySeries.setData(activityData);
    }

    // 自动调整可见范围
    if (candlestickChart) {
      candlestickChart.timeScale().fitContent();
    }

  } catch (error) {
    console.error('Failed to load candlestick data:', error);
  }
}

/**
 * 切换图表类型
 */
function switchChartType(type) {
  currentChartType = type;

  const lineChartContainer = document.getElementById('priceChart').parentElement;
  const candlestickContainer = document.getElementById('candlestick-container');
  const intervalSwitch = document.getElementById('interval-switch');
  const rangeSwitch = document.getElementById('range-switch');

  if (type === 'line') {
    // 显示折线图,隐藏K线图
    lineChartContainer.querySelector('canvas').style.display = 'block';
    if (candlestickContainer) {
      candlestickContainer.style.display = 'none';
    }
    if (intervalSwitch) {
      intervalSwitch.style.display = 'none';
    }
    if (rangeSwitch) {
      rangeSwitch.style.display = 'flex';
    }
    // 重新加载折线图数据
    if (window.loadDashboard) {
      loadDashboard();
    }
  } else if (type === 'candlestick') {
    // 隐藏折线图,显示K线图
    lineChartContainer.querySelector('canvas').style.display = 'none';
    if (candlestickContainer) {
      candlestickContainer.style.display = 'block';
    }
    if (intervalSwitch) {
      intervalSwitch.style.display = 'flex';
    }
    if (rangeSwitch) {
      rangeSwitch.style.display = 'none';
    }
    // 初始化K线图(如果还没初始化)
    if (!candlestickChart) {
      initCandlestickChart();
    }
    // 加载K线数据
    loadCandlestickData(7, currentInterval);
  }

  // 更新按钮状态
  document.querySelectorAll('.chart-type-switch button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.type === type);
  });
}

/**
 * 切换K线时间间隔
 */
function switchCandlestickInterval(interval) {
  currentInterval = interval;

  // 根据间隔调整天数
  const daysMap = {
    '1h': 7,
    '4h': 30,
    '1d': 90,
  };

  const days = daysMap[interval] || 7;
  loadCandlestickData(days, interval);

  // 更新按钮状态
  document.querySelectorAll('.interval-switch button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.interval === interval);
  });
}

/**
 * 绑定图表类型切换事件
 */
function bindChartTypeSwitch() {
  const container = document.getElementById('chart-type-switch');
  if (!container) return;

  container.addEventListener('click', (event) => {
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
  const container = document.getElementById('interval-switch');
  if (!container) return;

  container.addEventListener('click', (event) => {
    if (!(event.target instanceof HTMLButtonElement)) return;
    const interval = event.target.dataset.interval;
    if (interval) {
      switchCandlestickInterval(interval);
    }
  });
}

// 页面加载时初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    bindChartTypeSwitch();
    bindIntervalSwitch();
  });
} else {
  bindChartTypeSwitch();
  bindIntervalSwitch();
}
